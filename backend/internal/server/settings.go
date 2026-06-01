package server

import (
	"encoding/json"
	"strings"
	"unicode"
)

func (s *server) handleNickname(c *client, payload map[string]json.RawMessage) {
	nickname := sanitizeNickname(readString(payload["nickname"]))

	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if rm == nil {
		return
	}
	if rm.State != nil {
		c.send("error", map[string]any{"message": "Can only change nickname in lobby"})
		return
	}
	if nickname == "" {
		c.send("error", map[string]any{"message": "Nickname is required"})
		return
	}
	if len([]rune(nickname)) > 20 {
		c.send("error", map[string]any{"message": "Nickname must be 20 characters or less"})
		return
	}
	if p := rm.ActivePlayers[c.id]; p != nil {
		p.Nickname = nickname
	}
	s.broadcastSettingsLocked(rm)
}

func sanitizeNickname(value string) string {
	cleaned := strings.Map(func(r rune) rune {
		if unicode.IsControl(r) {
			return -1
		}
		return r
	}, value)
	return strings.TrimSpace(cleaned)
}

func (s *server) handleHandicap(c *client, payload map[string]json.RawMessage) {
	handicap, _ := readNumber(payload["handicap"])

	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if rm == nil {
		return
	}
	if rm.State != nil {
		c.send("error", map[string]any{"message": "Can only change handicap in lobby"})
		return
	}
	if handicap < 0 || handicap > 30 {
		c.send("error", map[string]any{"message": "Handicap must be between 0 and 30 seconds"})
		return
	}
	if p := rm.ActivePlayers[c.id]; p != nil {
		p.Handicap = handicap
	}
	s.broadcastSettingsLocked(rm)
}

func (s *server) handleSettings(c *client, payload map[string]json.RawMessage) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rm := s.rooms[c.roomCode]
	if rm == nil {
		return
	}
	if c.id != rm.HostPlayerID {
		c.send("error", map[string]any{"message": "Only the host can change settings"})
		return
	}
	if rm.State != nil {
		c.send("error", map[string]any{"message": "Can only change settings in lobby"})
		return
	}
	if len(payload) == 0 {
		c.send("error", map[string]any{"message": "Settings payload must not be empty"})
		return
	}

	update, errors := validateSettingsPayload(payload)
	if len(errors) > 0 {
		c.send("error", map[string]any{
			"message": "Settings validation failed",
			"details": errors,
		})
		return
	}

	if update.songsSet {
		rm.Songs = update.songs
		rm.GameSongs = shuffleSongs(rm.Songs, rm.shuffleVersion)
		rm.shuffleVersion++
	}
	if update.totalRoundsSet {
		rm.TotalRounds = update.totalRounds
	}
	if update.playbackDurationsSet {
		rm.PlaybackDurations = update.playbackDurations
	}
	if update.rankPointsSet {
		rm.RankPoints = update.rankPoints
	}
	if update.lockoutDurationSet {
		rm.LockoutDuration = update.lockoutDuration
	}
	if update.attemptsLimitSet {
		rm.AttemptsLimit = update.attemptsLimit
	}

	s.broadcastSettingsLocked(rm)
	if update.songsSet && len(rm.GameSongs) > 0 {
		if host := rm.ActivePlayers[rm.HostPlayerID]; host != nil && host.client != nil {
			s.sendShuffledSongsLocked(host.client, rm)
		}
	}
}

type settingsUpdate struct {
	songsSet             bool
	songs                []song
	totalRoundsSet       bool
	totalRounds          *int
	playbackDurationsSet bool
	playbackDurations    []float64
	rankPointsSet        bool
	rankPoints           []int
	lockoutDurationSet   bool
	lockoutDuration      *float64
	attemptsLimitSet     bool
	attemptsLimit        *int
}

func validateSettingsPayload(payload map[string]json.RawMessage) (settingsUpdate, []string) {
	var update settingsUpdate
	var errors []string

	if raw, ok := payload["songs"]; ok {
		update.songsSet = true
		var songs []song
		if err := json.Unmarshal(raw, &songs); err == nil {
			update.songs = songs
			errors = append(errors, validateSongs(songs)...)
		}
	}

	if raw, ok := payload["playbackDurations"]; ok {
		update.playbackDurationsSet = true
		var values []float64
		if err := json.Unmarshal(raw, &values); err == nil {
			update.playbackDurations = values
			errors = append(errors, validatePlaybackDurations(values)...)
		}
	}

	if raw, ok := payload["rankPoints"]; ok {
		update.rankPointsSet = true
		points, fieldErrors := decodeRankPoints(raw)
		update.rankPoints = points
		errors = append(errors, fieldErrors...)
	}

	if raw, ok := payload["lockoutDuration"]; ok {
		update.lockoutDurationSet = true
		if value, ok := readNumber(raw); ok {
			update.lockoutDuration = &value
			if value < 0 || value > 30 {
				errors = append(errors, "Lockout duration must be between 0 and 30 seconds")
			}
		}
	}

	if raw, ok := payload["attemptsLimit"]; ok {
		update.attemptsLimitSet = true
		if value, ok := readNumber(raw); ok {
			intValue := int(value)
			update.attemptsLimit = &intValue
			if !isInteger(value) {
				errors = append(errors, "Attempts limit must be an integer")
			} else if value < 0 || value > 10 {
				errors = append(errors, "Attempts limit must be between 0 and 10")
			}
		}
	}

	if raw, ok := payload["totalRounds"]; ok {
		update.totalRoundsSet = true
		if value, ok := readNumber(raw); ok {
			intValue := int(value)
			update.totalRounds = &intValue
			if !isInteger(value) {
				errors = append(errors, "Total rounds must be an integer")
			} else if value < 1 {
				errors = append(errors, "Total rounds must be at least 1")
			} else if value > 1000 {
				errors = append(errors, "Total rounds must not exceed 1000")
			}
		}
	}

	return update, errors
}

func validateSongs(songs []song) []string {
	var errors []string
	if len(songs) > 1000 {
		errors = append(errors, "Songs must not exceed 1000")
	}
	seen := make(map[string]struct{}, len(songs))
	for _, s := range songs {
		if s.ID == "" {
			errors = append(errors, "Song ID is required")
		}
		if s.Title == "" {
			errors = append(errors, "Song title is required")
		}
		if s.Artist == "" {
			errors = append(errors, "Song artist is required")
		}
		if s.ArtworkURL != nil && *s.ArtworkURL == "" {
			errors = append(errors, "Song artwork URL must not be empty")
		}
		if s.ID != "" {
			if _, ok := seen[s.ID]; ok {
				errors = append(errors, "Duplicate song IDs are not allowed")
			}
			seen[s.ID] = struct{}{}
		}
	}
	return dedupeErrors(errors)
}

func validatePlaybackDurations(values []float64) []string {
	var errors []string
	if len(values) == 0 {
		errors = append(errors, "Playback durations are required")
	}
	if len(values) > 10 {
		errors = append(errors, "Playback durations must not exceed 10 entries")
	}
	for i, value := range values {
		if value <= 0 {
			errors = append(errors, "Playback durations must contain only positive numbers")
		}
		if value > 300 {
			errors = append(errors, "Playback durations must not exceed 300 seconds each")
		}
		if i > 0 && value <= values[i-1] {
			errors = append(errors, "Playback durations must be in ascending order")
		}
	}
	return dedupeErrors(errors)
}

func decodeRankPoints(raw json.RawMessage) ([]int, []string) {
	var values []float64
	if err := json.Unmarshal(raw, &values); err != nil {
		return nil, nil
	}
	points := make([]int, 0, len(values))
	var errors []string
	if len(values) == 0 {
		errors = append(errors, "Rank points are required")
	}
	if len(values) > 10 {
		errors = append(errors, "Rank points must not exceed 10 entries")
	}
	for _, value := range values {
		if value <= 0 {
			errors = append(errors, "Rank points must contain only positive numbers")
		}
		if !isInteger(value) {
			errors = append(errors, "Rank points must contain only integers")
		}
		points = append(points, int(value))
	}
	return points, dedupeErrors(errors)
}

func dedupeErrors(values []string) []string {
	seen := map[string]struct{}{}
	out := make([]string, 0, len(values))
	for _, value := range values {
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		out = append(out, value)
	}
	return out
}

func shuffleSongs(songs []song, version int) []song {
	out := append([]song(nil), songs...)
	n := len(out)
	if n <= 1 {
		return out
	}
	shift := (version % (n - 1)) + 1
	rotated := append(append([]song(nil), out[shift:]...), out[:shift]...)
	return rotated
}

func (s *server) sendShuffledSongsLocked(c *client, rm *room) {
	ids := make([]string, 0, len(rm.GameSongs))
	for _, song := range rm.GameSongs {
		ids = append(ids, song.ID)
	}
	c.send("game:shuffled-songs", map[string]any{"shuffledSongIds": ids})
}
