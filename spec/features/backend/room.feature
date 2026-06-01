Feature: Room management
  As a player
  I want to create, join, and manage rooms
  So that I can participate in games

  # --- Room phases ---

  Scenario: Room has three phases
    Then a room is in one of three phases: lobby, playing, or finished
    And lobby is when roomState is null
    And playing and finished are indicated by the phase field in roomState

  # --- Room code format ---

  Scenario: Room code format
    Then a valid room code is a string of exactly 4 digits representing an integer between 1000 and 9999

  # --- Creation ---
  # Design: Codes start at 1000 (not 0000) to simplify input and prevent
  # premature navigation—the app auto-navigates on 4-digit completion.

  Scenario: Host creates a room
    When a player sends POST /api/room
    Then the response status is 201 with { code }
    And a room with a 4-digit code between 1000 and 9999 is created

  Scenario: Room creation fails on server error
    Given the server fails to handle room creation for any reason
    When a player sends POST /api/room
    Then the response status is 500 with { error }

  Scenario: Room code is unique
    Given a room exists
    When another player creates a room
    Then the new room has a different code

  Scenario: Room creation fails when all codes are exhausted
    Given all room codes between 1000 and 9999 are in use
    When a player sends POST /api/room
    Then the response status is 500 with { error: "No available room codes" }

  Scenario: Room is created with unset game settings
    When a player sends POST /api/room
    Then the room settings are:
      | setting               | value             |
      | hostPlayerId          | <creator's player ID> |
      | songs                 | []                |
      | totalRounds           | null              |
      | playbackDurations     | []                |
      | rankPoints            | []                |
      | lockoutDuration       | null              |
      | attemptsLimit         | null              |
      | activePlayers         | []                |
      | inactivePlayers       | []                |

  # Design: Auto-closing prevents orphaned rooms from blocking the host
  # when the previous session was not properly cleaned up.
  Scenario: Creating a room closes existing hosted room
    Given a player is the host of an existing room
    When the player sends POST /api/room
    Then the existing room is closed
    And remaining connections receive a room:closed event with { message: "Room closed by host" }
    And all sockets are forced to leave the room
    And a new room is created and returned

  Scenario: Creating a room leaves existing non-hosted room
    Given a player is in activePlayers of a room they do not host
    When the player sends POST /api/room
    Then the player is moved from activePlayers to inactivePlayers in the existing room
    And room:settings is broadcast to the existing room
    And room:state is broadcast to the existing room if roomState is not null
    And a new room is created and returned

  # --- Joining ---

  Scenario: room:join check order
    Then the server checks room:join in the following order:
      | check                   | error message                                 |
      | Code is valid format    | "Invalid room code"                           |
      | Room exists             | "Room not found"                              |
      | Not in another room     | "Already in another room"                     |
      | Room in lobby phase     | "Game already in progress" or "Game has ended" |
      | Room not full           | "Room is full"                                |
    And players present in roomState (activePlayers or inactivePlayers) skip "Room in lobby phase" and "Room not full"
    And "Not in another room" does not consider players in inactivePlayers as "in a room"
    And "Room in lobby phase" error is "Game already in progress" during playing or "Game has ended" during finished
    And "Room not full" checks whether activePlayers count has reached 20

  Scenario: Player joins an existing room in lobby
    Given a room exists in lobby phase
    When a player sends room:join
    Then the player is added to the room
    And the player's nickname is auto-assigned
    And the player's handicap is 0
    And room:settings is broadcast to the room

  Scenario: Player cannot join a non-existent room
    When a player sends room:join for room "9999" that does not exist
    Then the player receives an error event with "Room not found"

  # Design: 20 is the estimated upper limit for an enjoyable game session.
  Scenario: Room is limited to 20 active players
    Given a room exists with 20 active players
    When a player sends room:join
    Then the player receives an error event with "Room is full"

  Scenario: Same socket joining same room is a no-op
    Given a player is already in the room
    When the same socket sends room:join for the same room
    Then no error is returned and no state changes

  # Design: The new connection takes over to prevent improperly closed
  # connections from permanently blocking the player.
  Scenario: Same player ID joining from a new connection takes over
    Given a player is in the room with an active WebSocket connection
    When the same player ID sends room:join from a different connection
    Then the new connection takes over
    And the old connection is closed with close code 4409

  # Design: No auto-leave to prevent unintended departures from the
  # current room.
  Scenario: Player in another room cannot join a second room
    Given a player is already in a room
    When the player sends room:join for a different room
    Then the player receives an error event with "Already in another room"

  Scenario: Non-participant cannot join during active game
    Given a game is in progress
    When a new player who was not in the lobby sends room:join
    Then the player receives an error event with "Game already in progress"

  Scenario: Game participant can rejoin during active game
    Given a game is in progress
    And a participant has disconnected
    When the participant reconnects and sends room:join
    Then the participant is moved from inactivePlayers to activePlayers
    And room:settings is broadcast to the room
    And room:state is broadcast to the room

  Scenario: Non-participant cannot join during finished game
    Given a room is in finished phase
    When a new player who was not a participant sends room:join
    Then the player receives an error event with "Game has ended"

  Scenario: Game participant can rejoin during finished game
    Given a room is in finished phase
    And a participant has disconnected
    When the participant reconnects and sends room:join
    Then the participant is moved from inactivePlayers to activePlayers
    And room:settings is broadcast to the room
    And room:state is broadcast to the room

  Scenario: Host joining cancels scheduled deletion
    Given a room is scheduled for deletion
    When the host sends room:join before the grace period expires
    Then the scheduled deletion is cancelled
    And the room continues to exist

  Scenario: Non-host joining does not cancel scheduled deletion
    Given a room is scheduled for deletion
    When a non-host player sends room:join before the grace period expires
    Then the scheduled deletion is not cancelled

  Scenario: Previously inactive player can rejoin during lobby
    Given a player is in inactivePlayers during lobby phase
    When the player sends room:join
    Then the player is moved from inactivePlayers to activePlayers
    And room:settings is broadcast to the room

  Scenario: Inactive player cannot rejoin full room during lobby
    Given a room in lobby phase has 20 active players
    And a player is in inactivePlayers
    When the player sends room:join
    Then the player receives an error event with "Room is full"

  # --- Room check ---

  Scenario: Room in lobby is visible to anyone
    Given a room exists in lobby phase
    When any player sends GET /api/room/{code}
    Then the response status is 200 with { exists: true }

  Scenario: Room in game is not visible to non-participants
    Given a game is in progress
    When a non-participant sends GET /api/room/{code}
    Then the response status is 403 with { error: "Game already in progress" }

  Scenario: Room in game is visible to participants
    Given a game is in progress
    When a participant sends GET /api/room/{code}
    Then the response status is 200 with { exists: true }

  Scenario: Room in finished phase is visible to participants
    Given a room is in finished phase
    When a participant sends GET /api/room/{code}
    Then the response status is 200 with { exists: true }

  Scenario: Room in finished phase is not visible to non-participants
    Given a room is in finished phase
    When a non-participant sends GET /api/room/{code}
    Then the response status is 403 with { error: "Game has ended" }

  Scenario: Non-existent room returns 404
    When any player sends GET /api/room/{code} for a non-existent room
    Then the response status is 404 with { error: "Room not found" }

  Scenario: Invalid room code format returns 400
    When any player sends GET /api/room/{code} with an invalid room code format
    Then the response status is 400 with { error: "Invalid room code" }

  # --- Departure (leave and disconnect) ---
  # Leave (room:leave) and disconnect (WebSocket close) are treated identically.
  # Both are referred to as "departure" in the following scenarios.
  # Host status is never transferred to another player because only the
  # host's device can play music via Apple Music.

  Scenario: Non-host departure during lobby
    Given a room exists in lobby phase with multiple players
    When a non-host player leaves or disconnects
    Then the player is moved from activePlayers to inactivePlayers
    And room:settings is broadcast to the room

  Scenario: Non-host departure during game
    Given a game is in playing phase
    When a non-host player leaves or disconnects
    Then the player is moved from activePlayers to inactivePlayers
    And room:settings is broadcast to the room
    And room:state is broadcast to the room

  Scenario: Non-host departure during finished phase
    Given a room is in finished phase
    When a non-host player leaves or disconnects
    Then the player is moved from activePlayers to inactivePlayers
    And room:settings is broadcast to the room
    And room:state is broadcast to the room

  Scenario: Host departure during lobby
    Given a room exists in lobby phase with the host and other players
    When the host leaves or disconnects
    Then the host is moved from activePlayers to inactivePlayers
    And the room is scheduled for deletion after 5 minutes
    And room:settings is broadcast to the room

  Scenario: Host departure during game
    Given a game is in playing phase
    When the host leaves or disconnects
    Then the host is moved from activePlayers to inactivePlayers
    And the room is scheduled for deletion after 5 minutes
    And room:settings is broadcast to the room
    And room:state is broadcast to the room

  Scenario: Host departure during finished phase
    Given a room is in finished phase with the host and other players
    When the host leaves or disconnects
    Then the host is moved from activePlayers to inactivePlayers
    And the room is scheduled for deletion after 5 minutes
    And room:settings is broadcast to the room
    And room:state is broadcast to the room

  Scenario: All players depart
    Given a room exists with players
    When all players leave or disconnect
    Then the room is scheduled for deletion after 5 minutes

  Scenario: Penalty state continues on departure
    Given a player has penalty state (pending answer, lockout, or wrong answer count)
    When the player leaves or disconnects
    Then the penalty state is preserved

  # Design: Players in inactivePlayers are not considered room members
  # for join checks. Their data is preserved only for potential rejoin.
  # Design: Joining another room removes all data including game scores
  # from the previous room. The player has abandoned that game.
  Scenario: Joining another room removes from previous room
    Given a player is in inactivePlayers of room A
    When the player joins room B
    Then the player is removed from room A's inactivePlayers
    And the player's pending answer in room A is cancelled
    And room:settings is broadcast to room A
    And room:state is broadcast to room A if roomState is not null

  # Design: Covers the case where the host disconnects before joining.
  Scenario: Newly created room is scheduled for deletion
    When a room is created via POST /api/room
    Then the room is scheduled for deletion after 5 minutes

  Scenario: Room is deleted after grace period
    Given a room is scheduled for deletion
    When 5 minutes elapse
    Then the room is deleted
    And remaining connections receive a room:closed event with { message: "Room closed due to inactivity" }
    And all sockets are forced to leave the room
