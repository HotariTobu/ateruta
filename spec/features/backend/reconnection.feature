Feature: Reconnection
  As a player
  I want to reconnect to my game after disconnection
  So that I don't lose my progress

  # --- Session identification ---

  Scenario: Player is identified by session across connections
    Given a player has a player ID
    When the player disconnects
    And the player reconnects with the same session
    Then the player is recognized as the same person

  # --- State restoration ---

  Scenario: Score is restored on reconnection during game
    Given a player with score 10 is in inactivePlayers during a game
    When the player rejoins the room
    Then the player is moved from inactivePlayers to activePlayers
    And the player's score is 10

  Scenario: Handicap is restored on reconnection during game
    Given a player with handicap 5 seconds is in inactivePlayers during a game
    When the player rejoins the room
    Then the player is moved from inactivePlayers to activePlayers
    And the player's handicap is 5 seconds

  Scenario: Nickname is restored on reconnection
    Given a player with nickname "Alice" is in inactivePlayers
    When the player rejoins the room
    Then the player is moved from inactivePlayers to activePlayers
    And the player's nickname is "Alice"

  Scenario: Penalty state is preserved on reconnection within same round
    Given a game is in progress
    And a player has acquired penalty state
    When the player disconnects
    And the player rejoins within the same round
    Then the player's wrong answer count is preserved
    And the original lockoutExpiresAt and pendingExpiresAt are preserved

  Scenario: Penalty state is reset on reconnection after round change
    Given a game is in progress
    And a player has acquired penalty state
    When the player disconnects
    And the player rejoins after the round has changed
    Then all penalty state is reset

  # --- Host reconnection ---

  Scenario: Host status is restored on reconnection
    Given the host is in inactivePlayers
    When the host rejoins the room with the same session
    Then the player is the host

  # --- State delivery on rejoin ---

  Scenario: Rejoining player during lobby receives settings
    Given a room is in lobby phase
    And a player is in inactivePlayers
    When the player rejoins the room
    Then room:settings is broadcast to the room

  Scenario: Rejoining host during lobby receives shuffled songs
    Given a room is in lobby phase
    And the host is in inactivePlayers
    And shuffled game songs exist
    When the host rejoins the room
    Then room:settings is broadcast to the room
    And the host receives the shuffled song IDs via game:shuffled-songs

  Scenario: Rejoining player during game receives full state
    Given a game is in progress
    And a player is in inactivePlayers
    When the player rejoins the room
    Then room:settings is broadcast to the room
    And room:state is broadcast to the room

  Scenario: Rejoining player during revealed round receives restore-reveal
    Given a game is in progress
    And the current round has been revealed
    And a player is in inactivePlayers
    When the player rejoins the room
    Then game:restore-reveal is sent to the player

  Scenario: Rejoining host during game receives full state
    Given a game is in progress
    And the current round has not been revealed
    And the host is in inactivePlayers
    When the host rejoins the room
    Then room:settings is broadcast to the room
    And room:state is broadcast to the room
    And the host receives the shuffled game song IDs via game:shuffled-songs
    And game:player-state is sent to the host

  Scenario: Rejoining host during revealed round receives full state
    Given a game is in progress
    And the current round has been revealed
    And the host is in inactivePlayers
    When the host rejoins the room
    Then room:settings is broadcast to the room
    And room:state is broadcast to the room
    And the host receives the shuffled game song IDs via game:shuffled-songs
    And game:restore-reveal is sent to the host

  Scenario: Rejoining player during finished phase receives state
    Given a room is in finished phase
    And a player is in inactivePlayers
    When the player rejoins the room
    Then room:settings is broadcast to the room
    And room:state is broadcast to the room

  # --- Personal round state ---

  Scenario: Rejoining player receives personal round state
    Given a game is in progress
    And the current round has not been revealed
    And a player is in inactivePlayers
    When the player rejoins the room
    Then game:player-state is sent to the player

  # --- Access control ---

  Scenario: Non-participant cannot rejoin during game
    Given a game is in progress
    When a player who was not in the lobby sends room:join
    Then the player receives an error event with "Game already in progress"
