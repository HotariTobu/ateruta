package server

import (
	"time"

	"github.com/coder/websocket"
)

const (
	sessionCookieName = "ateruta-player-id"
	closeUnauthorized = websocket.StatusCode(4401)
	closeTakeover     = websocket.StatusCode(4409)
)

type envelope struct {
	Event   string `json:"event"`
	Payload any    `json:"payload"`
}

type song struct {
	ID         string  `json:"id"`
	Title      string  `json:"title"`
	Artist     string  `json:"artist"`
	ArtworkURL *string `json:"artworkUrl"`
}

type playerProfile struct {
	ID       string  `json:"id"`
	Nickname string  `json:"nickname"`
	Handicap float64 `json:"handicap"`
	client   *client
}

type playerSettingsPayload struct {
	ID       string  `json:"id"`
	Nickname string  `json:"nickname"`
	Handicap float64 `json:"handicap"`
}

type roomSettingsPayload struct {
	HostPlayerID      string                  `json:"hostPlayerId"`
	Songs             []song                  `json:"songs"`
	TotalRounds       *int                    `json:"totalRounds"`
	PlaybackDurations []float64               `json:"playbackDurations"`
	RankPoints        []int                   `json:"rankPoints"`
	LockoutDuration   *float64                `json:"lockoutDuration"`
	AttemptsLimit     *int                    `json:"attemptsLimit"`
	ActivePlayers     []playerSettingsPayload `json:"activePlayers"`
	InactivePlayers   []playerSettingsPayload `json:"inactivePlayers"`
}

type statePlayerPayload struct {
	ID    string `json:"id"`
	Score int    `json:"score"`
}

type roomStatePayload struct {
	Phase                 string               `json:"phase"`
	CurrentRound          int                  `json:"currentRound"`
	PlaybackDurationIndex int                  `json:"playbackDurationIndex"`
	ActivePlayers         []statePlayerPayload `json:"activePlayers"`
	InactivePlayers       []statePlayerPayload `json:"inactivePlayers"`
}

type winner struct {
	PlayerID  string `json:"playerId"`
	RankIndex int    `json:"rankIndex"`
}

type playerRoundStatePayload struct {
	Scored           bool    `json:"scored"`
	ScoredRankIndex  *int    `json:"scoredRankIndex"`
	WrongAnswerCount int     `json:"wrongAnswerCount"`
	LockoutExpiresAt *string `json:"lockoutExpiresAt"`
	PendingSongID    *string `json:"pendingSongId"`
	PendingExpiresAt *string `json:"pendingExpiresAt"`
}

type penaltyState struct {
	WrongAnswerCount int
	LockoutExpiresAt *time.Time
	PendingSongID    *string
	PendingExpiresAt *time.Time
	timer            *time.Timer
	token            int64
	round            int
}

type roomState struct {
	Phase                 string
	CurrentRound          int
	PlaybackDurationIndex int
	ActiveScores          map[string]int
	InactiveScores        map[string]int
	ActiveOrder           []string
	InactiveOrder         []string
	Revealed              bool
	SongPlayed            bool
	Winners               []winner
	Penalties             map[string]*penaltyState
}

type room struct {
	Code              string
	HostPlayerID      string
	Songs             []song
	TotalRounds       *int
	PlaybackDurations []float64
	RankPoints        []int
	LockoutDuration   *float64
	AttemptsLimit     *int
	ActivePlayers     map[string]*playerProfile
	InactivePlayers   map[string]*playerProfile
	ActiveOrder       []string
	InactiveOrder     []string
	NicknameCounter   int
	GameSongs         []song
	shuffleVersion    int
	State             *roomState
	deletionTimer     *time.Timer
}

type client struct {
	id       string
	conn     *websocket.Conn
	roomCode string
	sendMu   chan struct{}
	replaced bool
}

func newClient(id string, conn *websocket.Conn) *client {
	return &client{
		id:     id,
		conn:   conn,
		sendMu: make(chan struct{}, 1),
	}
}
