import { backendFetch } from "./config"
import type { Song } from "./types"

type MusicQueue = {
  items: { id: string }[]
}

type MusicKitInstance = {
  isAuthorized: boolean
  isPlaying: boolean
  nowPlayingItem: { id: string } | null
  queue: MusicQueue
  authorize: () => Promise<string>
  unauthorize: () => Promise<void>
  setQueue: (queue: { songs?: string[]; song?: string }) => Promise<MusicQueue>
  play: () => Promise<void>
  pause: () => Promise<void>
  seekToTime: (seconds: number) => Promise<void>
  // 0 = no repeat, 1 = repeat the current song. The enum is not exposed by
  // the MusicKit JS build, so the numeric value is used directly.
  repeatMode: number
}

type MusicKitGlobal = {
  configure?: (config: {
    developerToken: string
    app: { name: string; build: string }
  }) => MusicKitInstance | Promise<MusicKitInstance>
  getInstance: () => MusicKitInstance | undefined
}

declare global {
  interface Window {
    // MusicKit is the vendor-defined browser global name.
    // biome-ignore lint/style/useNamingConvention: external API name
    MusicKit?: MusicKitGlobal
  }
}

const developerTokenCache: { expiresAt: number; value: string | null } = {
  expiresAt: 0,
  value: null,
}

const apiOrigin = "https://api.music.apple.com"
const playbackOrigin = "https://play.itunes.apple.com"
const tokenRefreshGraceMs = 60_000
const playlistSearchLimit = 10
const songPageLimit = 100
const secondsToMilliseconds = 1000
const artworkSize = "120"

const musicReady = () => window.MusicKit?.getInstance() !== undefined

const musicInstance = () => window.MusicKit?.getInstance()

async function initializeMusicKit(): Promise<boolean> {
  try {
    await ensureDeveloperToken()
    const music = window.MusicKit
    if (music === undefined) {
      return false
    }
    if (music.getInstance() === undefined && music.configure !== undefined) {
      await music.configure({
        developerToken: developerTokenCache.value ?? "",
        app: { name: "ATERUTA", build: "1.0.0" },
      })
    }
    return music.getInstance() !== undefined
  } catch {
    return false
  }
}

async function ensureDeveloperToken(allowRetry = true): Promise<string> {
  const now = Date.now()
  if (
    developerTokenCache.value !== null &&
    developerTokenCache.expiresAt - now > tokenRefreshGraceMs
  ) {
    return developerTokenCache.value
  }
  const response = await backendFetch("/api/token")
  if (!response.ok) {
    throw new Error("Failed to load Apple Music token")
  }
  const data = (await response.json()) as { token: string; expiresAt: string }
  developerTokenCache.value = data.token
  developerTokenCache.expiresAt = Date.parse(data.expiresAt)
  if (
    !Number.isFinite(developerTokenCache.expiresAt) ||
    developerTokenCache.expiresAt <= now
  ) {
    developerTokenCache.value = null
    if (allowRetry) {
      return ensureDeveloperToken(false)
    }
    throw new Error("Expired Apple Music token")
  }
  return developerTokenCache.value
}

async function probeAuthorized(): Promise<boolean> {
  try {
    const response = await appleFetch(`${apiOrigin}/v1/me/account`)
    return response.ok
  } catch {
    return false
  }
}

async function publicPlaylistSearch(query: string): Promise<Playlist[]> {
  const url = new URL(`${apiOrigin}/v1/catalog/us/search`)
  url.searchParams.set("types", "playlists")
  url.searchParams.set("term", query)
  url.searchParams.set("limit", String(playlistSearchLimit))
  const response = await appleFetch(url.toString())
  if (!response.ok) {
    throw new Error("Playlist search failed")
  }
  const body = await response.json()
  const raw = body?.results?.playlists?.data
  return Array.isArray(raw)
    ? raw.slice(0, playlistSearchLimit).map(playlistFromResource)
    : []
}

type Playlist = {
  id: string
  name: string
  artworkUrl: string | null
  source: "catalog" | "library"
}

function loadPlaylistSongs(playlist: Playlist): Promise<Song[]> {
  const path =
    playlist.source === "library"
      ? `/v1/me/library/playlists/${playlist.id}/tracks`
      : `/v1/catalog/us/playlists/${playlist.id}/tracks`
  return loadSongsFromPath(path)
}

async function loadLibraryPlaylists(): Promise<Playlist[]> {
  const response = await appleFetch(`${apiOrigin}/v1/me/library/playlists`)
  if (!response.ok) {
    throw new Error("Library playlists failed")
  }
  const body = await response.json()
  return resourceArray(body).map(libraryPlaylistFromResource)
}

function loadPlaylistSongsById(id: string): Promise<Song[]> {
  return loadSongsFromPath(`/v1/catalog/us/playlists/${id}/tracks`)
}

async function prepareSong(songId: string): Promise<void> {
  const music = musicInstance()
  if (music === undefined) {
    return
  }
  await music.setQueue({ songs: [songId] })
}

const repeatModeOff = 0
const repeatModeOne = 1

async function playSong(
  songId: string,
  options: { duration?: number; loop?: boolean } = {}
): Promise<void> {
  const { duration, loop = false } = options
  await prepareSong(songId)
  const response = await appleFetch(
    `${playbackOrigin}/WebObjects/MZPlay.woa/wa/webPlayback`,
    {
      body: JSON.stringify({ salableAdamId: songId }),
      method: "POST",
    }
  )
  const payload = await response.json().catch(() => null)
  if (!response.ok || payload?.songList === undefined) {
    throw new Error("Song playback failed")
  }
  const music = musicInstance()
  if (music === undefined) {
    return
  }
  music.repeatMode = loop ? repeatModeOne : repeatModeOff
  await music.play()
  if (duration !== undefined) {
    window.setTimeout(() => {
      stopPlayback().catch(() => undefined)
    }, duration * secondsToMilliseconds)
  }
}

async function stopPlayback(): Promise<void> {
  const music = musicInstance()
  if (music === undefined) {
    return
  }
  await music.pause()
  await music.seekToTime(0)
}

async function loadSongsFromPath(
  path: string,
  offset = 0,
  loadedSongs: Song[] = []
): Promise<Song[]> {
  const url = new URL(`${apiOrigin}${path}`)
  url.searchParams.set("limit", String(songPageLimit))
  url.searchParams.set("offset", String(offset))
  const response = await appleFetch(url.toString())
  if (!response.ok) {
    throw new Error("Network error")
  }
  const body = await response.json()
  const page = parseSongPage(body)
  const songs = loadedSongs.concat(page)
  const next = typeof body?.next === "string" ? body.next : null
  const hasNextPage = next !== null || page.length === songPageLimit
  if (!hasNextPage || page.length === 0) {
    return songs
  }
  return loadSongsFromPath(path, offset + page.length, songs)
}

function parseSongPage(body: unknown): Song[] {
  const data = resourceArray(body)
  return data.map(songFromResource).filter((song) => song.id.length > 0)
}

function resourceArray(body: unknown): Record<string, unknown>[] {
  if (typeof body !== "object" || body === null) {
    return []
  }
  const data = (body as { data?: unknown }).data
  return Array.isArray(data) ? data.filter(isRecord) : []
}

function playlistFromResource(resource: Record<string, unknown>): Playlist {
  const attributes = recordValue(resource.attributes)
  return {
    id: stringValue(resource.id),
    name: stringValue(attributes.name) || "Playlist",
    artworkUrl: artworkUrl(attributes.artwork),
    source: "catalog",
  }
}

function libraryPlaylistFromResource(
  resource: Record<string, unknown>
): Playlist {
  const attributes = recordValue(resource.attributes)
  return {
    id: stringValue(resource.id),
    name: stringValue(attributes.name) || "Playlist",
    artworkUrl: artworkUrl(attributes.artwork),
    source: "library",
  }
}

function songFromResource(resource: Record<string, unknown>): Song {
  const attributes = recordValue(resource.attributes)
  return {
    id: stringValue(resource.id),
    title: stringValue(attributes.name) || stringValue(attributes.title),
    artist:
      stringValue(attributes.artistName) || stringValue(attributes.artist),
    artworkUrl: artworkUrl(attributes.artwork),
  }
}

function artworkUrl(value: unknown): string | null {
  const artwork = recordValue(value)
  const url = stringValue(artwork.url)
  return url.replace("{w}", artworkSize).replace("{h}", artworkSize) || null
}

async function appleFetch(
  input: string,
  init?: RequestInit
): Promise<Response> {
  const token = await ensureDeveloperToken()
  const headers = new Headers(init?.headers)
  headers.set("Authorization", `Bearer ${token}`)
  return fetch(input, { ...init, headers })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function recordValue(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {}
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : ""
}

export type { Playlist }
export {
  ensureDeveloperToken,
  initializeMusicKit,
  loadLibraryPlaylists,
  loadPlaylistSongs,
  loadPlaylistSongsById,
  musicInstance,
  musicReady,
  playSong,
  prepareSong,
  probeAuthorized,
  publicPlaylistSearch,
  stopPlayback,
}
