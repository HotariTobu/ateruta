package server

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
)

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func (s *server) handleSession(w http.ResponseWriter, r *http.Request) {
	if _, err := r.Cookie(sessionCookieName); err != nil {
		http.SetCookie(w, &http.Cookie{
			Name:     sessionCookieName,
			Value:    newUUID(),
			Path:     "/",
			MaxAge:   31536000,
			HttpOnly: true,
			Secure:   true,
			SameSite: http.SameSiteLaxMode,
		})
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ready": true})
}

func (s *server) handleCreateRoom(w http.ResponseWriter, r *http.Request) {
	playerID, ok := playerIDFromCookie(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}

	code, err := s.createRoom(playerID)
	if err != nil {
		if errors.Is(err, errNoAvailableRoomCodes) {
			writeError(w, http.StatusInternalServerError, "No available room codes")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, map[string]string{"code": code})
}

func (s *server) handleGetRoom(w http.ResponseWriter, r *http.Request) {
	playerID, ok := playerIDFromCookie(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}

	code := strings.TrimPrefix(r.URL.Path, "/api/room/")
	if !validRoomCode(code) {
		writeError(w, http.StatusBadRequest, "Invalid room code")
		return
	}

	status, message := s.checkRoomVisibility(playerID, code)
	if status != http.StatusOK {
		writeError(w, status, message)
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"exists": true})
}

func playerIDFromCookie(r *http.Request) (string, bool) {
	cookie, err := r.Cookie(sessionCookieName)
	if err != nil || cookie.Value == "" {
		return "", false
	}
	return cookie.Value, true
}

func newUUID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic(err)
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	buf := make([]byte, 36)
	hex.Encode(buf[0:8], b[0:4])
	buf[8] = '-'
	hex.Encode(buf[9:13], b[4:6])
	buf[13] = '-'
	hex.Encode(buf[14:18], b[6:8])
	buf[18] = '-'
	hex.Encode(buf[19:23], b[8:10])
	buf[23] = '-'
	hex.Encode(buf[24:36], b[10:16])
	return string(buf)
}
