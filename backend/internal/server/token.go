package server

import (
	"crypto/ecdsa"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func (s *server) handleToken(w http.ResponseWriter, r *http.Request) {
	token, expiresAt, err := generateDeveloperToken()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Token generation failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{
		"token":     token,
		"expiresAt": expiresAt.Format(time.RFC3339),
	})
}

func generateDeveloperToken() (string, time.Time, error) {
	teamID := os.Getenv("APPLE_DEVELOPER_TEAM_ID")
	keyID := firstEnv("APPLE_MUSIC_KEY_ID", "APPLE_MUSIC_KIT_KEY_ID")
	keyPEM := os.Getenv("APPLE_MUSIC_KIT_AUTH_KEY")
	if teamID == "" || keyID == "" || keyPEM == "" {
		return "", time.Time{}, errors.New("missing Apple Music credentials")
	}

	key, err := parseECPrivateKey(keyPEM)
	if err != nil {
		return "", time.Time{}, err
	}

	now := time.Now().UTC()
	expiresAt := now.Add(24 * time.Hour)
	claims := jwt.MapClaims{
		"iss": teamID,
		"iat": now.Unix(),
		"exp": expiresAt.Unix(),
	}
	token := jwt.NewWithClaims(jwt.SigningMethodES256, claims)
	token.Header["kid"] = keyID
	signed, err := token.SignedString(key)
	if err != nil {
		return "", time.Time{}, err
	}
	return signed, expiresAt, nil
}

func parseECPrivateKey(value string) (*ecdsa.PrivateKey, error) {
	normalized := strings.ReplaceAll(value, `\n`, "\n")
	block, _ := pem.Decode([]byte(normalized))
	if block == nil {
		return nil, errors.New("invalid PEM")
	}
	if key, err := x509.ParseECPrivateKey(block.Bytes); err == nil {
		return key, nil
	}
	parsed, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return nil, err
	}
	key, ok := parsed.(*ecdsa.PrivateKey)
	if !ok {
		return nil, errors.New("private key is not ECDSA")
	}
	return key, nil
}

func firstEnv(names ...string) string {
	for _, name := range names {
		if value := os.Getenv(name); value != "" {
			return value
		}
	}
	return ""
}
