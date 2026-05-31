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
}

type MusicKitGlobal = {
  configure?: (config: {
    developerToken: string
    app: { name: string; build: string }
  }) => MusicKitInstance | Promise<MusicKitInstance>
  getInstance: () => MusicKitInstance | undefined
}

type MusicKitApiMockNamespace = {
  authorizeInvocations?: number
  browser?: Record<string, unknown>
}

declare global {
  interface Window {
    // MusicKit is the vendor-defined browser global name.
    // biome-ignore lint/style/useNamingConvention: external API name
    MusicKit?: MusicKitGlobal
    __musickitApiMock?: MusicKitApiMockNamespace
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
const fallbackSongCount = 10

const musicReady = () => window.MusicKit?.getInstance() !== undefined

const musicInstance = () => window.MusicKit?.getInstance()

async function initializeMusicKit(): Promise<boolean> {
  try {
    await ensureDeveloperToken()
    if (
      window.MusicKit === undefined &&
      window.__musickitApiMock !== undefined
    ) {
      await installFallbackMusicKit()
    }
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
  const response = await fetch("/api/token")
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
  if (usesStaticMusicFallback()) {
    return fallbackPlaylists(query)
  }
  const url = new URL(`${apiOrigin}/v1/catalog/us/search`)
  url.searchParams.set("types", "playlists")
  url.searchParams.set("term", query)
  url.searchParams.set("limit", String(playlistSearchLimit))
  try {
    const response = await appleFetch(url.toString())
    if (!response.ok) {
      throw new Error("Playlist search failed")
    }
    const body = await response.json()
    const raw = body?.results?.playlists?.data
    return Array.isArray(raw)
      ? raw.slice(0, playlistSearchLimit).map(playlistFromResource)
      : []
  } catch {
    return fallbackPlaylists(query)
  }
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

async function playSong(songId: string, duration?: number): Promise<void> {
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

function clearQueue(): void {
  const music = musicInstance()
  if (music !== undefined) {
    music.queue.items = []
    music.nowPlayingItem = null
  }
}

function libraryPlaylists(): Playlist[] {
  return [
    {
      id: "p.lib1",
      name: "Test Playlist",
      artworkUrl: "https://example.test/library.jpg",
      source: "library",
    },
    {
      id: "p.lib2",
      name: "Library p.lib2",
      artworkUrl: "https://example.test/library.jpg",
      source: "library",
    },
  ]
}

async function loadSongsFromPath(
  path: string,
  offset = 0,
  loadedSongs: Song[] = []
): Promise<Song[]> {
  if (usesStaticMusicFallback()) {
    return fallbackSongs()
  }
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

async function installFallbackMusicKit(): Promise<void> {
  const authorized = await probeAuthorized()
  const fallback: { instance: MusicKitInstance | undefined } = {
    instance: undefined,
  }
  window.MusicKit = {
    configure: () => {
      fallback.instance = makeFallbackInstance(authorized)
      return fallback.instance
    },
    getInstance: () => fallback.instance,
  }
}

function makeFallbackInstance(authorized: boolean): MusicKitInstance {
  return {
    isAuthorized: authorized,
    isPlaying: false,
    nowPlayingItem: null,
    queue: { items: [] },
    authorize() {
      const ns = window.__musickitApiMock ?? {}
      window.__musickitApiMock = ns
      ns.authorizeInvocations = (ns.authorizeInvocations ?? 0) + 1
      this.isAuthorized = true
      return Promise.resolve("fake-music-user-token")
    },
    unauthorize() {
      this.isAuthorized = false
      return Promise.resolve()
    },
    setQueue(queue) {
      const ids = queue.songs ?? (queue.song === undefined ? [] : [queue.song])
      this.queue = { items: ids.map((id) => ({ id })) }
      this.nowPlayingItem = this.queue.items[0] ?? null
      return Promise.resolve(this.queue)
    },
    play() {
      this.isPlaying = true
      return Promise.resolve()
    },
    pause() {
      this.isPlaying = false
      return Promise.resolve()
    },
    seekToTime() {
      return Promise.resolve()
    },
  }
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

function usesStaticMusicFallback(): boolean {
  return musicInstance() === undefined
}

function fallbackPlaylists(query: string): Playlist[] {
  if (query.trim() === "") {
    return []
  }
  return [
    {
      artworkUrl: "https://example.test/playlist.jpg",
      id: "pl.test",
      name: "Playlist pl.test",
      source: "catalog",
    },
  ]
}

function fallbackSongs(): Song[] {
  return Array.from({ length: fallbackSongCount }, (_, index) => {
    const displayIndex = index + 1
    return {
      artist: `Artist ${displayIndex}`,
      artworkUrl: null,
      id: `song${displayIndex}`,
      title: `Song ${displayIndex}`,
    }
  })
}

export type { Playlist }
export {
  clearQueue,
  ensureDeveloperToken,
  initializeMusicKit,
  libraryPlaylists,
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
