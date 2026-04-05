Feature: Reconnection
  As a player
  I want to reconnect to my game after disconnection
  So that I don't lose my progress

  # --- Session identification ---

  Scenario: Player is identified by session across connections
    Given a player has a player ID
    When the player disconnects and reconnects with the same session
    Then the player is recognized as the same person

  # --- State restoration ---

  Scenario: Score is restored on reconnection during game
    Given a player with score 10 disconnects during a game
    When the player reconnects
    Then the player is moved from inactivePlayers to activePlayers
    And the player's score is 10

  Scenario: Handicap is restored on reconnection during game
    Given a player with handicap 5 seconds disconnects during a game
    When the player reconnects
    Then the player is moved from inactivePlayers to activePlayers
    And the player's handicap is 5 seconds

  Scenario: Nickname is restored on reconnection
    Given a player with nickname "Alice" disconnects
    When the player reconnects to the same room
    Then the player is moved from inactivePlayers to activePlayers
    And the player's nickname is "Alice"

  Scenario: Penalty state is preserved on reconnection within same round
    Given a player disconnects during a game with penalty state
    When the player reconnects within the same round
    Then the player's wrong answer count is preserved
    And lockout and pending answer states reflect the current time

  Scenario: Penalty state is reset on reconnection after round change
    Given a player disconnects during a game with penalty state
    When the player reconnects after the round has changed
    Then all penalty state is reset

  # --- Host reconnection ---

  Scenario: Host status is restored on reconnection
    Given the host disconnects
    When the host reconnects with the same session
    Then the player is marked as host via hostPlayerId matching

  # --- State delivery on rejoin ---

  Scenario: Events are delivered in a fixed order on rejoin
    When a player rejoins a room
    Then the following events are delivered in the listed order:
      | event               | condition                                     |
      | room:settings       | always (broadcast)                             |
      | room:state          | roomState is not null (broadcast)               |
      | game:shuffled-songs | host only, if game songs exist (to host)       |
      | game:player-state   | playing phase, round not revealed (to player)  |
      | game:restore-reveal | playing phase, round revealed (to player)      |

  Scenario: Rejoining player during lobby receives settings
    Given a player reconnects during lobby phase
    Then room:settings is broadcast to the room

  Scenario: Rejoining host during lobby receives shuffled songs
    Given the host reconnects during lobby phase
    And shuffled game songs exist
    Then room:settings is broadcast to the room
    And the host receives the shuffled song IDs via game:shuffled-songs

  Scenario: Rejoining player during game receives full state
    Given a player reconnects during an active game
    Then room:settings and room:state are broadcast to the room

  Scenario: Rejoining player during revealed round receives restore-reveal
    Given a player reconnects during an active game
    And the current round has been revealed
    Then game:restore-reveal is sent to the player

  Scenario: Rejoining host during game receives full state
    Given the host reconnects during an active game
    Then room:settings and room:state are broadcast to the room
    And the host receives the shuffled game song IDs via game:shuffled-songs

  Scenario: Rejoining player during finished phase receives state
    Given a player reconnects during finished phase
    Then room:settings and room:state are broadcast to the room

  # --- Personal round state ---

  Scenario: Rejoining player receives personal round state
    Given a player reconnects during an active game
    And the current round has not been revealed
    Then game:player-state is sent to the player

  # --- Access control ---

  Scenario: Non-participant cannot rejoin during game
    Given a game is in progress
    When a player who was not in the lobby sends room:join
    Then the player receives an error event with "Game already in progress"
