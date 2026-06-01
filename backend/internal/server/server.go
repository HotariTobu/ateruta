package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"
)

const roomDeletionGrace = 5 * time.Minute

var errNoAvailableRoomCodes = errors.New("no available room codes")

type server struct {
	mu    sync.Mutex
	rooms map[string]*room
}

func newServer() *server {
	return &server{rooms: make(map[string]*room)}
}

func NewHandler() http.Handler {
	app := newServer()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/session", app.handleSession)
	mux.HandleFunc("POST /api/room", app.handleCreateRoom)
	mux.HandleFunc("GET /api/room/", app.handleGetRoom)
	mux.HandleFunc("GET /api/token", app.handleToken)
	mux.HandleFunc("GET /ws", app.handleWebSocket)
	return withCORS(mux)
}

func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Access-Control-Allow-Credentials", "true")
			w.Header().Set("Vary", "Origin")
		}
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *server) createRoom(playerID string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	closedCodes := s.leaveHostedRoomsLocked(playerID)
	s.leaveActiveRoomsForCreateLocked(playerID)

	code := ""
	for i := 1000; i <= 9999; i++ {
		candidate := fmt.Sprintf("%04d", i)
		if _, closed := closedCodes[candidate]; closed {
			continue
		}
		if _, exists := s.rooms[candidate]; !exists {
			code = candidate
			break
		}
	}
	if code == "" {
		return "", errNoAvailableRoomCodes
	}

	rm := &room{
		Code:              code,
		HostPlayerID:      playerID,
		Songs:             []song{},
		PlaybackDurations: []float64{},
		RankPoints:        []int{},
		ActivePlayers:     make(map[string]*playerProfile),
		InactivePlayers:   make(map[string]*playerProfile),
	}
	s.rooms[code] = rm
	s.scheduleDeletionLocked(rm)
	return code, nil
}

func (s *server) leaveHostedRoomsLocked(playerID string) map[string]struct{} {
	closedCodes := make(map[string]struct{})
	for _, rm := range s.rooms {
		if rm.HostPlayerID != playerID {
			continue
		}
		closedCodes[rm.Code] = struct{}{}
		s.closeRoomLocked(rm, "Room closed by host")
	}
	return closedCodes
}

func (s *server) leaveActiveRoomsForCreateLocked(playerID string) {
	for _, rm := range s.rooms {
		if rm.HostPlayerID == playerID {
			continue
		}
		if _, ok := rm.ActivePlayers[playerID]; ok {
			s.moveActiveToInactiveLocked(rm, playerID)
			s.cancelPendingLocked(rm, playerID)
			s.broadcastSettingsLocked(rm)
			if rm.State != nil {
				s.broadcastStateLocked(rm)
			}
		}
	}
}

func (s *server) checkRoomVisibility(playerID, code string) (int, string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[code]
	if rm == nil {
		return http.StatusNotFound, "Room not found"
	}
	if rm.State == nil {
		return http.StatusOK, ""
	}
	if s.isGameParticipantLocked(rm, playerID) {
		return http.StatusOK, ""
	}
	if rm.State.Phase == "playing" {
		return http.StatusForbidden, "Game already in progress"
	}
	return http.StatusForbidden, "Game has ended"
}

func validRoomCode(code string) bool {
	if len(code) != 4 {
		return false
	}
	n, err := strconv.Atoi(code)
	if err != nil {
		return false
	}
	return n >= 1000 && n <= 9999
}

func (s *server) handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		OriginPatterns: []string{"*"},
	})
	if err != nil {
		return
	}
	conn.SetReadLimit(4 << 20)

	playerID, ok := playerIDFromCookie(r)
	if !ok {
		_ = conn.Close(closeUnauthorized, "Unauthorized")
		return
	}

	c := newClient(playerID, conn)
	defer s.disconnectClient(c)

	for {
		_, data, err := conn.Read(r.Context())
		if err != nil {
			return
		}
		s.handleWebSocketMessage(c, data)
	}
}

func (s *server) handleWebSocketMessage(c *client, data []byte) {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		c.send("error", map[string]any{"message": "Invalid message format"})
		return
	}

	var event string
	if err := json.Unmarshal(raw["event"], &event); err != nil || event == "" {
		c.send("error", map[string]any{"message": "Invalid message format"})
		return
	}
	if !knownEvent(event) {
		c.send("error", map[string]any{"message": "Unknown event"})
		return
	}

	payload := map[string]json.RawMessage{}
	if rawPayload, ok := raw["payload"]; ok && string(rawPayload) != "null" {
		if err := json.Unmarshal(rawPayload, &payload); err != nil {
			c.send("error", map[string]any{"message": "Invalid message format"})
			return
		}
	}
	if hasUnknownPayloadFields(event, payload) {
		c.send("error", map[string]any{"message": "Unknown fields in payload"})
		return
	}

	if event != "room:join" && event != "room:leave" && c.roomCode == "" {
		c.send("error", map[string]any{"message": "Not in a room"})
		return
	}

	switch event {
	case "room:join":
		s.handleRoomJoin(c, payload)
	case "room:leave":
		s.handleRoomLeave(c)
	case "room:nickname":
		s.handleNickname(c, payload)
	case "room:handicap":
		s.handleHandicap(c, payload)
	case "room:settings":
		s.handleSettings(c, payload)
	case "game:start":
		s.handleGameStart(c)
	case "game:play-song":
		s.handleGamePlaySong(c)
	case "game:extend":
		s.handleGameExtend(c)
	case "game:close-answers":
		s.handleGameCloseAnswers(c)
	case "game:next-round":
		s.handleGameNextRound(c)
	case "game:end":
		s.handleGameEnd(c)
	case "game:back-to-lobby":
		s.handleGameBackToLobby(c)
	case "game:answer":
		s.handleGameAnswer(c, payload, false)
	}
}

func knownEvent(event string) bool {
	_, ok := allowedPayloadFields[event]
	return ok
}

var allowedPayloadFields = map[string]map[string]struct{}{
	"room:join":          {"code": {}},
	"room:leave":         {},
	"room:nickname":      {"nickname": {}},
	"room:handicap":      {"handicap": {}},
	"room:settings":      {"songs": {}, "totalRounds": {}, "playbackDurations": {}, "rankPoints": {}, "lockoutDuration": {}, "attemptsLimit": {}},
	"game:start":         {},
	"game:play-song":     {},
	"game:answer":        {"songId": {}},
	"game:extend":        {},
	"game:close-answers": {},
	"game:next-round":    {},
	"game:end":           {},
	"game:back-to-lobby": {},
}

func hasUnknownPayloadFields(event string, payload map[string]json.RawMessage) bool {
	allowed := allowedPayloadFields[event]
	for key := range payload {
		if _, ok := allowed[key]; !ok {
			return true
		}
	}
	return false
}

func (c *client) send(event string, payload any) {
	c.sendMu <- struct{}{}
	defer func() { <-c.sendMu }()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = c.conn.Write(ctx, websocket.MessageText, mustJSON(envelope{Event: event, Payload: payload}))
}

func mustJSON(value any) []byte {
	data, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return data
}

func (s *server) handleRoomJoin(c *client, payload map[string]json.RawMessage) {
	code := readString(payload["code"])

	s.mu.Lock()
	defer s.mu.Unlock()

	if !validRoomCode(code) {
		c.send("error", map[string]any{"message": "Invalid room code"})
		return
	}

	rm := s.rooms[code]
	if rm == nil {
		c.send("error", map[string]any{"message": "Room not found"})
		return
	}

	if c.roomCode == code {
		if current := rm.ActivePlayers[c.id]; current != nil && current.client == c {
			return
		}
	}

	if activeRoom := s.activeRoomForPlayerLocked(c.id); activeRoom != "" && activeRoom != code {
		c.send("error", map[string]any{"message": "Already in another room"})
		return
	}

	presentInState := s.isGameParticipantLocked(rm, c.id)
	if rm.State != nil && !presentInState {
		if rm.State.Phase == "playing" {
			c.send("error", map[string]any{"message": "Game already in progress"})
			return
		}
		c.send("error", map[string]any{"message": "Game has ended"})
		return
	}

	if !presentInState && len(rm.ActivePlayers) >= 20 {
		c.send("error", map[string]any{"message": "Room is full"})
		return
	}

	s.removeFromInactiveRoomsLocked(c.id, code)
	profile := s.profileForJoinLocked(rm, c.id)
	if profile.client != nil && profile.client != c {
		old := profile.client
		old.replaced = true
		old.roomCode = ""
		_ = old.conn.Close(closeTakeover, "Connected from another location")
	}
	profile.client = c
	c.roomCode = code

	delete(rm.InactivePlayers, c.id)
	rm.InactiveOrder = removeString(rm.InactiveOrder, c.id)
	rm.ActivePlayers[c.id] = profile
	if !containsString(rm.ActiveOrder, c.id) {
		rm.ActiveOrder = append(rm.ActiveOrder, c.id)
	}

	if rm.State != nil {
		if score, ok := rm.State.InactiveScores[c.id]; ok {
			delete(rm.State.InactiveScores, c.id)
			rm.State.ActiveScores[c.id] = score
			rm.State.InactiveOrder = removeString(rm.State.InactiveOrder, c.id)
			if !containsString(rm.State.ActiveOrder, c.id) {
				rm.State.ActiveOrder = append(rm.State.ActiveOrder, c.id)
			}
		}
	}

	if c.id == rm.HostPlayerID {
		s.cancelDeletionLocked(rm)
	}

	s.broadcastSettingsLocked(rm)
	if rm.State != nil {
		s.broadcastStateLocked(rm)
	}
	if c.id == rm.HostPlayerID && len(rm.GameSongs) > 0 {
		s.sendShuffledSongsLocked(c, rm)
	}
	if rm.State != nil && rm.State.Phase == "playing" {
		if rm.State.Revealed {
			winners := rm.State.Winners
			if winners == nil {
				winners = []winner{}
			}
			c.send("game:restore-reveal", map[string]any{
				"songId":  s.currentSongIDLocked(rm),
				"winners": winners,
			})
		} else {
			c.send("game:player-state", s.playerRoundStateLocked(rm, c.id))
		}
	}
}

func (s *server) handleRoomLeave(c *client) {
	if c.roomCode == "" {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.departClientLocked(c)
}

func (s *server) disconnectClient(c *client) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if c.replaced || c.roomCode == "" {
		return
	}
	s.departClientLocked(c)
}

func (s *server) departClientLocked(c *client) {
	rm := s.rooms[c.roomCode]
	if rm == nil {
		c.roomCode = ""
		return
	}
	s.moveActiveToInactiveLocked(rm, c.id)
	if c.id == rm.HostPlayerID || len(rm.ActivePlayers) == 0 {
		s.scheduleDeletionLocked(rm)
	}
	c.roomCode = ""
	s.broadcastSettingsLocked(rm)
	if rm.State != nil {
		s.broadcastStateLocked(rm)
	}
}

func (s *server) activeRoomForPlayerLocked(playerID string) string {
	for code, rm := range s.rooms {
		if profile := rm.ActivePlayers[playerID]; profile != nil && profile.client != nil {
			return code
		}
	}
	return ""
}

func (s *server) removeFromInactiveRoomsLocked(playerID, exceptCode string) {
	for _, rm := range s.rooms {
		if rm.Code == exceptCode {
			continue
		}
		if _, ok := rm.InactivePlayers[playerID]; ok {
			delete(rm.InactivePlayers, playerID)
			rm.InactiveOrder = removeString(rm.InactiveOrder, playerID)
			s.cancelPendingLocked(rm, playerID)
			s.broadcastSettingsLocked(rm)
			if rm.State != nil {
				delete(rm.State.InactiveScores, playerID)
				rm.State.InactiveOrder = removeString(rm.State.InactiveOrder, playerID)
				s.broadcastStateLocked(rm)
			}
		}
	}
}

func (s *server) profileForJoinLocked(rm *room, playerID string) *playerProfile {
	if profile := rm.ActivePlayers[playerID]; profile != nil {
		return profile
	}
	if profile := rm.InactivePlayers[playerID]; profile != nil {
		return profile
	}
	rm.NicknameCounter++
	return &playerProfile{
		ID:       playerID,
		Nickname: fmt.Sprintf("Player %d", rm.NicknameCounter),
		Handicap: 0,
	}
}

func (s *server) moveActiveToInactiveLocked(rm *room, playerID string) {
	profile := rm.ActivePlayers[playerID]
	if profile == nil {
		return
	}
	if profile.client != nil {
		profile.client.roomCode = ""
	}
	profile.client = nil
	delete(rm.ActivePlayers, playerID)
	rm.ActiveOrder = removeString(rm.ActiveOrder, playerID)
	rm.InactivePlayers[playerID] = profile
	if !containsString(rm.InactiveOrder, playerID) {
		rm.InactiveOrder = append(rm.InactiveOrder, playerID)
	}

	if rm.State != nil {
		if score, ok := rm.State.ActiveScores[playerID]; ok {
			delete(rm.State.ActiveScores, playerID)
			rm.State.ActiveOrder = removeString(rm.State.ActiveOrder, playerID)
			rm.State.InactiveScores[playerID] = score
			if !containsString(rm.State.InactiveOrder, playerID) {
				rm.State.InactiveOrder = append(rm.State.InactiveOrder, playerID)
			}
		}
	}
}

func (s *server) isGameParticipantLocked(rm *room, playerID string) bool {
	if rm.State == nil {
		return false
	}
	if _, ok := rm.State.ActiveScores[playerID]; ok {
		return true
	}
	_, ok := rm.State.InactiveScores[playerID]
	return ok
}

func (s *server) scheduleDeletionLocked(rm *room) {
	s.cancelDeletionLocked(rm)
	code := rm.Code
	rm.deletionTimer = time.AfterFunc(roomDeletionGrace, func() {
		s.mu.Lock()
		defer s.mu.Unlock()
		current := s.rooms[code]
		if current == nil {
			return
		}
		s.closeRoomLocked(current, "Room closed due to inactivity")
	})
}

func (s *server) cancelDeletionLocked(rm *room) {
	if rm.deletionTimer != nil {
		rm.deletionTimer.Stop()
		rm.deletionTimer = nil
	}
}

func (s *server) closeRoomLocked(rm *room, message string) {
	s.cancelDeletionLocked(rm)
	clients := s.roomClientsLocked(rm)
	for _, c := range clients {
		c.send("room:closed", map[string]any{"message": message})
		c.roomCode = ""
		_ = c.conn.Close(websocket.StatusNormalClosure, message)
	}
	delete(s.rooms, rm.Code)
}

func (s *server) roomClientsLocked(rm *room) []*client {
	clients := make([]*client, 0, len(rm.ActivePlayers))
	for _, id := range rm.ActiveOrder {
		if profile := rm.ActivePlayers[id]; profile != nil && profile.client != nil {
			clients = append(clients, profile.client)
		}
	}
	return clients
}

func (s *server) broadcastSettingsLocked(rm *room) {
	payload := s.settingsPayloadLocked(rm)
	for _, c := range s.roomClientsLocked(rm) {
		c.send("room:settings", payload)
	}
}

func (s *server) broadcastStateLocked(rm *room) {
	var payload any
	if rm.State == nil {
		payload = nil
	} else {
		payload = s.statePayloadLocked(rm)
	}
	for _, c := range s.roomClientsLocked(rm) {
		c.send("room:state", payload)
	}
}

func (s *server) settingsPayloadLocked(rm *room) roomSettingsPayload {
	active := make([]playerSettingsPayload, 0, len(rm.ActiveOrder))
	for _, id := range rm.ActiveOrder {
		if p := rm.ActivePlayers[id]; p != nil {
			active = append(active, playerSettingsPayload{
				ID:       p.ID,
				Nickname: p.Nickname,
				Handicap: p.Handicap,
			})
		}
	}
	inactive := make([]playerSettingsPayload, 0, len(rm.InactiveOrder))
	for _, id := range rm.InactiveOrder {
		if p := rm.InactivePlayers[id]; p != nil {
			inactive = append(inactive, playerSettingsPayload{
				ID:       p.ID,
				Nickname: p.Nickname,
				Handicap: p.Handicap,
			})
		}
	}
	return roomSettingsPayload{
		HostPlayerID:      rm.HostPlayerID,
		Songs:             rm.Songs,
		TotalRounds:       rm.TotalRounds,
		PlaybackDurations: rm.PlaybackDurations,
		RankPoints:        rm.RankPoints,
		LockoutDuration:   rm.LockoutDuration,
		AttemptsLimit:     rm.AttemptsLimit,
		ActivePlayers:     active,
		InactivePlayers:   inactive,
	}
}

func (s *server) statePayloadLocked(rm *room) roomStatePayload {
	st := rm.State
	active := make([]statePlayerPayload, 0, len(st.ActiveOrder))
	for _, id := range st.ActiveOrder {
		if score, ok := st.ActiveScores[id]; ok {
			active = append(active, statePlayerPayload{ID: id, Score: score})
		}
	}
	inactive := make([]statePlayerPayload, 0, len(st.InactiveOrder))
	for _, id := range st.InactiveOrder {
		if score, ok := st.InactiveScores[id]; ok {
			inactive = append(inactive, statePlayerPayload{ID: id, Score: score})
		}
	}
	return roomStatePayload{
		Phase:                 st.Phase,
		CurrentRound:          st.CurrentRound,
		PlaybackDurationIndex: st.PlaybackDurationIndex,
		ActivePlayers:         active,
		InactivePlayers:       inactive,
	}
}

func readString(raw json.RawMessage) string {
	var value string
	_ = json.Unmarshal(raw, &value)
	return value
}

func readNumber(raw json.RawMessage) (float64, bool) {
	var n json.Number
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.UseNumber()
	if err := decoder.Decode(&n); err != nil {
		return 0, false
	}
	value, err := n.Float64()
	return value, err == nil
}

func isInteger(value float64) bool {
	return math.Trunc(value) == value
}

func removeString(values []string, target string) []string {
	out := values[:0]
	for _, value := range values {
		if value != target {
			out = append(out, value)
		}
	}
	return out
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
