export type Song = {
  id: string
  title: string
  artist: string
  artworkUrl?: string | null
}

export type Player = {
  id: string
  nickname: string
  handicap: number
}

export type StatePlayer = {
  id: string
  score: number
}

export type RoomSettings = {
  hostPlayerId: string
  songs: Song[]
  totalRounds: number
  playbackDurations: number[]
  rankPoints: number[]
  lockoutDuration: number
  attemptsLimit: number
  activePlayers: Player[]
  inactivePlayers: Player[]
}

export type RoomState = {
  phase: "playing" | "finished"
  currentRound: number
  playbackDurationIndex: number
  activePlayers: StatePlayer[]
  inactivePlayers: StatePlayer[]
} | null

export type Winner = {
  playerId?: string
  nickname?: string
  rank?: number
  rankIndex?: number
  points?: number
}

export type Reveal = {
  song: Song
  winners: Winner[]
}

export type Toast = {
  id: number
  message: string
}

export type PlaybackStatus = "preparing" | "loading" | "ready"
