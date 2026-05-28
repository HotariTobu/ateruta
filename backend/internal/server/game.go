package server

import (
	"encoding/json"
	"time"
)

func (s *server) handleGameStart(c *client) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if rm == nil {
		return
	}
	if c.id != rm.HostPlayerID {
		c.send("error", map[string]any{"message": "Only the host can start the game"})
		return
	}
	if rm.State != nil {
		c.send("error", map[string]any{"message": "Can only start game in lobby"})
		return
	}
	if len(rm.Songs) == 0 {
		c.send("error", map[string]any{"message": "Songs are required to start the game"})
		return
	}
	if rm.TotalRounds == nil {
		c.send("error", map[string]any{"message": "Total rounds are required"})
		return
	}
	if len(rm.Songs) < *rm.TotalRounds {
		c.send("error", map[string]any{"message": "Not enough songs for the specified number of rounds"})
		return
	}
	if len(rm.RankPoints) == 0 {
		c.send("error", map[string]any{"message": "Rank points are required"})
		return
	}
	if len(rm.PlaybackDurations) == 0 {
		c.send("error", map[string]any{"message": "Playback durations are required"})
		return
	}
	if rm.LockoutDuration == nil {
		c.send("error", map[string]any{"message": "Lockout duration is required"})
		return
	}
	if rm.AttemptsLimit == nil {
		c.send("error", map[string]any{"message": "Attempts limit is required"})
		return
	}

	if len(rm.GameSongs) == 0 {
		rm.GameSongs = shuffleSongs(rm.Songs, rm.shuffleVersion)
		rm.shuffleVersion++
		if host := rm.ActivePlayers[rm.HostPlayerID]; host != nil && host.client != nil {
			s.sendShuffledSongsLocked(host.client, rm)
		}
	}

	if len(rm.InactivePlayers) > 0 {
		rm.InactivePlayers = make(map[string]*playerProfile)
		rm.InactiveOrder = nil
		s.broadcastSettingsLocked(rm)
	}

	activeScores := make(map[string]int, len(rm.ActivePlayers))
	activeOrder := append([]string(nil), rm.ActiveOrder...)
	for _, id := range activeOrder {
		activeScores[id] = 0
	}
	rm.State = &roomState{
		Phase:                 "playing",
		CurrentRound:          1,
		PlaybackDurationIndex: 0,
		ActiveScores:          activeScores,
		InactiveScores:        make(map[string]int),
		ActiveOrder:           activeOrder,
		Penalties:             make(map[string]*penaltyState),
	}
	s.broadcastStateLocked(rm)
}

func (s *server) handleGamePlaySong(c *client) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if !s.requireHostPlayingLocked(c, rm, "Only the host can play songs") {
		return
	}
	if rm.State.Revealed {
		c.send("error", map[string]any{"message": "Round has already been revealed"})
		return
	}
	rm.State.SongPlayed = true
	for _, client := range s.roomClientsLocked(rm) {
		client.send("game:play-song", map[string]any{})
	}
}

func (s *server) handleGameExtend(c *client) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if !s.requireHostPlayingLocked(c, rm, "Only the host can extend duration") {
		return
	}
	if rm.State.Revealed {
		c.send("error", map[string]any{"message": "Round has already been revealed"})
		return
	}
	if rm.State.PlaybackDurationIndex >= len(rm.PlaybackDurations)-1 {
		c.send("error", map[string]any{"message": "Already at maximum duration"})
		return
	}
	rm.State.PlaybackDurationIndex++
	s.broadcastStateLocked(rm)
}

func (s *server) handleGameCloseAnswers(c *client) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if !s.requireHostPlayingLocked(c, rm, "Only the host can close answers") {
		return
	}
	if rm.State.Revealed {
		c.send("error", map[string]any{"message": "Round has already been revealed"})
		return
	}
	if !rm.State.SongPlayed {
		c.send("error", map[string]any{"message": "Song has not been played yet"})
		return
	}
	s.revealRoundLocked(rm)
}

func (s *server) handleGameNextRound(c *client) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if !s.requireHostPlayingLocked(c, rm, "Only the host can advance rounds") {
		return
	}
	if !rm.State.Revealed {
		c.send("error", map[string]any{"message": "Round has not been revealed"})
		return
	}
	if rm.TotalRounds == nil || rm.State.CurrentRound >= *rm.TotalRounds {
		c.send("error", map[string]any{"message": "All rounds have been played"})
		return
	}
	s.beginNextRoundLocked(rm)
	s.broadcastStateLocked(rm)
}

func (s *server) handleGameEnd(c *client) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if rm == nil {
		return
	}
	if c.id != rm.HostPlayerID {
		c.send("error", map[string]any{"message": "Only the host can end the game"})
		return
	}
	if rm.State == nil || rm.State.Phase != "playing" {
		c.send("error", map[string]any{"message": "Game is not in playing phase"})
		return
	}
	s.cancelAllPendingLocked(rm)
	s.resetPenaltiesLocked(rm)
	rm.GameSongs = nil
	rm.State.Phase = "finished"
	rm.State.Revealed = false
	rm.State.SongPlayed = false
	rm.State.Winners = nil
	s.broadcastStateLocked(rm)
}

func (s *server) handleGameBackToLobby(c *client) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if rm == nil {
		return
	}
	if c.id != rm.HostPlayerID {
		c.send("error", map[string]any{"message": "Only the host can return to lobby"})
		return
	}
	if rm.State == nil || rm.State.Phase != "finished" {
		c.send("error", map[string]any{"message": "Game has not finished"})
		return
	}
	rm.GameSongs = shuffleSongs(rm.Songs, rm.shuffleVersion)
	rm.shuffleVersion++
	if host := rm.ActivePlayers[rm.HostPlayerID]; host != nil && host.client != nil {
		s.sendShuffledSongsLocked(host.client, rm)
	}
	rm.State = nil
	s.broadcastStateLocked(rm)
}

func (s *server) requireHostPlayingLocked(c *client, rm *room, hostError string) bool {
	if rm == nil {
		return false
	}
	if c.id != rm.HostPlayerID {
		c.send("error", map[string]any{"message": hostError})
		return false
	}
	if rm.State == nil || rm.State.Phase != "playing" {
		c.send("error", map[string]any{"message": "Game is not in playing phase"})
		return false
	}
	return true
}

func (s *server) beginNextRoundLocked(rm *room) {
	s.cancelAllPendingLocked(rm)
	s.resetPenaltiesLocked(rm)
	rm.State.CurrentRound++
	rm.State.PlaybackDurationIndex = 0
	rm.State.Revealed = false
	rm.State.SongPlayed = false
	rm.State.Winners = nil
}

func (s *server) revealRoundLocked(rm *room) {
	s.cancelAllPendingLocked(rm)
	rm.State.Revealed = true
	winners := rm.State.Winners
	if winners == nil {
		winners = []winner{}
	}
	payload := map[string]any{
		"songId":  s.currentSongIDLocked(rm),
		"winners": winners,
	}
	for _, c := range s.roomClientsLocked(rm) {
		c.send("game:reveal", payload)
	}
	s.broadcastStateLocked(rm)
}

func (s *server) handleGameAnswer(c *client, payload map[string]json.RawMessage, silent bool) {
	songID := readString(payload["songId"])

	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if rm == nil {
		return
	}
	handicap := 0.0
	if p := rm.ActivePlayers[c.id]; p != nil {
		handicap = p.Handicap
	} else if p := rm.InactivePlayers[c.id]; p != nil {
		handicap = p.Handicap
	}
	if handicap > 0 && !silent {
		s.setPendingAnswerLocked(rm, c.id, songID, handicap)
		return
	}
	s.processAnswerLocked(rm, c, songID, silent)
}

func (s *server) processAnswerLocked(rm *room, c *client, songID string, silent bool) {
	st := rm.State
	sendError := func(message string) {
		if !silent {
			c.send("error", map[string]any{"message": message})
		}
	}
	if st == nil || st.Phase != "playing" {
		sendError("Game is not in playing phase")
		return
	}
	if st.Revealed {
		sendError("Round has been revealed")
		return
	}
	if songID == "" {
		sendError("Song ID is required")
		return
	}
	if !s.songExistsLocked(rm, songID) {
		sendError("Song not found")
		return
	}
	if len(st.Winners) >= s.scoringCapLocked(rm) {
		sendError("All scoring slots are filled")
		return
	}
	if rank := s.scoredRankLocked(rm, c.id); rank != nil {
		sendError("Already scored this round")
		return
	}
	penalty := s.penaltyLocked(rm, c.id)
	if rm.AttemptsLimit != nil && *rm.AttemptsLimit > 0 && penalty.WrongAnswerCount >= *rm.AttemptsLimit {
		sendError("No attempts remaining")
		return
	}
	if penalty.LockoutExpiresAt != nil {
		if time.Now().Before(*penalty.LockoutExpiresAt) {
			sendError("Locked out")
			return
		}
		penalty.LockoutExpiresAt = nil
	}

	penalty.PendingSongID = nil
	penalty.PendingExpiresAt = nil
	if songID != s.currentSongIDLocked(rm) {
		penalty.WrongAnswerCount++
		var expires *string
		if rm.LockoutDuration != nil && *rm.LockoutDuration > 0 {
			t := time.Now().Add(durationSeconds(*rm.LockoutDuration))
			penalty.LockoutExpiresAt = &t
			formatted := formatTime(t)
			expires = &formatted
		} else {
			penalty.LockoutExpiresAt = nil
		}
		if !silent {
			c.send("game:wrong-answer", map[string]any{"lockoutExpiresAt": expires})
		}
		return
	}

	rankIndex := len(st.Winners)
	st.Winners = append(st.Winners, winner{PlayerID: c.id, RankIndex: rankIndex})
	points := rm.RankPoints[rankIndex]
	if _, ok := st.ActiveScores[c.id]; ok {
		st.ActiveScores[c.id] += points
	} else if _, ok := st.InactiveScores[c.id]; ok {
		st.InactiveScores[c.id] += points
	}

	if len(st.Winners) >= s.scoringCapLocked(rm) {
		s.revealRoundLocked(rm)
		return
	}

	payload := map[string]any{"winner": winner{PlayerID: c.id, RankIndex: rankIndex}}
	for _, client := range s.roomClientsLocked(rm) {
		client.send("game:scored", payload)
	}
	s.broadcastStateLocked(rm)
}

func (s *server) setPendingAnswerLocked(rm *room, playerID, songID string, handicap float64) {
	penalty := s.penaltyLocked(rm, playerID)
	if penalty.timer != nil {
		penalty.timer.Stop()
	}
	penalty.token++
	token := penalty.token
	round := rm.State.CurrentRound
	expires := time.Now().Add(durationSeconds(handicap))
	penalty.round = round
	penalty.PendingSongID = &songID
	penalty.PendingExpiresAt = &expires
	roomCode := rm.Code
	penalty.timer = time.AfterFunc(durationSeconds(handicap), func() {
		s.processPendingAnswer(roomCode, playerID, songID, round, token)
	})
}

func (s *server) processPendingAnswer(roomCode, playerID, songID string, round int, token int64) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[roomCode]
	if rm == nil || rm.State == nil {
		return
	}
	penalty := s.penaltyLocked(rm, playerID)
	if penalty.token != token || rm.State.CurrentRound != round {
		return
	}
	penalty.timer = nil

	c := &client{id: playerID}
	if p := rm.ActivePlayers[playerID]; p != nil {
		c = p.client
	}
	if c == nil {
		c = &client{id: playerID}
	}
	s.processAnswerLocked(rm, c, songID, true)
}

func (s *server) songExistsLocked(rm *room, songID string) bool {
	for _, song := range rm.GameSongs {
		if song.ID == songID {
			return true
		}
	}
	return false
}

func (s *server) currentSongIDLocked(rm *room) string {
	if rm.State == nil || rm.State.CurrentRound <= 0 || rm.State.CurrentRound > len(rm.GameSongs) {
		return ""
	}
	return rm.GameSongs[rm.State.CurrentRound-1].ID
}

func (s *server) scoringCapLocked(rm *room) int {
	capacity := len(rm.RankPoints)
	active := len(rm.State.ActiveScores)
	if active < capacity {
		capacity = active
	}
	if capacity < 0 {
		return 0
	}
	return capacity
}

func (s *server) scoredRankLocked(rm *room, playerID string) *int {
	for _, w := range rm.State.Winners {
		if w.PlayerID == playerID {
			rank := w.RankIndex
			return &rank
		}
	}
	return nil
}

func (s *server) penaltyLocked(rm *room, playerID string) *penaltyState {
	if rm.State.Penalties == nil {
		rm.State.Penalties = make(map[string]*penaltyState)
	}
	penalty := rm.State.Penalties[playerID]
	if penalty == nil {
		penalty = &penaltyState{round: rm.State.CurrentRound}
		rm.State.Penalties[playerID] = penalty
	}
	return penalty
}

func (s *server) cancelPendingLocked(rm *room, playerID string) {
	if rm.State == nil {
		return
	}
	penalty := rm.State.Penalties[playerID]
	if penalty == nil {
		return
	}
	if penalty.timer != nil {
		penalty.timer.Stop()
		penalty.timer = nil
	}
	penalty.PendingSongID = nil
	penalty.PendingExpiresAt = nil
	penalty.token++
}

func (s *server) cancelAllPendingLocked(rm *room) {
	if rm.State == nil {
		return
	}
	for id := range rm.State.Penalties {
		s.cancelPendingLocked(rm, id)
	}
}

func (s *server) resetPenaltiesLocked(rm *room) {
	if rm.State == nil {
		return
	}
	for id, penalty := range rm.State.Penalties {
		if penalty.timer != nil {
			penalty.timer.Stop()
		}
		delete(rm.State.Penalties, id)
	}
}

func (s *server) playerRoundStateLocked(rm *room, playerID string) playerRoundStatePayload {
	penalty := s.penaltyLocked(rm, playerID)
	var lockout *string
	if penalty.LockoutExpiresAt != nil {
		value := formatTime(*penalty.LockoutExpiresAt)
		lockout = &value
	}
	var pendingExpires *string
	if penalty.PendingExpiresAt != nil {
		value := formatTime(*penalty.PendingExpiresAt)
		pendingExpires = &value
	}
	rank := s.scoredRankLocked(rm, playerID)
	return playerRoundStatePayload{
		Scored:           rank != nil,
		ScoredRankIndex:  rank,
		WrongAnswerCount: penalty.WrongAnswerCount,
		LockoutExpiresAt: lockout,
		PendingSongID:    penalty.PendingSongID,
		PendingExpiresAt: pendingExpires,
	}
}

func durationSeconds(seconds float64) time.Duration {
	return time.Duration(seconds * float64(time.Second))
}

func formatTime(value time.Time) string {
	return value.UTC().Format(time.RFC3339Nano)
}
