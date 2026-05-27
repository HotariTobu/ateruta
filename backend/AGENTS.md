# backend

Go WebSocket server. Handles room management, game progression, and scoring in-memory.

## Technologies

- `github.com/coder/websocket` — WebSocket communication
- `golang-jwt/jwt/v5` — Apple Music developer token generation (ES256)

## Commands

@Makefile

## Endpoints

- WebSocket — Real-time game communication
- `GET /api/token` — Returns Apple Music developer token
- `GET /api/session` — Issues/verifies session cookie
