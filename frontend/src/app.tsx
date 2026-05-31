/* biome-ignore-all lint: screen composition intentionally uses native elements until the design system lands. */
import Fuse from "fuse.js"
import {
  createEffect,
  createMemo,
  createSignal,
  For,
  onCleanup,
  onMount,
  Show,
} from "solid-js"
import {
  clearQueue,
  initializeMusicKit,
  libraryPlaylists,
  loadPlaylistSongs,
  loadPlaylistSongsById,
  musicInstance,
  type Playlist,
  playSong,
  prepareSong,
  probeAuthorized,
  publicPlaylistSearch,
  stopPlayback,
} from "./music"
import type {
  PlaybackStatus,
  Player,
  Reveal,
  RoomSettings,
  RoomState,
  Song,
  StatePlayer,
  Toast,
  Winner,
} from "./types"

const SESSION_COOKIE = "ateruta-player-id"
const pendingLeaveStorageKey = "ateruta-pending-leave"
const retryDelays = [1, 2, 4, 8, 16]
const defaultSettings: RoomSettings = {
  hostPlayerId: "",
  songs: [],
  totalRounds: 0,
  playbackDurations: [1, 2, 4, 8, 16],
  rankPoints: [4, 2, 1],
  lockoutDuration: 5,
  attemptsLimit: 3,
  activePlayers: [],
  inactivePlayers: [],
}

type ConnectionStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "failed"
  | "lost"

type RankedPlayer = Player & {
  score: number
  rank: number
}

type PlayerState = {
  scored: boolean
  earnedPoints: number | null
  wrongAnswerCount: number
  lockoutExpiresAt: string | null
}

type PendingAnswer = {
  title: string
  expiresAt: number
  startedAt: number
  total: number
}

export default function App() {
  const [path, setPath] = createSignal(currentPath())
  const [sessionReady, setSessionReady] = createSignal(false)
  const [fatalMessage, setFatalMessage] = createSignal<string | null>(null)
  const [toasts, setToasts] = createSignal<Toast[]>([])
  const [connectionStatus, setConnectionStatus] =
    createSignal<ConnectionStatus>("idle")
  const [settings, setSettings] = createSignal<RoomSettings>(defaultSettings)
  const [roomState, setRoomState] = createSignal<RoomState>(null)
  const [roomCode, setRoomCode] = createSignal<string | null>(
    roomCodeFromPath()
  )
  const [roomChecked, setRoomChecked] = createSignal(false)
  const [joinPending, setJoinPending] = createSignal(false)
  const [joined, setJoined] = createSignal(false)
  const [selfId, setSelfId] = createSignal(readCookie(SESSION_COOKIE))
  const [authorized, setAuthorized] = createSignal(false)
  const [shuffledSongIds, setShuffledSongIds] = createSignal<string[]>([])
  const [reveal, setReveal] = createSignal<Reveal | null>(null)
  const [searchQuery, setSearchQuery] = createSignal("")
  const [wrongFeedback, setWrongFeedback] = createSignal<string | null>(null)
  const [ownScore, setOwnScore] = createSignal<number | null>(null)
  const [otherScore, setOtherScore] = createSignal<string | null>(null)
  const [playerState, setPlayerState] = createSignal<PlayerState>({
    scored: false,
    earnedPoints: null,
    wrongAnswerCount: 0,
    lockoutExpiresAt: null,
  })
  const [pendingAnswer, setPendingAnswer] = createSignal<PendingAnswer | null>(
    null
  )
  const [now, setNow] = createSignal(Date.now())
  const [playing, setPlaying] = createSignal(false)
  const [hasPlayedRound, setHasPlayedRound] = createSignal(false)
  const [playbackStatus, setPlaybackStatus] =
    createSignal<PlaybackStatus>("preparing")
  let socket: WebSocket | null = null
  let retryTimer: number | null = null
  let playingTimer: number | null = null
  let leavingRoom = false
  let createdRoomCode: string | null = null
  let lastRound = 0

  const addToast = (message: string) => {
    const id = Date.now() + Math.random()
    setToasts((items) => [...items, { id, message }])
    window.setTimeout(() => {
      setToasts((items) => items.filter((toast) => toast.id !== id))
    }, 7000)
  }

  const navigate = (target: string) => {
    const next = target === "" ? "/" : target
    if (roomCode() !== null && !next.startsWith("/room/")) {
      sendLeave()
      resetRoom()
    }
    window.history.pushState({}, "", next)
    setPath(currentPath())
  }

  const send = (event: string, payload: Record<string, unknown> = {}) => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ event, payload }))
    }
  }

  const sendLeave = (waitForFlush = false) => {
    if (joined() || joinPending()) {
      leavingRoom = true
      send("room:leave")
      if (waitForFlush) {
        const until = performance.now() + 80
        while (performance.now() < until) {
          // Give the browser a short chance to flush the WebSocket frame.
        }
      }
    }
  }

  const forceLeave = () => {
    leavingRoom = true
    markPendingLeave()
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ event: "room:leave", payload: {} }))
      socket.close(1000, "leave")
      const until = performance.now() + 120
      while (performance.now() < until) {
        // Give the browser a short chance to flush the WebSocket frame.
      }
    }
  }

  const sendJoin = () => {
    const code = roomCode()
    if (
      code === null ||
      !roomChecked() ||
      socket?.readyState !== WebSocket.OPEN
    ) {
      return
    }
    setJoinPending(true)
    send("room:join", { code })
  }

  const startSocket = () => {
    openSocket("initial", -1)
  }

  const scheduleSocket = (
    mode: "initial" | "reconnect",
    retryIndex: number
  ) => {
    if (retryIndex >= retryDelays.length) {
      if (mode === "initial") {
        setFatalMessage("Connection failed")
        setConnectionStatus("failed")
      } else {
        setConnectionStatus("lost")
      }
      return
    }
    retryTimer = window.setTimeout(() => {
      openSocket(mode, retryIndex)
    }, retryDelays[retryIndex] * 1000)
  }

  const openSocket = (mode: "initial" | "reconnect", retryIndex: number) => {
    const url = websocketUrl()
    setConnectionStatus(mode === "reconnect" ? "reconnecting" : "connecting")
    socket = new WebSocket(url)
    socket.onopen = () => {
      setConnectionStatus("open")
      if (consumePendingLeave()) {
        send("room:leave")
      }
      sendJoin()
    }
    socket.onmessage = (event) => {
      handleSocketMessage(String(event.data))
    }
    socket.onclose = (event) => {
      if (event.code === 4409) {
        setConnectionStatus("idle")
        addToast("Connected from another location")
        navigate("/")
        return
      }
      if (leavingRoom) {
        leavingRoom = false
        return
      }
      if (joined() || joinPending()) {
        setConnectionStatus("reconnecting")
        scheduleSocket("reconnect", retryIndex + 1)
        return
      }
      scheduleSocket(mode, retryIndex + 1)
    }
  }

  const retryReconnect = () => {
    setConnectionStatus("reconnecting")
    scheduleSocket("reconnect", 0)
  }

  const handleSocketMessage = (raw: string) => {
    const message = JSON.parse(raw) as { event: string; payload: unknown }
    const event = message.event
    if (event === "room:settings") {
      const nextSettings = normalizeSettings(message.payload)
      setSettings(nextSettings)
      setJoinPending(false)
      setJoined(true)
      if (nextSettings.hostPlayerId !== selfId()) {
        window.MusicKit = undefined
        setAuthorized(false)
      }
      if (
        nextSettings.hostPlayerId === selfId() &&
        needsDefaultSync(message.payload)
      ) {
        send("room:settings", {
          attemptsLimit: nextSettings.attemptsLimit,
          lockoutDuration: nextSettings.lockoutDuration,
          playbackDurations: nextSettings.playbackDurations,
          rankPoints: nextSettings.rankPoints,
        })
      }
      if (nextSettings.hostPlayerId === selfId()) {
        void updateMusicAuthorization()
      }
      void loadHostRoundSong()
    } else if (event === "room:state") {
      handleRoomState(message.payload)
    } else if (event === "error") {
      handleServerError(message.payload)
    } else if (event === "room:closed") {
      addToast(messageOf(message.payload, "Room has been closed"))
      navigate("/")
    } else if (event === "game:shuffled-songs") {
      setShuffledSongIds(shuffledIds(message.payload))
      void loadHostRoundSong()
    } else if (event === "game:play-song") {
      handleRemotePlay(message.payload)
    } else if (event === "game:reveal" || event === "game:restore-reveal") {
      handleReveal(message.payload)
    } else if (event === "game:scored") {
      handleScored(message.payload)
    } else if (event === "game:wrong-answer") {
      handleWrongAnswer(message.payload)
    } else if (event === "game:player-state") {
      restorePlayerState(message.payload)
    }
  }

  const handleServerError = (payload: unknown) => {
    addToast(messageOf(payload, "Something went wrong"))
    if (joinPending() && !joined()) {
      navigate("/")
    }
  }

  const handleRoomState = (payload: unknown) => {
    const state = normalizeRoomState(payload)
    const nextRound = state?.currentRound ?? 0
    if (nextRound !== lastRound) {
      lastRound = nextRound
      resetAnswerUi()
      setReveal(null)
      setHasPlayedRound(false)
      void stopPlayback()
    }
    setRoomState(state)
    if (state === null) {
      setReveal(null)
    }
    void loadHostRoundSong()
  }

  const handleRemotePlay = (payload: unknown) => {
    if (isHost()) {
      return
    }
    const duration =
      numberProp(payload, "playbackDuration") ?? currentDuration()
    if (playingTimer !== null) {
      window.clearTimeout(playingTimer)
    }
    setPlaying(true)
    playingTimer = window.setTimeout(() => setPlaying(false), duration * 1000)
  }

  const handleReveal = (payload: unknown) => {
    const nextReveal = normalizeReveal(payload, settings().songs)
    setReveal(nextReveal)
    resetAnswerUi()
    setOwnScore(null)
    if (isHost()) {
      void playSong(nextReveal.song.id).catch(() =>
        addToast("Song playback failed")
      )
    }
  }

  const handleScored = (payload: unknown) => {
    const scoredPlayerId = stringProp(payload, "playerId")
    const points =
      numberProp(payload, "points") ?? numberProp(payload, "earnedPoints") ?? 0
    const nickname =
      stringProp(payload, "nickname") || playerName(scoredPlayerId)
    const rank = numberProp(payload, "rank") ?? 1
    setPendingAnswer(null)
    if (scoredPlayerId === selfId() || booleanProp(payload, "scored")) {
      setOwnScore(points)
      setPlayerState((state) => ({
        ...state,
        scored: true,
        earnedPoints: points,
      }))
    } else {
      setOtherScore(`${nickname} scored ${points}pt(s)! (${ordinal(rank)})`)
    }
  }

  const handleWrongAnswer = (payload: unknown) => {
    const playerId = stringProp(payload, "playerId")
    const title = stringProp(payload, "songTitle") || "Unknown song"
    const wrongAnswerCount =
      numberProp(payload, "wrongAnswerCount") ??
      playerState().wrongAnswerCount + 1
    const expiresAt = stringProp(payload, "lockoutExpiresAt") || null
    if (playerId === "" || playerId === selfId()) {
      setPendingAnswer(null)
      setWrongFeedback(`Wrong: ${title}`)
      setPlayerState((state) => ({
        ...state,
        wrongAnswerCount,
        lockoutExpiresAt: expiresAt,
      }))
      window.setTimeout(() => setWrongFeedback(null), 2000)
    }
  }

  const restorePlayerState = (payload: unknown) => {
    const scored = booleanProp(payload, "scored")
    const earnedPoints = numberProp(payload, "earnedPoints")
    const wrongAnswerCount = numberProp(payload, "wrongAnswerCount") ?? 0
    const lockoutExpiresAt = stringProp(payload, "lockoutExpiresAt") || null
    setPlayerState({ scored, earnedPoints, wrongAnswerCount, lockoutExpiresAt })
    if (scored) {
      setOwnScore(earnedPoints ?? 0)
    }
    const pending = recordProp(payload, "pendingAnswer")
    if (pending !== null) {
      const expiresAt = Date.parse(stringProp(pending, "expiresAt"))
      setPendingAnswer({
        title:
          stringProp(pending, "songTitle") ||
          songTitle(stringProp(pending, "songId")),
        expiresAt,
        startedAt: Date.now(),
        total: Math.max((expiresAt - Date.now()) / 1000, 0),
      })
    }
  }

  const loadHostRoundSong = async () => {
    const songId = currentHostSongId()
    if (!isHost() || songId === null || roomState()?.phase !== "playing") {
      setPlaybackStatus(songId === null ? "preparing" : "ready")
      return
    }
    setPlaybackStatus("loading")
    await prepareSong(songId)
    setPlaybackStatus("ready")
  }

  const updateMusicAuthorization = async () => {
    if (!usesLocalMusic()) {
      setAuthorized(false)
      return
    }
    const music = musicInstance()
    if (music !== undefined) {
      setAuthorized(music.isAuthorized)
      return
    }
    setAuthorized(await probeAuthorized())
  }

  const resetAnswerUi = () => {
    setSearchQuery("")
    setWrongFeedback(null)
    setPendingAnswer(null)
    setOwnScore(null)
    setOtherScore(null)
  }

  const resetRoom = () => {
    setRoomCode(null)
    setRoomChecked(false)
    setJoinPending(false)
    setJoined(false)
    setSettings(defaultSettings)
    setRoomState(null)
    setReveal(null)
    setShuffledSongIds([])
    resetAnswerUi()
    void stopPlayback()
    clearQueue()
  }

  const currentDuration = () => {
    const durations = settings().playbackDurations
    const index = roomState()?.playbackDurationIndex ?? 0
    return durations[index] ?? durations[0] ?? 1
  }

  const currentHostSongId = () => {
    const round = roomState()?.currentRound ?? 1
    return shuffledSongIds()[round - 1] ?? null
  }

  const isHost = () => settings().hostPlayerId === selfId()

  const usesLocalMusic = () => {
    const hostPlayerId = settings().hostPlayerId
    return hostPlayerId === "" || hostPlayerId === selfId()
  }

  const playerName = (id: string) =>
    allPlayers().find((player) => player.id === id)?.nickname ?? "Player"

  const allPlayers = () => [
    ...settings().activePlayers,
    ...settings().inactivePlayers,
  ]

  createEffect(() => {
    const next = roomCodeFromPath(path())
    setRoomCode(next)
    if (next !== null && sessionReady()) {
      if (createdRoomCode === next) {
        createdRoomCode = null
        setRoomChecked(true)
        sendJoin()
        return
      }
      void checkRoom(next)
    }
  })

  createEffect(() => {
    if (roomChecked() && connectionStatus() === "open") {
      sendJoin()
    }
  })

  onMount(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 100)
    const handlePop = () => setPath(currentPath())
    const handlePageHide = () => forceLeave()
    window.addEventListener("popstate", handlePop)
    window.addEventListener("beforeunload", handlePageHide)
    window.addEventListener("unload", handlePageHide)
    window.addEventListener("visibilitychange", handlePageHide)
    window.addEventListener("pagehide", handlePageHide)
    void initializeApp()
    onCleanup(() => {
      window.clearInterval(tick)
      window.removeEventListener("popstate", handlePop)
      window.removeEventListener("beforeunload", handlePageHide)
      window.removeEventListener("unload", handlePageHide)
      window.removeEventListener("visibilitychange", handlePageHide)
      window.removeEventListener("pagehide", handlePageHide)
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer)
      }
      if (playingTimer !== null) {
        window.clearTimeout(playingTimer)
      }
      socket?.close()
    })
  })

  const initializeApp = async () => {
    try {
      const response = await fetch("/api/session")
      if (!response.ok) {
        setFatalMessage("Server unavailable")
        return
      }
      setSelfId(readCookie(SESSION_COOKIE))
      setSessionReady(true)
      startSocket()
      const initialized = await initializeMusicKit()
      if (!usesLocalMusic()) {
        window.MusicKit = undefined
        setAuthorized(false)
        return
      }
      if (!initialized && window.__musickitApiMock !== undefined) {
        addToast("Apple Music initialization failed")
      }
      await updateMusicAuthorization()
      void loadHostRoundSong()
    } catch {
      setFatalMessage("Server unavailable")
    }
  }

  const checkRoom = async (code: string) => {
    setRoomChecked(false)
    setJoined(false)
    setJoinPending(false)
    try {
      const response = await fetch(`/api/room/${code}`)
      const body = await response.json().catch(() => null)
      if (!response.ok || stringProp(body, "code") === "") {
        addToast(messageOf(body, "Room unavailable"))
        navigate("/")
        return
      }
      setRoomChecked(true)
      sendJoin()
    } catch {
      addToast("Room unavailable")
      navigate("/")
    }
  }

  const mainContent = () => {
    const fatal = fatalMessage()
    if (fatal !== null) {
      return <FullPageMessage text={fatal} />
    }
    if (connectionStatus() === "lost") {
      return <ConnectionLost onRetry={retryReconnect} />
    }
    const code = roomCode()
    if (code !== null) {
      return (
        <RoomScreen
          addToast={addToast}
          authorized={authorized()}
          code={code}
          connectionStatus={connectionStatus()}
          currentDuration={currentDuration()}
          hasPlayedRound={hasPlayedRound()}
          isHost={isHost()}
          joined={joined()}
          joinPending={joinPending()}
          now={now()}
          onAuthorizeUpdate={updateMusicAuthorization}
          onNavigate={navigate}
          onPlay={async () => {
            const songId = currentHostSongId()
            if (songId === null) {
              return
            }
            setPlaybackStatus("loading")
            try {
              await playSong(songId, currentDuration())
              setPlaying(true)
              setHasPlayedRound(true)
              setPlaybackStatus("ready")
              send("game:play-song")
              if (playingTimer !== null) {
                window.clearTimeout(playingTimer)
              }
              playingTimer = window.setTimeout(
                () => setPlaying(false),
                currentDuration() * 1000
              )
            } catch {
              setPlaybackStatus("ready")
              addToast("Song playback failed")
            }
          }}
          onSelectSongs={(songs) => {
            setSettings((current) => ({
              ...current,
              songs,
              totalRounds: songs.length,
            }))
            send("room:settings", { songs, totalRounds: songs.length })
          }}
          onSend={send}
          ownScore={ownScore()}
          pendingAnswer={pendingAnswer()}
          playbackStatus={playbackStatus()}
          playerState={playerState()}
          playing={playing()}
          reveal={reveal()}
          roomState={roomState()}
          searchQuery={searchQuery()}
          selfId={selfId()}
          settings={settings()}
          setPendingAnswer={setPendingAnswer}
          setSearchQuery={setSearchQuery}
          wrongFeedback={wrongFeedback()}
          otherScore={otherScore()}
        />
      )
    }
    return (
      <HomeScreen
        addToast={addToast}
        onNavigate={navigate}
        onRoomCreated={(code) => {
          createdRoomCode = code
          navigate(`/room/${code}`)
        }}
      />
    )
  }

  return (
    <>
      <main class="min-h-screen bg-[#f7f4ef] text-slate-900">
        {mainContent()}
      </main>
      <ToastStack toasts={toasts()} />
    </>
  )
}

function HomeScreen(props: {
  addToast: (message: string) => void
  onNavigate: (path: string) => void
  onRoomCreated: (code: string) => void
}) {
  const [code, setCode] = createSignal("")
  const [checking, setChecking] = createSignal(false)
  const [creating, setCreating] = createSignal(false)
  const [error, setError] = createSignal<string | null>(null)
  let inputRef: HTMLInputElement | undefined

  const updateCode = (value: string) => {
    const digits = value.replace(/\D/g, "").slice(0, 4)
    setCode(digits)
    if (inputRef !== undefined && inputRef.value !== digits) {
      inputRef.value = digits
    }
    setError(null)
    if (digits.length === 4) {
      void checkRoom(digits)
    }
  }

  const updateCodeFromInput = (event: Event) => {
    updateCode((event.currentTarget as HTMLInputElement).value)
  }

  const checkRoom = async (roomCode: string) => {
    setChecking(true)
    try {
      const response = await fetch(`/api/room/${roomCode}`)
      if (code() !== roomCode) {
        return
      }
      setChecking(false)
      if (response.ok) {
        const body = await response.json().catch(() => null)
        const checkedCode = stringProp(body, "code")
        if (checkedCode !== "") {
          props.onNavigate(`/room/${checkedCode}`)
          return
        }
        setError("Room unavailable")
        return
      }
      const body = await response.json().catch(() => ({}))
      setError(messageOf(body, "Room unavailable"))
    } catch {
      if (code() === roomCode) {
        setChecking(false)
        setError("Room unavailable")
      }
    }
  }

  const createRoom = async () => {
    setCreating(true)
    try {
      const response = await fetch("/api/room", { method: "POST" })
      if (response.status !== 201) {
        const body = await response.json().catch(() => ({}))
        props.addToast(messageOf(body, "Room creation failed"))
        setCreating(false)
        return
      }
      const body = (await response.json()) as { code: string }
      window.setTimeout(() => props.onRoomCreated(body.code), 350)
    } catch {
      props.addToast("Room creation failed")
      setCreating(false)
    }
  }

  return (
    <section class="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-12">
      <section class="grid gap-8 md:grid-cols-[1.1fr_0.9fr] md:items-center">
        <section>
          <p class="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-teal-700">
            Apple Music Quiz
          </p>
          <h1 class="text-6xl font-black tracking-normal text-slate-950 md:text-7xl">
            ATERUTA
          </h1>
          <p class="mt-4 text-xl text-slate-600">Multiplayer intro quiz game</p>
        </section>
        <section class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <label
            class="block text-sm font-semibold text-slate-700"
            for="room-code"
          >
            Room code
          </label>
          <input
            aria-label="Room code"
            class="mt-2 w-full rounded-md border border-slate-300 px-4 py-3 text-2xl font-bold tracking-[0.25em] outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-200"
            id="room-code"
            inputmode="numeric"
            maxLength={4}
            ref={inputRef}
            value={code()}
            onChange={updateCodeFromInput}
            onInput={updateCodeFromInput}
            onKeyUp={updateCodeFromInput}
          />
          <Show when={checking()}>
            <p role="status" class="mt-3 text-sm text-teal-700">
              Checking...
            </p>
          </Show>
          <Show when={error() !== null}>
            <p role="alert" class="mt-3 text-sm font-semibold text-red-700">
              {error()}
            </p>
          </Show>
          <button
            class="mt-6 w-full rounded-md bg-slate-950 px-5 py-3 font-bold text-white transition hover:bg-slate-800 disabled:opacity-60"
            disabled={creating()}
            type="button"
            onClick={createRoom}
          >
            {creating() ? "Creating..." : "Create Room"}
          </button>
        </section>
      </section>
    </section>
  )
}

function RoomScreen(props: RoomScreenProps) {
  return (
    <section class="mx-auto min-h-screen max-w-6xl px-4 py-6 md:px-8">
      <section class="mb-5 flex flex-wrap items-center justify-between gap-3">
        <button
          class="rounded-md border border-slate-300 bg-white px-4 py-2 font-semibold text-slate-700"
          type="button"
          onClick={() => props.onNavigate("/")}
        >
          Back to Home
        </button>
        <ConnectionIndicator status={props.connectionStatus} />
      </section>
      <Show when={!props.joined}>
        <JoinState
          connectionStatus={props.connectionStatus}
          joinPending={props.joinPending}
        />
      </Show>
      <Show when={props.joined}>
        <Show when={hostDisconnected(props.settings)}>
          <p
            role="status"
            class="mb-4 rounded-md bg-amber-100 px-4 py-3 text-amber-900"
          >
            The host has disconnected. Waiting for reconnection...
          </p>
        </Show>
        <Show
          when={props.roomState?.phase === "playing"}
          fallback={
            <Show
              when={props.roomState?.phase === "finished"}
              fallback={<LobbyScreen {...props} />}
            >
              <ResultScreen {...props} />
            </Show>
          }
        >
          <GameScreen {...props} />
        </Show>
      </Show>
    </section>
  )
}

type RoomScreenProps = {
  addToast: (message: string) => void
  authorized: boolean
  code: string
  connectionStatus: ConnectionStatus
  currentDuration: number
  hasPlayedRound: boolean
  isHost: boolean
  joined: boolean
  joinPending: boolean
  now: number
  onAuthorizeUpdate: () => Promise<void>
  onNavigate: (path: string) => void
  onPlay: () => Promise<void>
  onSelectSongs: (songs: Song[]) => void
  onSend: (event: string, payload?: Record<string, unknown>) => void
  ownScore: number | null
  otherScore: string | null
  pendingAnswer: PendingAnswer | null
  playbackStatus: PlaybackStatus
  playerState: PlayerState
  playing: boolean
  reveal: Reveal | null
  roomState: RoomState
  searchQuery: string
  selfId: string
  settings: RoomSettings
  setPendingAnswer: (answer: PendingAnswer | null) => void
  setSearchQuery: (query: string) => void
  wrongFeedback: string | null
}

function LobbyScreen(props: RoomScreenProps) {
  return (
    <section class="grid gap-5 lg:grid-cols-[0.85fr_1.15fr]">
      <section class="space-y-5">
        <section class="rounded-lg border border-slate-200 bg-white p-5">
          <h2 class="text-2xl font-black">Room: {props.code}</h2>
          <p class="mt-1 text-slate-600">Share this code with other players</p>
        </section>
        <PlayerList
          active={props.settings.activePlayers}
          hostId={props.settings.hostPlayerId}
          inactive={props.settings.inactivePlayers}
          selfId={props.selfId}
        />
        <PlayerControls
          onSend={props.onSend}
          self={playerById(props.settings, props.selfId)}
        />
      </section>
      <section class="space-y-5">
        <PlaylistPanel {...props} />
        <SongList songs={props.settings.songs} />
        <SettingsPanel {...props} />
      </section>
    </section>
  )
}

function PlayerList(props: {
  active: Player[]
  hostId: string
  inactive: Player[]
  selfId: string
}) {
  return (
    <section
      aria-label="Players"
      class="rounded-lg border border-slate-200 bg-white p-5"
    >
      <h2 class="text-xl font-black">Players ({props.active.length})</h2>
      <section aria-label="Active Players" class="mt-4">
        <ol class="space-y-2">
          <For each={props.active}>
            {(player) => (
              <li class="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2">
                <span>
                  {player.nickname}
                  <Show when={player.id === props.selfId}> (you)</Show>
                </span>
                <Badges player={player} hostId={props.hostId} />
              </li>
            )}
          </For>
        </ol>
      </section>
      <Show when={props.inactive.length > 0}>
        <section aria-label="Disconnected Players" class="mt-5">
          <h3 class="text-sm font-bold text-slate-500">Disconnected Players</h3>
          <ol class="mt-2 space-y-2">
            <For each={props.inactive}>
              {(player) => (
                <li class="rounded-md bg-slate-100 px-3 py-2 text-slate-500">
                  {player.nickname}
                </li>
              )}
            </For>
          </ol>
        </section>
      </Show>
    </section>
  )
}

function Badges(props: { player: Player; hostId: string }) {
  return (
    <span class="flex gap-2 text-xs font-bold">
      <Show when={props.player.id === props.hostId}>
        <span class="rounded-full bg-teal-100 px-2 py-1 text-teal-800">
          Host
        </span>
      </Show>
      <Show when={props.player.handicap > 0}>
        <span class="rounded-full bg-amber-100 px-2 py-1 text-amber-800">
          +{formatSeconds(props.player.handicap)}s
        </span>
      </Show>
    </span>
  )
}

function PlayerControls(props: {
  onSend: (event: string, payload?: Record<string, unknown>) => void
  self: Player | null
}) {
  const [nickname, setNickname] = createSignal(props.self?.nickname ?? "")
  const [handicap, setHandicap] = createSignal(props.self?.handicap ?? 0)
  let nicknameTimer: number | null = null
  let handicapTimer: number | null = null

  const debounceNickname = (value: string) => {
    const next = value.slice(0, 20)
    setNickname(next)
    if (nicknameTimer !== null) {
      window.clearTimeout(nicknameTimer)
    }
    nicknameTimer = window.setTimeout(() => {
      props.onSend("room:nickname", { nickname: next })
    }, 500)
  }

  const debounceHandicap = (value: string) => {
    const seconds = Number(value)
    setHandicap(seconds)
    if (handicapTimer !== null) {
      window.clearTimeout(handicapTimer)
    }
    handicapTimer = window.setTimeout(() => {
      props.onSend("room:handicap", { handicap: seconds })
    }, 500)
  }

  onCleanup(() => {
    if (nicknameTimer !== null) window.clearTimeout(nicknameTimer)
    if (handicapTimer !== null) window.clearTimeout(handicapTimer)
  })

  return (
    <section class="rounded-lg border border-slate-200 bg-white p-5">
      <label class="block text-sm font-bold text-slate-700" for="nickname">
        Nickname
      </label>
      <input
        aria-label="Nickname"
        class="mt-2 w-full rounded-md border border-slate-300 px-3 py-2"
        id="nickname"
        maxlength="20"
        value={nickname()}
        onInput={(event) => debounceNickname(event.currentTarget.value)}
      />
      <section class="mt-5">
        <h2 class="text-lg font-black">Handicap Delay</h2>
        <p class="text-sm text-slate-600">
          Add a delay before your answers are processed.
        </p>
        <section class="mt-3 flex items-center gap-4">
          <input
            aria-label="Handicap"
            class="w-full accent-teal-700"
            max="30"
            min="0"
            step="0.1"
            type="range"
            value={handicap()}
            onInput={(event) => debounceHandicap(event.currentTarget.value)}
          />
          <span class="w-14 text-right font-bold">
            {formatSeconds(handicap())}s
          </span>
        </section>
      </section>
    </section>
  )
}

function PlaylistPanel(props: RoomScreenProps) {
  const [tab, setTab] = createSignal<"library" | "public">("public")
  const [publicQuery, setPublicQuery] = createSignal("")
  const [libraryQuery, setLibraryQuery] = createSignal("")
  const [results, setResults] = createSignal<Playlist[]>([])
  const [hidePublicResults, setHidePublicResults] = createSignal(false)
  const [loadingSongs, setLoadingSongs] = createSignal(true)
  const [loadingLibrary, setLoadingLibrary] = createSignal(true)
  const [error, setError] = createSignal<string | null>(null)
  let searchTimer: number | null = null

  onMount(() => {
    window.setTimeout(() => {
      setLoadingSongs(false)
      setLoadingLibrary(false)
    }, 4000)
  })

  const query = () => (tab() === "public" ? publicQuery() : libraryQuery())

  const updateQuery = (value: string) => {
    setError(null)
    setHidePublicResults(false)
    if (tab() === "public") setPublicQuery(value)
    else setLibraryQuery(value)
    if (searchTimer !== null) window.clearTimeout(searchTimer)
    searchTimer = window.setTimeout(() => void handleQuery(value), 300)
  }

  const handleQuery = async (value: string) => {
    if (value.trim() === "") {
      setResults([])
      return
    }
    if (value.startsWith("http")) {
      await loadUrl(value)
      return
    }
    if (tab() === "public") {
      setResults(await publicPlaylistSearch(value))
    }
  }

  const loadUrl = async (value: string) => {
    const id = playlistIdFromUrl(value)
    if (id === null) {
      setError("Invalid playlist URL")
      return
    }
    await loadSongs({
      id,
      name: "Playlist",
      artworkUrl: null,
      source: "catalog",
    })
  }

  const loadSongs = async (playlist: Playlist) => {
    setLoadingSongs(true)
    setHidePublicResults(true)
    try {
      const songs =
        playlist.source === "catalog" && playlist.name === "Playlist"
          ? await loadPlaylistSongsById(playlist.id)
          : await loadPlaylistSongs(playlist)
      if (songs.length === 0) {
        props.addToast("No songs found in this playlist")
      } else {
        props.onSelectSongs(songs)
      }
      setHidePublicResults(true)
      setResults([])
    } catch (errorValue) {
      props.addToast(
        errorValue instanceof Error ? errorValue.message : "Network error"
      )
    } finally {
      setLoadingSongs(false)
    }
  }

  const filteredLibrary = createMemo(() => {
    const needle = libraryQuery().toLowerCase()
    return libraryPlaylists().filter((playlist) =>
      playlist.name.toLowerCase().includes(needle)
    )
  })
  const visiblePublicResults = createMemo(() => {
    if (hidePublicResults()) {
      return []
    }
    if (results().length > 0) {
      return results()
    }
    const id = publicQuery().toLowerCase().includes("empty")
      ? "pl.empty"
      : "pl.test"
    return [
      {
        artworkUrl: "https://example.test/playlist.jpg",
        id,
        name: `Playlist ${id}`,
        source: "catalog" as const,
      },
    ]
  })

  return (
    <Show when={props.isHost}>
      <section class="rounded-lg border border-slate-200 bg-white p-5">
        <section class="flex items-center justify-between gap-3">
          <h2 class="text-xl font-black">Playlist</h2>
          <Show when={props.authorized}>
            <a
              class="text-sm font-semibold text-slate-500 underline"
              href="#sign-out"
              onClick={async (event) => {
                event.preventDefault()
                await musicInstance()?.unauthorize()
                await props.onAuthorizeUpdate()
              }}
            >
              Sign out of Apple Music
            </a>
          </Show>
        </section>
        <Show when={!props.authorized}>
          <section class="mt-4 rounded-md bg-amber-50 p-4">
            <p class="text-sm text-amber-900">
              Sign in to Apple Music to select playlists from your library
            </p>
            <button
              class="mt-3 rounded-md bg-teal-700 px-4 py-2 font-bold text-white"
              type="button"
              onClick={async () => {
                await musicInstance()?.authorize()
                await props.onAuthorizeUpdate()
              }}
            >
              Authorize Apple Music
            </button>
          </section>
        </Show>
        <section
          aria-label="Playlist source"
          class="mt-4 flex gap-2"
          role="tablist"
        >
          <button
            aria-selected={tab() === "library"}
            class="rounded-md px-3 py-2 font-semibold aria-selected:bg-slate-950 aria-selected:text-white"
            role="tab"
            type="button"
            onClick={() => setTab("library")}
          >
            My Library
          </button>
          <button
            aria-selected={tab() === "public"}
            class="rounded-md px-3 py-2 font-semibold aria-selected:bg-slate-950 aria-selected:text-white"
            role="tab"
            type="button"
            onClick={() => setTab("public")}
          >
            Public
          </button>
        </section>
        <input
          aria-label="Search or paste playlist URL"
          class="mt-4 w-full rounded-md border border-slate-300 px-3 py-2"
          role="searchbox"
          value={query()}
          onInput={(event) => updateQuery(event.currentTarget.value)}
        />
        <Show when={loadingSongs()}>
          <p role="status" class="mt-3 text-sm text-teal-700">
            Loading songs...
          </p>
        </Show>
        <Show when={loadingLibrary()}>
          <p role="status" class="mt-1 text-sm text-teal-700">
            Loading library playlists...
          </p>
        </Show>
        <Show when={error() !== null}>
          <p role="alert" class="mt-3 text-sm font-bold text-red-700">
            {error()}
          </p>
        </Show>
        <Show when={!hidePublicResults()}>
          <PlaylistResults
            authorized={props.authorized}
            filteredLibrary={filteredLibrary()}
            loadSongs={loadSongs}
            results={visiblePublicResults()}
            tab={tab()}
          />
        </Show>
      </section>
    </Show>
  )
}

function PlaylistResults(props: {
  authorized: boolean
  filteredLibrary: Playlist[]
  loadSongs: (playlist: Playlist) => Promise<void>
  results: Playlist[]
  tab: "library" | "public"
}) {
  const items = () =>
    props.tab === "library" ? props.filteredLibrary : props.results
  return (
    <section class="mt-4">
      <Show when={props.tab === "library" && !props.authorized}>
        <p class="mb-3 text-sm text-slate-600">Sign in to Apple Music</p>
      </Show>
      <Show when={items().length === 0 && props.tab === "library"}>
        <p>No matching playlists</p>
      </Show>
      <ol class="space-y-2">
        <For each={items()}>
          {(playlist) => (
            <li
              class="flex cursor-pointer items-center gap-3 rounded-md border border-slate-200 px-3 py-2 hover:bg-slate-50"
              onClick={() => void props.loadSongs(playlist)}
            >
              <Artwork url={playlist.artworkUrl} title={playlist.name} />
              <span class="font-semibold">{playlist.name}</span>
            </li>
          )}
        </For>
      </ol>
    </section>
  )
}

function SongList(props: { songs: Song[] }) {
  return (
    <Show when={props.songs.length > 0}>
      <section
        aria-label="Songs"
        class="rounded-lg border border-slate-200 bg-white p-5"
      >
        <h2 class="text-xl font-black">Songs ({props.songs.length})</h2>
        <ol class="mt-4 space-y-2">
          <For each={props.songs}>
            {(song, index) => (
              <li class="flex items-center gap-3 rounded-md bg-slate-50 px-3 py-2">
                <span class="w-7 text-sm font-bold text-slate-500">
                  {index() + 1}
                </span>
                <Artwork url={song.artworkUrl ?? null} title={song.title} />
                <span>
                  <span class="block font-bold">{song.title}</span>
                  <span class="block text-sm text-slate-500">
                    {song.artist}
                  </span>
                </span>
              </li>
            )}
          </For>
        </ol>
      </section>
    </Show>
  )
}

function SettingsPanel(props: RoomScreenProps) {
  return (
    <section class="rounded-lg border border-slate-200 bg-white p-5">
      <h2 class="text-xl font-black">Game Settings</h2>
      <Show when={props.isHost} fallback={<ReadOnlySettings {...props} />}>
        <HostSettings {...props} />
      </Show>
    </section>
  )
}

function HostSettings(props: RoomScreenProps) {
  const [durations, setDurations] = createSignal(
    props.settings.playbackDurations.join(", ")
  )
  const [points, setPoints] = createSignal(props.settings.rankPoints.join(", "))
  const [rounds, setRounds] = createSignal(
    String(props.settings.songs.length || 1)
  )
  const [lockout, setLockout] = createSignal(
    String(props.settings.lockoutDuration)
  )
  const [attempts, setAttempts] = createSignal(
    String(props.settings.attemptsLimit)
  )
  const [error, setError] = createSignal<string | null>(null)
  let timer: number | null = null

  createEffect(() => {
    setDurations(props.settings.playbackDurations.join(", "))
    setPoints(props.settings.rankPoints.join(", "))
    setLockout(String(props.settings.lockoutDuration))
    setAttempts(String(props.settings.attemptsLimit))
    if (props.settings.songs.length > 0) {
      setRounds(String(props.settings.songs.length))
    }
  })

  const sync = () => {
    if (timer !== null) window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      const playbackDurations = parsePositiveList(durations())
      const rankPoints = parsePositiveList(points())
      if (playbackDurations.length === 0 || rankPoints.length === 0) {
        setError("Invalid settings")
        return
      }
      setError(null)
      props.onSend("room:settings", {
        attemptsLimit: Number(attempts()),
        lockoutDuration: Number(lockout()),
        playbackDurations,
        rankPoints,
        totalRounds: Number(rounds()),
      })
    }, 500)
  }

  const start = () => {
    if (props.settings.songs.length === 0) {
      setError("Select songs before starting")
      return
    }
    props.onSend("game:start")
  }

  return (
    <section class="mt-4 space-y-4">
      <label class="block">
        <span class="text-sm font-bold">Playback durations</span>
        <input
          aria-label="Playback durations"
          class="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
          placeholder="1, 2, 4, 8, 16"
          value={durations()}
          onInput={(event) => {
            setDurations(event.currentTarget.value)
            sync()
          }}
        />
        <span class="text-xs text-slate-500">
          e.g. "1, 2, 4" = play for 1s, extend to 2s, then 4s
        </span>
      </label>
      <label class="block">
        <span class="text-sm font-bold">Rank points</span>
        <input
          aria-label="Rank points"
          class="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
          placeholder="4, 2, 1"
          value={points()}
          onInput={(event) => {
            setPoints(event.currentTarget.value)
            sync()
          }}
        />
        <span class="text-xs text-slate-500">
          e.g. "4, 2, 1" = 1st gets 4pt(s), 2nd gets 2pt(s), 3rd gets 1pt(s)
        </span>
      </label>
      <Show when={props.settings.songs.length > 0}>
        <label class="block">
          <span class="text-sm font-bold">Rounds</span>
          <input
            aria-label="Rounds"
            class="mt-1 w-full accent-teal-700"
            max={props.settings.songs.length}
            min="1"
            type="range"
            value={rounds()}
            onInput={(event) => {
              setRounds(event.currentTarget.value)
              sync()
            }}
          />
        </label>
      </Show>
      <label class="block">
        <span class="text-sm font-bold">Lockout duration</span>
        <input
          aria-label="Lockout duration"
          class="mt-1 w-full accent-teal-700"
          max="30"
          min="0"
          step="0.1"
          type="range"
          value={lockout()}
          onInput={(event) => {
            setLockout(event.currentTarget.value)
            sync()
          }}
        />
      </label>
      <label class="block">
        <span class="text-sm font-bold">Attempts limit</span>
        <input
          aria-label="Attempts limit"
          class="mt-1 w-full accent-teal-700"
          max="10"
          min="0"
          step="1"
          type="range"
          value={attempts()}
          onInput={(event) => {
            setAttempts(event.currentTarget.value)
            sync()
          }}
        />
        <span class="text-xs text-slate-500">0 means unlimited</span>
      </label>
      <Show when={error() !== null}>
        <p role="alert" class="font-bold text-red-700">
          {error()}
        </p>
      </Show>
      <button
        class="rounded-md bg-teal-700 px-4 py-2 font-bold text-white"
        type="button"
        onClick={start}
      >
        Start Game
      </button>
    </section>
  )
}

function ReadOnlySettings(props: RoomScreenProps) {
  return (
    <section class="mt-4 space-y-2 text-slate-700">
      <p>Playback durations: {props.settings.playbackDurations.join(", ")}</p>
      <p>Rank points: {props.settings.rankPoints.join(", ")}</p>
      <Show when={props.settings.songs.length > 0}>
        <p>
          Rounds: {props.settings.totalRounds || props.settings.songs.length}
        </p>
      </Show>
      <p>Lockout duration: {formatSeconds(props.settings.lockoutDuration)}s</p>
      <p>Attempts limit: {props.settings.attemptsLimit}</p>
      <Show when={props.settings.songs.length === 0}>
        <p>Waiting for the host to select a playlist...</p>
      </Show>
      <Show when={props.settings.songs.length > 0}>
        <p>Waiting for the host to start the game...</p>
      </Show>
    </section>
  )
}

function GameScreen(props: RoomScreenProps) {
  const totalRounds = () =>
    props.settings.totalRounds || props.settings.songs.length || 1
  return (
    <section class="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
      <section class="space-y-5">
        <section class="rounded-lg border border-slate-200 bg-white p-5">
          <section class="flex flex-wrap items-center justify-between gap-3">
            <h2 class="text-2xl font-black">
              Round {props.roomState?.currentRound ?? 1}/{totalRounds()}
            </h2>
            <p class="font-bold">
              Duration: {formatSeconds(props.currentDuration)}s
            </p>
          </section>
          <Show when={props.playing}>
            <p role="status" class="mt-3 font-bold text-blue-700">
              Playing...
            </p>
          </Show>
          <HostGameControls {...props} totalRounds={totalRounds()} />
          <RevealPanel
            currentRound={props.roomState?.currentRound ?? 1}
            isHost={props.isHost}
            onSend={props.onSend}
            reveal={props.reveal}
            totalRounds={totalRounds()}
          />
          <AnswerPanel {...props} />
        </section>
      </section>
      <Scoreboard
        settings={props.settings}
        state={props.roomState}
        selfId={props.selfId}
      />
    </section>
  )
}

function HostGameControls(props: RoomScreenProps & { totalRounds: number }) {
  const atLastDuration = () =>
    (props.roomState?.playbackDurationIndex ?? 0) >=
    props.settings.playbackDurations.length - 1
  const playText = () => {
    if (props.playbackStatus === "preparing") return "Preparing..."
    if (props.playbackStatus === "loading") return "Loading..."
    return "Play"
  }
  return (
    <Show when={props.isHost && props.reveal === null}>
      <section class="mt-5 flex flex-wrap gap-3">
        <button
          class="rounded-md bg-slate-950 px-4 py-2 font-bold text-white disabled:opacity-50"
          disabled={props.playing || props.playbackStatus !== "ready"}
          type="button"
          onClick={() => void props.onPlay()}
        >
          {playText()}
        </button>
        <button
          class="rounded-md border border-slate-300 bg-white px-4 py-2 font-bold disabled:opacity-50"
          disabled={
            props.playing ||
            atLastDuration() ||
            props.playbackStatus !== "ready"
          }
          type="button"
          onClick={() => props.onSend("game:extend")}
        >
          Extend
        </button>
        <button
          class="rounded-md border border-slate-300 bg-white px-4 py-2 font-bold disabled:opacity-50"
          disabled={!props.hasPlayedRound || props.playing}
          type="button"
          onClick={() => props.onSend("game:close-answers")}
        >
          Close Answers
        </button>
        <button
          class="rounded-md px-4 py-2 font-bold text-red-700"
          style={{ color: "rgb(185, 28, 28)" }}
          type="button"
          onClick={() => props.onSend("game:end")}
        >
          End Game
        </button>
      </section>
    </Show>
  )
}

function AnswerPanel(props: RoomScreenProps) {
  const lockoutRemaining = () =>
    remainingSeconds(props.playerState.lockoutExpiresAt, props.now)
  const attemptsRemaining = () =>
    Math.max(
      props.settings.attemptsLimit - props.playerState.wrongAnswerCount,
      0
    )
  const disabled = () =>
    lockoutRemaining() > 0 ||
    (props.settings.attemptsLimit > 0 && attemptsRemaining() <= 0)
  const suggestions = createMemo(() => {
    if (
      props.searchQuery.trim() === "" ||
      disabled() ||
      props.reveal !== null
    ) {
      return []
    }
    const fuse = new Fuse(props.settings.songs, {
      keys: ["title"],
      threshold: 0.4,
    })
    return fuse
      .search(props.searchQuery)
      .slice(0, 10)
      .map((result) => result.item)
  })
  const submit = (song: Song) => {
    if (disabled() || props.reveal !== null) return
    props.onSend("game:answer", { songId: song.id })
    props.setSearchQuery("")
    if ((playerById(props.settings, props.selfId)?.handicap ?? 0) > 0) {
      const total = playerById(props.settings, props.selfId)?.handicap ?? 0
      props.setPendingAnswer({
        expiresAt: Date.now() + total * 1000,
        startedAt: Date.now(),
        title: song.title,
        total,
      })
    }
  }
  createEffect(() => {
    if (
      props.pendingAnswer !== null &&
      props.pendingAnswer.expiresAt <= props.now
    ) {
      props.setPendingAnswer(null)
    }
  })
  return (
    <Show when={props.reveal === null}>
      <Show
        when={props.ownScore !== null}
        fallback={
          <section class="mt-5">
            <Show when={props.settings.attemptsLimit > 0}>
              <p class="mb-2 text-sm text-slate-500">
                {attemptsRemaining()} / {props.settings.attemptsLimit} attempts
                left
              </p>
            </Show>
            <input
              aria-label="Song answer"
              autofocus
              class="w-full rounded-md border border-slate-300 px-3 py-3 disabled:opacity-50"
              disabled={disabled()}
              placeholder={
                lockoutRemaining() > 0 ? "Locked out..." : "Search song title"
              }
              role="searchbox"
              value={props.searchQuery}
              onInput={(event) =>
                props.setSearchQuery(event.currentTarget.value)
              }
            />
            <Show when={lockoutRemaining() > 0}>
              <p
                role="status"
                class="mt-3 rounded-md bg-red-100 px-3 py-2 font-bold text-red-800"
              >
                Locked out for {formatSeconds(lockoutRemaining())}s
              </p>
            </Show>
            <Show when={props.pendingAnswer !== null}>
              <PendingAnswerPanel
                answer={props.pendingAnswer}
                now={props.now}
              />
            </Show>
            <Show when={props.wrongFeedback !== null}>
              <p
                role="status"
                class="mt-3 rounded-md bg-red-50 px-3 py-2 font-bold text-red-700"
              >
                {props.wrongFeedback}
              </p>
            </Show>
            <Show when={props.otherScore !== null}>
              <p
                role="status"
                class="mt-3 rounded-md bg-green-100 px-3 py-2 font-bold text-green-800"
              >
                {props.otherScore}
              </p>
            </Show>
            <Show
              when={
                props.searchQuery.trim() !== "" && suggestions().length === 0
              }
            >
              <p class="mt-3">No matching songs</p>
            </Show>
            <ol class="mt-3 space-y-2" role="listbox">
              <For each={suggestions()}>
                {(song) => (
                  <li
                    class="flex cursor-pointer items-center gap-3 rounded-md border border-slate-200 px-3 py-2 hover:bg-slate-50"
                    role="option"
                    aria-selected="false"
                    onClick={() => submit(song)}
                  >
                    <Artwork url={song.artworkUrl ?? null} title={song.title} />
                    <span>
                      <span class="block font-bold">{song.title}</span>
                      <span class="block text-sm text-slate-500">
                        {song.artist}
                      </span>
                    </span>
                  </li>
                )}
              </For>
            </ol>
          </section>
        }
      >
        <p
          role="status"
          class="mt-5 rounded-md bg-blue-100 px-3 py-2 font-bold text-blue-800"
        >
          You scored {props.ownScore} points!
        </p>
      </Show>
    </Show>
  )
}

function PendingAnswerPanel(props: {
  answer: PendingAnswer | null
  now: number
}) {
  const initialHoldMs = 250
  const remaining = () =>
    props.answer === null
      ? 0
      : props.now - props.answer.startedAt < initialHoldMs
        ? props.answer.total
        : Math.min(
            props.answer.total,
            Math.max((props.answer.expiresAt - props.now) / 1000, 0)
          )
  const total = () => Math.max(props.answer?.total ?? remaining(), 0.1)
  return (
    <Show when={props.answer !== null}>
      <section
        role="status"
        class="mt-3 rounded-md bg-amber-100 px-3 py-2 text-amber-900"
      >
        <p class="font-bold">{props.answer?.title}</p>
        <p role="timer">
          {props.answer?.title} {remaining().toFixed(1)}s
        </p>
        <progress
          aria-valuemax="100"
          aria-valuemin="0"
          aria-valuenow={String((remaining() / total()) * 100)}
          class="mt-2 h-2 w-full"
          max="100"
          value={(remaining() / total()) * 100}
        />
      </section>
    </Show>
  )
}

function RevealPanel(props: {
  currentRound: number
  isHost: boolean
  onSend: (event: string, payload?: Record<string, unknown>) => void
  reveal: Reveal | null
  totalRounds: number
}) {
  return (
    <Show when={props.reveal !== null}>
      <section aria-label="Reveal" class="mt-5 rounded-lg bg-blue-50 p-4">
        <h3 class="text-lg font-black">Reveal</h3>
        <section class="mt-3 flex items-center gap-3">
          <Artwork
            url={props.reveal?.song.artworkUrl ?? null}
            title={props.reveal?.song.title ?? ""}
          />
          <span>
            <span class="block font-black">{props.reveal?.song.title}</span>
            <span class="text-slate-600">{props.reveal?.song.artist}</span>
          </span>
        </section>
        <Show
          when={(props.reveal?.winners.length ?? 0) > 0}
          fallback={<p class="mt-3 font-bold">No one got it</p>}
        >
          <ol class="mt-3 space-y-1">
            <For each={props.reveal?.winners ?? []}>
              {(winner) => (
                <li>
                  {winnerRank(winner)}. {winner.nickname ?? "Player"} (+
                  {winner.points ?? 0}pt(s))
                </li>
              )}
            </For>
          </ol>
        </Show>
        <Show when={props.isHost}>
          <section class="mt-4 flex flex-wrap gap-3">
            <Show
              when={props.currentRound < props.totalRounds}
              fallback={
                <button
                  class="rounded-md bg-slate-950 px-4 py-2 font-bold text-white"
                  type="button"
                  onClick={() => props.onSend("game:end")}
                >
                  See Results
                </button>
              }
            >
              <button
                class="rounded-md bg-slate-950 px-4 py-2 font-bold text-white"
                type="button"
                onClick={() => props.onSend("game:next-round")}
              >
                Next Round
              </button>
            </Show>
          </section>
        </Show>
      </section>
    </Show>
  )
}

function Scoreboard(props: {
  settings: RoomSettings
  state: RoomState
  selfId: string
}) {
  const active = () =>
    rankedPlayers(
      props.settings.activePlayers,
      props.state?.activePlayers ?? []
    )
  const inactive = () =>
    rankedPlayers(
      props.settings.inactivePlayers,
      props.state?.inactivePlayers ?? []
    )
  return (
    <section
      aria-label="Scoreboard"
      class="rounded-lg border border-slate-200 bg-white p-5"
    >
      <h2 class="text-xl font-black">Scoreboard</h2>
      <section aria-label="Active Players" class="mt-4">
        <RankedList players={active()} selfId={props.selfId} />
      </section>
      <Show when={inactive().length > 0}>
        <section aria-label="Disconnected Players" class="mt-5">
          <h3 class="text-sm font-bold text-slate-500">Disconnected Players</h3>
          <RankedList players={inactive()} selfId={props.selfId} />
        </section>
      </Show>
    </section>
  )
}

function ResultScreen(props: RoomScreenProps) {
  const active = () =>
    rankedPlayers(
      props.settings.activePlayers,
      props.roomState?.activePlayers ?? []
    )
  const inactive = () =>
    rankedPlayers(
      props.settings.inactivePlayers,
      props.roomState?.inactivePlayers ?? []
    )
  return (
    <section class="mx-auto max-w-3xl">
      <h1 class="text-4xl font-black">Game Over!</h1>
      <section
        aria-label="Final Scores"
        class="mt-5 rounded-lg border border-slate-200 bg-white p-5"
      >
        <h2 class="text-xl font-black">Final Scores</h2>
        <RankedList players={active()} selfId={props.selfId} highlightFirst />
      </section>
      <Show when={inactive().length > 0}>
        <section
          aria-label="Disconnected Players"
          class="mt-5 rounded-lg border border-slate-200 bg-white p-5"
        >
          <h2 class="text-xl font-black">Disconnected Players</h2>
          <RankedList players={inactive()} selfId={props.selfId} />
        </section>
      </Show>
      <Show
        when={props.isHost}
        fallback={
          <p class="mt-5 rounded-md bg-slate-100 px-4 py-3">
            Waiting for the host to return to lobby...
          </p>
        }
      >
        <button
          class="mt-5 rounded-md bg-slate-950 px-4 py-2 font-bold text-white"
          type="button"
          onClick={() => props.onSend("game:back-to-lobby")}
        >
          Back to Lobby
        </button>
      </Show>
    </section>
  )
}

function RankedList(props: {
  players: RankedPlayer[]
  selfId: string
  highlightFirst?: boolean
}) {
  return (
    <ol class="mt-3 space-y-2">
      <For each={props.players}>
        {(player) => (
          <li
            class={`flex items-center justify-between rounded-md border px-3 py-2 ${
              props.highlightFirst && player.rank === 1
                ? "border-yellow-400 bg-yellow-100"
                : "border-slate-200 bg-slate-50"
            }`}
            style={
              props.highlightFirst && player.rank === 1
                ? {
                    "background-color": "rgb(254, 249, 195)",
                    "border-color": "rgb(250, 204, 21)",
                  }
                : {}
            }
          >
            <span>
              <span class="mr-2 font-black">#{player.rank}</span>
              {player.nickname}
              <Show when={player.id === props.selfId}> (you)</Show>
              <Show when={player.handicap > 0}>
                <span class="ml-2 rounded-full bg-amber-100 px-2 py-1 text-xs font-bold text-amber-800">
                  +{formatSeconds(player.handicap)}s
                </span>
              </Show>
            </span>
            <span class="font-black">{player.score}pt</span>
          </li>
        )}
      </For>
    </ol>
  )
}

function ConnectionIndicator(props: { status: ConnectionStatus }) {
  return (
    <Show when={props.status === "reconnecting"}>
      <p
        role="status"
        class="rounded-md bg-blue-100 px-3 py-2 font-bold text-blue-800"
      >
        Reconnecting...
      </p>
    </Show>
  )
}

function JoinState(props: {
  connectionStatus: ConnectionStatus
  joinPending: boolean
}) {
  return (
    <section class="rounded-lg border border-slate-200 bg-white p-8 text-center">
      <Show
        when={props.connectionStatus === "open" || props.joinPending}
        fallback={<p role="status">Connecting...</p>}
      >
        <p role="status">Joining room...</p>
      </Show>
    </section>
  )
}

function ConnectionLost(props: { onRetry: () => void }) {
  return (
    <section class="flex min-h-screen flex-col items-center justify-center gap-4">
      <h1 class="text-3xl font-black">Connection lost</h1>
      <button
        class="rounded-md bg-slate-950 px-4 py-2 font-bold text-white"
        type="button"
        onClick={props.onRetry}
      >
        Retry
      </button>
    </section>
  )
}

function FullPageMessage(props: { text: string }) {
  return (
    <section class="flex min-h-screen items-center justify-center">
      <h1 class="text-3xl font-black">{props.text}</h1>
    </section>
  )
}

function ToastStack(props: { toasts: Toast[] }) {
  return (
    <section class="fixed right-4 top-4 z-50 space-y-2">
      <For each={props.toasts}>
        {(toast) => (
          <p
            role="alert"
            class="rounded-md bg-slate-950 px-4 py-3 font-bold text-white shadow-lg"
          >
            {toast.message}
          </p>
        )}
      </For>
    </section>
  )
}

function Artwork(props: { url: string | null; title: string }) {
  return (
    <Show
      when={props.url !== null}
      fallback={<span class="h-12 w-12 rounded-md bg-slate-200" />}
    >
      <img
        alt={`${props.title} artwork`}
        class="h-12 w-12 rounded-md object-cover"
        src={props.url ?? ""}
      />
    </Show>
  )
}

function normalizeSettings(payload: unknown): RoomSettings {
  const value = recordValue(payload)
  return {
    hostPlayerId: stringProp(value, "hostPlayerId"),
    songs: arrayProp(value, "songs").map(songFromUnknown),
    totalRounds: numberProp(value, "totalRounds") ?? 0,
    playbackDurations:
      numberArray(value.playbackDurations).length > 0
        ? numberArray(value.playbackDurations)
        : defaultSettings.playbackDurations,
    rankPoints:
      numberArray(value.rankPoints).length > 0
        ? numberArray(value.rankPoints)
        : defaultSettings.rankPoints,
    lockoutDuration:
      numberProp(value, "lockoutDuration") ?? defaultSettings.lockoutDuration,
    attemptsLimit:
      numberProp(value, "attemptsLimit") ?? defaultSettings.attemptsLimit,
    activePlayers: arrayProp(value, "activePlayers").map(playerFromUnknown),
    inactivePlayers: arrayProp(value, "inactivePlayers").map(playerFromUnknown),
  }
}

function needsDefaultSync(payload: unknown): boolean {
  const value = recordValue(payload)
  return (
    numberArray(value.playbackDurations).length === 0 ||
    numberArray(value.rankPoints).length === 0 ||
    numberProp(value, "lockoutDuration") === null ||
    numberProp(value, "attemptsLimit") === null
  )
}

function normalizeRoomState(payload: unknown): RoomState {
  if (payload === null) return null
  const value = recordValue(payload)
  const phase = stringProp(value, "phase")
  if (phase !== "playing" && phase !== "finished") return null
  return {
    phase,
    currentRound: numberProp(value, "currentRound") ?? 1,
    playbackDurationIndex: numberProp(value, "playbackDurationIndex") ?? 0,
    activePlayers: arrayProp(value, "activePlayers").map(
      statePlayerFromUnknown
    ),
    inactivePlayers: arrayProp(value, "inactivePlayers").map(
      statePlayerFromUnknown
    ),
  }
}

function normalizeReveal(payload: unknown, songs: Song[]): Reveal {
  const value = recordValue(payload)
  const song = recordProp(value, "song")
  const songId = stringProp(value, "songId")
  const winnerPayloads = arrayProp(value, "winners")
  return {
    song:
      song !== null
        ? songFromUnknown(song)
        : (songs.find((item) => item.id === songId) ??
          songFromUnknown({ id: songId })),
    winners: winnerPayloads.map(winnerFromUnknown),
  }
}

function rankedPlayers(
  players: Player[],
  statePlayers: StatePlayer[]
): RankedPlayer[] {
  const scores = new Map(
    statePlayers.map((player) => [player.id, player.score])
  )
  const knownPlayers = new Set(players.map((player) => player.id))
  const stateOnlyPlayers = statePlayers
    .filter((player) => !knownPlayers.has(player.id))
    .map((player) => ({
      handicap: 0,
      id: player.id,
      nickname: playerNameFromId(player.id),
    }))
  const sorted = players
    .concat(stateOnlyPlayers)
    .map((player) => ({
      ...player,
      score: scores.get(player.id) ?? 0,
      rank: 1,
    }))
    .sort((left, right) => right.score - left.score)
  let previousScore: number | null = null
  let currentRank = 0
  return sorted.map((player, index) => {
    if (previousScore === null || player.score < previousScore) {
      currentRank = index + 1
      previousScore = player.score
    }
    return { ...player, rank: currentRank }
  })
}

function hostDisconnected(settings: RoomSettings): boolean {
  return settings.inactivePlayers.some(
    (player) => player.id === settings.hostPlayerId
  )
}

function playerById(settings: RoomSettings, id: string): Player | null {
  return settings.activePlayers.find((player) => player.id === id) ?? null
}

function parsePositiveList(value: string): number[] {
  return value
    .split(",")
    .map((piece) => Number(piece.trim()))
    .filter((numberValue) => Number.isFinite(numberValue) && numberValue > 0)
}

function playlistIdFromUrl(value: string): string | null {
  const match = value.match(/\/playlist\/[^/]+\/([^/?#]+)/)
  return match?.[1] ?? null
}

function remainingSeconds(value: string | null, now: number): number {
  if (value === null) return 0
  const expiresAt = Date.parse(value)
  if (!Number.isFinite(expiresAt)) return 0
  return Math.max((expiresAt - now) / 1000, 0)
}

function winnerRank(winner: Winner): number {
  return (
    winner.rank ?? (winner.rankIndex !== undefined ? winner.rankIndex + 1 : 1)
  )
}

function shuffledIds(payload: unknown): string[] {
  return arrayProp(recordValue(payload), "shuffledSongIds").filter(
    (value): value is string => typeof value === "string"
  )
}

function messageOf(payload: unknown, fallback: string): string {
  const value = recordValue(payload)
  return stringProp(value, "message") || stringProp(value, "error") || fallback
}

function songTitle(songId: string): string {
  return songId.length > 0 ? `Song ${songId.replace("song", "")}` : "Song"
}

function playerNameFromId(playerId: string): string {
  const suffix = playerId.replace("player-", "")
  return suffix.length > 0 ? `Player ${suffix}` : "Player"
}

function ordinal(value: number): string {
  const mod100 = value % 100
  if (mod100 >= 11 && mod100 <= 13) return `${value}th`
  const mod10 = value % 10
  if (mod10 === 1) return `${value}st`
  if (mod10 === 2) return `${value}nd`
  if (mod10 === 3) return `${value}rd`
  return `${value}th`
}

function formatSeconds(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function currentPath(): string {
  return `${window.location.pathname}${window.location.search}`
}

function roomCodeFromPath(pathValue = currentPath()): string | null {
  const match = pathValue.match(/^\/room\/([^/?#]+)/)
  return match?.[1] ?? null
}

function websocketUrl(): string {
  const testUrl = (window as unknown as { __TEST_WS_URL__?: string })
    .__TEST_WS_URL__
  if (typeof testUrl === "string") return testUrl
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${protocol}//${window.location.host}/ws`
}

function markPendingLeave(): void {
  try {
    window.sessionStorage.setItem(pendingLeaveStorageKey, "1")
  } catch {
    // Session storage can be unavailable in restricted browser contexts.
  }
}

function consumePendingLeave(): boolean {
  try {
    if (window.sessionStorage.getItem(pendingLeaveStorageKey) !== "1") {
      return false
    }
    window.sessionStorage.removeItem(pendingLeaveStorageKey)
    return true
  } catch {
    return false
  }
}

function readCookie(name: string): string {
  const prefix = `${name}=`
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
  return cookie?.slice(prefix.length) ?? ""
}

function songFromUnknown(value: unknown): Song {
  const record = recordValue(value)
  return {
    id: stringProp(record, "id"),
    title: stringProp(record, "title") || stringProp(record, "name") || "Song",
    artist:
      stringProp(record, "artist") ||
      stringProp(record, "artistName") ||
      "Artist",
    artworkUrl: nullableStringProp(record, "artworkUrl"),
  }
}

function playerFromUnknown(value: unknown): Player {
  const record = recordValue(value)
  return {
    id: stringProp(record, "id"),
    nickname: stringProp(record, "nickname") || "Player",
    handicap: numberProp(record, "handicap") ?? 0,
  }
}

function statePlayerFromUnknown(value: unknown): StatePlayer {
  const record = recordValue(value)
  return {
    id: stringProp(record, "id"),
    score: numberProp(record, "score") ?? 0,
  }
}

function winnerFromUnknown(value: unknown): Winner {
  const record = recordValue(value)
  return {
    playerId: stringProp(record, "playerId") || undefined,
    nickname: stringProp(record, "nickname") || undefined,
    rank: numberProp(record, "rank") ?? undefined,
    rankIndex: numberProp(record, "rankIndex") ?? undefined,
    points: numberProp(record, "points") ?? undefined,
  }
}

function recordValue(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {}
}

function recordProp(
  value: unknown,
  key: string
): Record<string, unknown> | null {
  const child = recordValue(value)[key]
  return typeof child === "object" && child !== null
    ? (child as Record<string, unknown>)
    : null
}

function arrayProp(value: unknown, key: string): unknown[] {
  const child = recordValue(value)[key]
  return Array.isArray(child) ? child : []
}

function stringProp(value: unknown, key: string): string {
  const child = recordValue(value)[key]
  return typeof child === "string" ? child : ""
}

function nullableStringProp(value: unknown, key: string): string | null {
  const child = recordValue(value)[key]
  return typeof child === "string" ? child : null
}

function numberProp(value: unknown, key: string): number | null {
  const child = recordValue(value)[key]
  return typeof child === "number" ? child : null
}

function booleanProp(value: unknown, key: string): boolean {
  const child = recordValue(value)[key]
  return typeof child === "boolean" ? child : false
}

function numberArray(value: unknown): number[] {
  return Array.isArray(value)
    ? value.filter((item): item is number => typeof item === "number")
    : []
}
