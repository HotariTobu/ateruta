Feature: Session and HTTP API
  As a client
  I want to manage sessions and access HTTP endpoints

  # --- Session management ---

  Scenario: Session ID is resolved from cookie
    When a player connects via WebSocket
    Then the player ID is read from the "ateruta-player-id" cookie

  Scenario: WebSocket connection without cookie is rejected
    When a player connects via WebSocket without an ateruta-player-id cookie
    Then the connection is closed with close code 4401

  Scenario: HTTP endpoints identify player from cookie
    When a client calls an HTTP endpoint that requires player identification
    Then the player ID is read from the ateruta-player-id cookie

  Scenario: POST /api/room without cookie is rejected
    When a client calls POST /api/room without an ateruta-player-id cookie
    Then the response status is 401

  Scenario: GET /api/room/{code} without cookie is rejected
    When a client calls GET /api/room/{code} without an ateruta-player-id cookie
    Then the response status is 401

  # Design: The developer token is application-level, not user-specific,
  # so no session identification is needed.
  Scenario: GET /api/token does not require a session cookie
    When a client calls GET /api/token without an ateruta-player-id cookie
    Then the response contains { token, expiresAt }

  Scenario: GET /api/session issues session cookie
    Given no ateruta-player-id cookie is present
    When a client calls GET /api/session
    Then a Set-Cookie header is returned with a new UUID
    And the cookie attributes are HttpOnly, Secure, SameSite=Lax, Max-Age=31536000, Path=/
    And the response body is { ready: true }

  Scenario: GET /api/session with existing cookie
    Given an ateruta-player-id cookie is already present
    When a client calls GET /api/session
    Then no Set-Cookie header is returned
    And the response body is { ready: true }

  # --- Developer token ---

  # Design: 24-hour validity ensures the token does not expire during
  # any realistic play session.
  Scenario: GET /api/token returns developer token
    Given Apple Music credentials are configured
    When a client calls GET /api/token
    Then the response contains { token, expiresAt }
    And the token is a JWT signed with ES256
    And the token is valid for 24 hours

  Scenario: GET /api/token error returns 500
    Given the token generation fails for any reason
    When a client calls GET /api/token
    Then the response status is 500

  # --- WebSocket error handling ---

  Scenario: WebSocket message pre-checks
    Then the server checks all WebSocket messages in the following order before event-specific checks:
      | check                          | error message              |
      | Message is valid JSON          | "Invalid message format"   |
      | Event type is known            | "Unknown event"            |
      | No unknown fields in payload   | "Unknown fields in payload" |
      | Player is in a room (except room:join and room:leave) | "Not in a room" |

  Scenario: Unknown event type returns error
    When the server receives a WebSocket message with an unknown event type
    Then the sender receives an error event with "Unknown event"

  Scenario: Malformed WebSocket message returns error
    When the server receives a WebSocket message that is not valid JSON
    Then the sender receives an error event with "Invalid message format"

  Scenario: Unknown fields in event payload are rejected
    When the server receives a WebSocket message with unknown fields in the payload
    Then the sender receives an error event with "Unknown fields in payload"

  Scenario: Event sent without being in a room
    Given a player is not in any room
    When the player sends any event other than room:join or room:leave
    Then the player receives an error event with "Not in a room"

  Scenario: room:leave without being in a room is a no-op
    Given a player is not in any room
    When the player sends room:leave
    Then no error is returned and no state changes
