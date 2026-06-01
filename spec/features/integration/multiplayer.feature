Feature: Multiplayer interactions
  As multiple players in the same room
  We want to interact concurrently
  So that the game works correctly with real-time communication

  # --- Room joining errors ---
  # Error messages mirror GET /api/room/{code} responses in room.feature

  Scenario: Non-existent room code shows error
    When a player enters a room code that does not exist
    Then an error is displayed

  Scenario: Room code for game in progress shows error
    Given a room has a game in progress
    When a non-participant enters the room code
    Then an error is displayed

  Scenario: Room code for finished game shows error
    Given a room's game has finished
    When a non-participant enters the room code
    Then an error is displayed

  Scenario: Full room shows error
    Given a room has reached the maximum number of players
    When another player tries to join
    Then an error is displayed indicating the room is full

  # --- Lobby ---

  Scenario: Multiple players join a room
    Given a host creates a room
    When 5 players join the room using the room code
    Then all 6 players appear in the player list
    And each player has a unique auto-assigned nickname

  Scenario: Nickname and handicap changes are visible to all players
    Given a room with 3 players
    When a player changes their nickname
    Then all other players see the updated nickname in the player list
    When a player sets their handicap to 5 seconds
    Then all other players see the handicap badge next to that player's name

  Scenario: Host's settings changes are visible to non-host players
    Given a room with a host and 2 other players
    When the host changes the rank points to "4, 2" and playback durations to "1, 2, 4"
    Then non-host players see the updated rank points and playback duration values

  # --- Game ---

  Scenario: Concurrent answers are scored in order
    Given a game is in progress with 4 players and no handicaps
    When player A submits the correct answer
    And player B submits the correct answer after player A
    Then player A earns 1st place points
    And player B earns 2nd place points

  Scenario: Wrong answer with penalty does not affect other players
    Given a game is in progress with 3 players
    When player A submits a wrong answer
    Then player A is locked out
    And player B and player C can still submit answers

  Scenario: Handicap delays answer processing
    Given players have configured their handicaps in the lobby
    And player A has handicap of 5 seconds
    And player B has handicap of 0 seconds
    And a game is in progress
    When both players submit the correct answer at the same time
    Then player B scores before player A

  Scenario: All scoring slots filled triggers auto-reveal
    Given a game with rank points "4, 2, 1" and 5 players
    When 3 players submit correct answers
    Then the song is automatically revealed
    And the remaining players cannot score

  # --- Lifecycle ---

  Scenario: Player leaves during game
    Given a game is in progress with 3 players
    When a non-host player disconnects
    Then the game continues with the remaining players

  Scenario: Disconnected player's score shown in results
    Given a game is in progress with 3 players
    And player A has earned points
    When player A disconnects
    And the host ends the game
    Then the result screen shows player A's score
