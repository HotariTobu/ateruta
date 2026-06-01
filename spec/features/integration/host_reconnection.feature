Feature: Host reconnection
  As a host
  I want the game to handle my disconnection gracefully
  So that the game can resume when I return

  Scenario: Game continues when host disconnects during play
    Given a game is in progress with a host and 2 players
    When the host disconnects
    Then the game remains in playing phase
    And other players can still submit answers
    And a banner displays "The host has disconnected. Waiting for reconnection..."

  Scenario: Host reconnects during game
    Given a game is in progress
    And the host has disconnected
    When the host reconnects
    Then the host can resume controlling the game
    And the host's score, handicap, and nickname are restored
    And the banner is dismissed

  Scenario: Room is deleted when host does not return
    Given the host has disconnected
    When the grace period expires without the host returning
    Then the room is deleted
    And the room closure message is displayed as a toast to all remaining players

  Scenario: Non-host player reconnects during game
    Given a game is in progress
    When a non-host player disconnects
    And the non-host player reconnects
    Then the player's score, handicap, and nickname are preserved

  Scenario: Player reconnects during finished phase
    Given a game has finished with 3 players
    And a player has disconnected from the result screen
    When the player reconnects
    Then the player sees the result screen with all scores preserved

  Scenario: Host reconnects during finished phase
    Given a game has finished with 3 players
    And the host has disconnected from the result screen
    When the host reconnects
    Then the host sees the result screen with all scores preserved
    And the host can return to lobby

  Scenario: Host reconnects during lobby
    Given a room is in lobby phase
    And the host has disconnected
    And another player is still in the room
    When the host reconnects
    Then the host is shown as the host in the player list
    And all players remain in the lobby
