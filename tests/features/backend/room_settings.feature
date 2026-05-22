Feature: Room settings
  As a player
  I want to configure room settings, nicknames, and handicaps
  So that the game is customized to our preferences

  # --- Settings ---

  Scenario: room:settings check order
    Then the server checks room:settings in the following order:
      | check              | error message                        |
      | Sender is host     | "Only the host can change settings"  |
      | Room is in lobby   | "Can only change settings in lobby"  |
      | Payload has fields | "Settings payload must not be empty" |
      | Field validations  | "Settings validation failed"         |

  Scenario: room:settings field validation is batched and atomic
    When the host sends room:settings with multiple fields that fail validation
    Then field validations are applied to each field present in the payload
    And all field validation errors are collected in a single error event with message "Settings validation failed" and individual errors in details
    And no fields in the payload are applied

  Scenario: Empty settings payload is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with no fields
    Then the host receives an error event with "Settings payload must not be empty"

  Scenario: Host updates settings with partial data
    Given a room exists in lobby phase
    When the host sends room:settings with partial settings
    Then the settings are partially merged
    And room:settings is broadcast to the room

  Scenario: Settings cannot be changed outside lobby
    Given a room is not in lobby phase
    When the host sends room:settings
    Then the settings are not changed
    And the host receives an error event with "Can only change settings in lobby"

  Scenario: Non-host cannot update settings
    When a non-host player tries to update settings
    Then the player receives an error event with "Only the host can change settings"

  # --- Nickname ---

  Scenario: room:nickname check order
    Then the server checks room:nickname in the following order:
      | check                              | error message                            |
      | Room is in lobby                   | "Can only change nickname in lobby"      |
      | Nickname is not empty              | "Nickname is required"                   |
      | Nickname is 20 characters or less  | "Nickname must be 20 characters or less" |
    And the nickname is sanitized and trimmed before validation

  Scenario: Players get auto-assigned nicknames
    Given player A has created a room
    When player A sends room:join
    And player B sends room:join
    And player C sends room:join
    Then player A's nickname is "Player 1"
    And player B's nickname is "Player 2"
    And player C's nickname is "Player 3"

  # Design: Numbers are never reused to keep the implementation simple.
  Scenario: Auto-assigned nickname uses global counter
    Given Player 1, Player 2, and Player 3 have joined the room
    And Player 2 has left the room
    When a new player joins the room
    Then the new player's nickname is "Player 4"

  Scenario: Player changes nickname
    Given a player is in a room
    When the player sends room:nickname with "Alice"
    Then the player's nickname is "Alice"
    And room:settings is broadcast to the room

  Scenario: Nickname is trimmed before processing
    Given a player is in a room
    When the player sends room:nickname with "  Alice  "
    Then the player's nickname is "Alice"

  # Design: Sanitization prevents display issues from invisible characters.
  Scenario: Nickname control characters are stripped before processing
    Given a player is in a room
    When the player sends room:nickname containing control characters (Unicode category Cc)
    Then the control characters are removed
    And the result is trimmed and then validated

  Scenario: Nickname with only control characters is rejected
    Given a player is in a room
    When the player sends room:nickname containing only control characters
    Then the player receives an error event with "Nickname is required"

  Scenario: Nickname cannot be changed outside lobby
    Given a room is not in lobby phase
    When a player sends room:nickname
    Then the player receives an error event with "Can only change nickname in lobby"

  Scenario: Empty nickname is rejected
    Given a player is in a room
    When the player sends room:nickname with ""
    Then the player receives an error event with "Nickname is required"

  Scenario: Whitespace-only nickname is rejected
    Given a player is in a room
    When the player sends room:nickname with "   "
    Then the player receives an error event with "Nickname is required"

  Scenario: Nickname exceeding 20 characters is rejected
    Given a player is in a room
    When the player sends room:nickname with a 21-character string
    Then the player receives an error event with "Nickname must be 20 characters or less"

  Scenario: Nickname is preserved across reconnection
    Given a player with nickname "Alice" is in the room
    When the player disconnects
    And the player rejoins
    Then the player's nickname is "Alice"

  # Design: Allowed deliberately—"which Tom was that?" confusion is
  # part of the fun.
  Scenario: Duplicate nicknames are allowed
    Given a player has nickname "Alice"
    When another player sends room:nickname with "Alice"
    Then the nickname is accepted
    And room:settings is broadcast to the room

  # --- Handicap ---

  Scenario: room:handicap check order
    Then the server checks room:handicap in the following order:
      | check                        | error message                              |
      | Room is in lobby             | "Can only change handicap in lobby"        |
      | Handicap is between 0 and 30 | "Handicap must be between 0 and 30 seconds" |

  Scenario: Player sets handicap in lobby
    Given a player is in a room in lobby phase
    When the player sends room:handicap with 5
    Then the player's handicap is 5 seconds
    And room:settings is broadcast to the room

  Scenario: Handicap supports decimal values
    Given a player is in a room in lobby phase
    When the player sends room:handicap with 5.3
    Then the player's handicap is 5.3 seconds

  Scenario: Handicap cannot be changed outside lobby
    Given a room is not in lobby phase
    When a player sends room:handicap
    Then the player receives an error event with "Can only change handicap in lobby"

  Scenario: Handicap above 30 seconds is rejected
    Given a player is in a room in lobby phase
    When the player sends room:handicap with 31
    Then the player receives an error event with "Handicap must be between 0 and 30 seconds"

  Scenario: Negative handicap is rejected
    Given a player is in a room in lobby phase
    When the player sends room:handicap with -1
    Then the player receives an error event with "Handicap must be between 0 and 30 seconds"

  Scenario: Handicap of exactly 30 seconds is valid
    Given a player is in a room in lobby phase
    When the player sends room:handicap with 30
    Then the player's handicap is 30 seconds

  Scenario: Handicap of 0 means no delay
    Given a player with handicap 0 seconds is in a game
    When the player sends game:answer
    Then the answer is processed immediately

  Scenario: Handicap is preserved across reconnection
    Given a player with handicap 10 seconds is in a game
    When the player disconnects
    And the player rejoins
    Then the player's handicap is 10 seconds

  # --- Songs validation ---

  Scenario: Songs exceeding 1000 are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with more than 1000 songs
    Then the host receives an error event with "Songs must not exceed 1000"

  Scenario: Song with empty ID is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with a song that has an empty ID
    Then the host receives an error event with "Song ID is required"

  Scenario: Song with empty title is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with a song that has an empty title
    Then the host receives an error event with "Song title is required"

  Scenario: Song with empty artist is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with a song that has an empty artist
    Then the host receives an error event with "Song artist is required"

  Scenario: Duplicate song IDs are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with songs containing duplicate IDs
    Then the host receives an error event with "Duplicate song IDs are not allowed"

  Scenario: Song with empty artwork URL is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with a song that has an empty artworkUrl
    Then the host receives an error event with "Song artwork URL must not be empty"

  # --- Playback durations validation ---

  Scenario: Empty playback durations are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with playbackDurations []
    Then the host receives an error event with "Playback durations are required"

  Scenario: Playback durations exceeding 10 entries are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with 11 playback durations
    Then the host receives an error event with "Playback durations must not exceed 10 entries"

  Scenario: Playback durations with zero values are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with playbackDurations [0, 2, 4]
    Then the host receives an error event with "Playback durations must contain only positive numbers"

  Scenario: Playback durations with negative values are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with playbackDurations [-1, 2, 4]
    Then the host receives an error event with "Playback durations must contain only positive numbers"

  Scenario: Playback durations support decimal values
    Given a room exists in lobby phase
    When the host sends room:settings with playbackDurations [0.5, 1, 2, 4]
    Then the settings are partially merged
    And room:settings is broadcast to the room

  # Design: Ascending order is enforced because extending to a shorter
  # duration than the previous one serves no purpose.
  Scenario: Playback durations not in ascending order are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with playbackDurations [4, 2, 8]
    Then the host receives an error event with "Playback durations must be in ascending order"

  Scenario: Playback durations with duplicate values are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with playbackDurations [1, 2, 2, 4]
    Then the host receives an error event with "Playback durations must be in ascending order"

  Scenario: Playback durations with values exceeding 300 seconds are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with playbackDurations [1, 2, 301]
    Then the host receives an error event with "Playback durations must not exceed 300 seconds each"

  # --- Rank points validation ---

  Scenario: Empty rank points are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with rankPoints []
    Then the host receives an error event with "Rank points are required"

  Scenario: Rank points exceeding 10 entries are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with 11 rank points
    Then the host receives an error event with "Rank points must not exceed 10 entries"

  Scenario: Rank points with non-positive values are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with rankPoints [4, 0, -1]
    Then the host receives an error event with "Rank points must contain only positive numbers"

  Scenario: Non-integer rank points are rejected
    Given a room exists in lobby phase
    When the host sends room:settings with rankPoints [4, 1.5, 1]
    Then the host receives an error event with "Rank points must contain only integers"

  # Design: Any order is accepted to support configurations where later
  # correct answers earn more points (e.g. [1, 2, 4]).
  Scenario: Rank points in any order are accepted
    Given a room exists in lobby phase
    When the host sends room:settings with rankPoints [1, 2, 4]
    Then the settings are partially merged
    And room:settings is broadcast to the room

  # --- Lockout duration validation ---

  Scenario: Negative lockout duration is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with lockoutDuration -1
    Then the host receives an error event with "Lockout duration must be between 0 and 30 seconds"

  Scenario: Lockout duration above 30 seconds is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with lockoutDuration 31
    Then the host receives an error event with "Lockout duration must be between 0 and 30 seconds"

  Scenario: Lockout duration of exactly 30 seconds is valid
    Given a room exists in lobby phase
    When the host sends room:settings with lockoutDuration 30
    Then the settings are partially merged
    And room:settings is broadcast to the room

  Scenario: Lockout duration supports decimal values
    Given a room exists in lobby phase
    When the host sends room:settings with lockoutDuration 2.5
    Then the settings are partially merged
    And room:settings is broadcast to the room

  # --- Attempts limit validation ---

  Scenario: Negative attempts limit is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with attemptsLimit -1
    Then the host receives an error event with "Attempts limit must be between 0 and 10"

  Scenario: Attempts limit above 10 is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with attemptsLimit 11
    Then the host receives an error event with "Attempts limit must be between 0 and 10"

  Scenario: Attempts limit of exactly 10 is valid
    Given a room exists in lobby phase
    When the host sends room:settings with attemptsLimit 10
    Then the settings are partially merged
    And room:settings is broadcast to the room

  Scenario: Non-integer attempts limit is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with attemptsLimit 2.5
    Then the host receives an error event with "Attempts limit must be an integer"

  # --- Total rounds validation ---

  Scenario: Total rounds of 0 is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with totalRounds 0
    Then the host receives an error event with "Total rounds must be at least 1"

  Scenario: Negative total rounds is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with totalRounds -1
    Then the host receives an error event with "Total rounds must be at least 1"

  Scenario: Non-integer total rounds is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with totalRounds 2.5
    Then the host receives an error event with "Total rounds must be an integer"

  # Design: The upper bound is derived from the maximum song count (see "Songs
  # exceeding 1000 are rejected"). Both limits must reference the same value.
  Scenario: Total rounds exceeding the songs limit is rejected
    Given a room exists in lobby phase
    When the host sends room:settings with totalRounds greater than the maximum song count
    Then the host receives an error event with "Total rounds must not exceed 1000"

  # Design: The server does not auto-adjust to keep host-configurable
  # settings flowing exclusively in the client-to-server direction.
  Scenario: Sending songs does not auto-adjust total rounds
    Given a room in lobby phase with total rounds set to 10
    When the host sends room:settings with 5 songs
    Then totalRounds remains 10
