Feature: Game lifecycle
  As a host
  I want to control the game flow
  So that players can play music quiz rounds

  # --- Song management ---
  # Design: Songs are shuffled to hide the play order from non-host
  # players. The host receives shuffled IDs for local playback only;
  # they are never shown in the UI.

  Scenario: Host sends songs via settings
    Given a room in lobby phase
    When the host sends songs via room:settings
    Then the songs are stored in settings
    And room:settings is broadcast to the room
    And the songs are shuffled and stored as game songs
    And the host receives the shuffled song IDs via game:shuffled-songs

  Scenario: Each round uses the corresponding shuffled song
    Given songs have been shuffled into game songs
    Then round 1 uses the 1st shuffled song, round 2 uses the 2nd, and so on

  # --- Game start ---

  # Design: Solo play (host only) is allowed for practice purposes.
  Scenario: Host starts game
    Given a room in lobby phase with valid settings
    When the host sends game:start
    Then a new roomState is created:
      | field             | value                                   |
      | phase             | "playing"                               |
      | currentRound      | 1                                       |
      | playbackDurationIndex | 0                                       |
      | activePlayers     | [{ id, score: 0 } for each participant] |
      | inactivePlayers   | []                                      |
    And game participants are the activePlayers in settings at the time of game:start
    And players in inactivePlayers at game start are not game participants
    And room:state is broadcast to the room

  Scenario: Inactive non-participants are removed on game start
    Given some players are in inactivePlayers in settings at the time of game:start
    When the host sends game:start, before room:state is broadcast
    Then those players are removed from inactivePlayers in settings
    And room:settings is broadcast to the room

  Scenario: Non-host cannot start game
    When a non-host player sends game:start
    Then the player receives an error event with "Only the host can start the game"

  Scenario: Game cannot start without songs
    Given a room in lobby phase with no songs
    When the host sends game:start
    Then the game does not start
    And the host receives an error event with "Songs are required to start the game"

  Scenario: Game cannot start without total rounds
    Given a room in lobby phase with no total rounds
    When the host sends game:start
    Then the game does not start
    And the host receives an error event with "Total rounds are required"

  Scenario: Game cannot start with too many rounds
    Given a room in lobby phase with 3 songs and total rounds set to 5
    When the host sends game:start
    Then the game does not start
    And the host receives an error event with "Not enough songs for the specified number of rounds"

  Scenario: Game cannot start without rank points
    Given a room in lobby phase with empty rank points
    When the host sends game:start
    Then the game does not start
    And the host receives an error event with "Rank points are required"

  Scenario: Game cannot start without playback durations
    Given a room in lobby phase with empty playback durations
    When the host sends game:start
    Then the game does not start
    And the host receives an error event with "Playback durations are required"

  Scenario: Game cannot start without lockout duration
    Given a room in lobby phase with no lockout duration
    When the host sends game:start
    Then the game does not start
    And the host receives an error event with "Lockout duration is required"

  Scenario: Game cannot start without attempts limit
    Given a room in lobby phase with no attempts limit
    When the host sends game:start
    Then the game does not start
    And the host receives an error event with "Attempts limit is required"

  Scenario: Game cannot start outside lobby
    Given a room is not in lobby phase
    When the host sends game:start
    Then the host receives an error event with "Can only start game in lobby"

  # --- Host-only action check order ---

  Scenario: game:start check order
    Then the server checks game:start in the following order:
      | check                         | error message                                         |
      | Sender is host                | "Only the host can start the game"                    |
      | Room is in lobby phase        | "Can only start game in lobby"                        |
      | Songs exist                   | "Songs are required to start the game"                |
      | Total rounds exist            | "Total rounds are required"                           |
      | Enough songs for total rounds | "Not enough songs for the specified number of rounds" |
      | Rank points exist             | "Rank points are required"                            |
      | Playback durations exist      | "Playback durations are required"                     |
      | Lockout duration exists       | "Lockout duration is required"                        |
      | Attempts limit exists         | "Attempts limit is required"                          |

  Scenario: game:extend check order
    Then the server checks game:extend in the following order:
      | check                   | error message                       |
      | Sender is host          | "Only the host can extend duration" |
      | Room phase is playing   | "Game is not in playing phase"      |
      | Round is not revealed   | "Round has already been revealed"   |
      | Not at maximum duration | "Already at maximum duration"       |

  Scenario: game:next-round check order
    Then the server checks game:next-round in the following order:
      | check                  | error message                      |
      | Sender is host         | "Only the host can advance rounds" |
      | Room phase is playing  | "Game is not in playing phase"     |
      | Round is revealed      | "Round has not been revealed"      |
      | Rounds remaining       | "All rounds have been played"      |

  Scenario: game:close-answers check order
    Then the server checks game:close-answers in the following order:
      | check                  | error message                      |
      | Sender is host         | "Only the host can close answers"  |
      | Room phase is playing  | "Game is not in playing phase"     |
      | Round is not revealed  | "Round has already been revealed"  |
      | Song has been played   | "Song has not been played yet"     |

  Scenario: game:play-song check order
    Then the server checks game:play-song in the following order:
      | check                  | error message                      |
      | Sender is host         | "Only the host can play songs"     |
      | Room phase is playing  | "Game is not in playing phase"     |
      | Round is not revealed  | "Round has already been revealed"  |

  Scenario: game:end check order
    Then the server checks game:end in the following order:
      | check                  | error message                      |
      | Sender is host         | "Only the host can end the game"   |
      | Room phase is playing  | "Game is not in playing phase"     |

  Scenario: game:back-to-lobby check order
    Then the server checks game:back-to-lobby in the following order:
      | check                  | error message                       |
      | Sender is host         | "Only the host can return to lobby" |
      | Room phase is finished | "Game has not finished"             |

  # --- Round start ---

  Scenario: New round initializes round state
    When a new round begins
    Then playbackDurationIndex is reset to 0
    And the round starts as not revealed
    And no song has been played for the new round
    And all pending answers are cancelled
    And penalties are reset for all players (including inactive players)

  # --- Song playback ---

  Scenario: Host triggers song playback
    Given a round is in progress
    When the host sends game:play-song
    Then game:play-song is broadcast to the room

  Scenario: Non-host cannot trigger song playback
    When a non-host player sends game:play-song
    Then the player receives an error event with "Only the host can play songs"

  Scenario: Song playback rejected outside playing phase
    Given the room phase is "finished"
    When the host sends game:play-song
    Then the host receives an error event with "Game is not in playing phase"

  Scenario: Song playback rejected after reveal
    Given the round has already been revealed
    When the host sends game:play-song
    Then the host receives an error event with "Round has already been revealed"

  # --- Duration extension ---

  Scenario: Host extends duration
    Given a round is in progress at playback duration index 0
    And the playback durations are [1, 2, 4, 8, 16]
    When the host sends game:extend
    Then playbackDurationIndex advances to 1
    And room:state is broadcast to the room

  Scenario: Extension at maximum duration is rejected
    Given a round is in progress at the last playback duration index
    When the host sends game:extend
    Then the host receives an error event with "Already at maximum duration"

  Scenario: Non-host cannot extend duration
    When a non-host player sends game:extend
    Then the player receives an error event with "Only the host can extend duration"

  Scenario: Extension rejected outside playing phase
    Given the room phase is "finished"
    When the host sends game:extend
    Then the host receives an error event with "Game is not in playing phase"

  Scenario: Extension rejected after reveal
    Given the round has already been revealed
    When the host sends game:extend
    Then the host receives an error event with "Round has already been revealed"

  # Design: Extending before playback is intentional—the host may want to
  # adjust the duration before playing the song.
  Scenario: Extend is allowed before song is played
    Given a round is in progress and no song has been played
    When the host sends game:extend
    Then playbackDurationIndex advances
    And room:state is broadcast to the room

  # --- Close answers ---

  Scenario: Host closes answers and reveals song
    Given a round is in progress
    When the host sends game:close-answers
    Then all pending answers are cancelled
    And game:reveal { songId, winners } is broadcast to the room
    And room:state is broadcast to the room

  Scenario: Non-host cannot close answers
    When a non-host player sends game:close-answers
    Then the player receives an error event with "Only the host can close answers"

  Scenario: Close answers rejected outside playing phase
    Given the room phase is "finished"
    When the host sends game:close-answers
    Then the host receives an error event with "Game is not in playing phase"

  Scenario: Close answers rejected when already revealed
    Given the round has already been revealed
    When the host sends game:close-answers
    Then the host receives an error event with "Round has already been revealed"

  Scenario: Close answers rejected before song is played
    Given a round is in progress and no song has been played
    When the host sends game:close-answers
    Then the host receives an error event with "Song has not been played yet"

  # --- Next round ---

  Scenario: Host advances to next round
    Given the current round has been revealed
    And more rounds are available
    When the host sends game:next-round
    Then the next round begins
    And room:state is broadcast to the room

  Scenario: Non-host cannot advance to next round
    When a non-host player sends game:next-round
    Then the player receives an error event with "Only the host can advance rounds"

  Scenario: Next round rejected outside playing phase
    Given the room phase is "finished"
    When the host sends game:next-round
    Then the host receives an error event with "Game is not in playing phase"

  Scenario: Next round rejected before reveal
    Given a round is in progress and has not been revealed
    When the host sends game:next-round
    Then the host receives an error event with "Round has not been revealed"

  # --- Game end ---

  Scenario: All rounds completed rejects next round
    Given a game with total rounds set to 3
    And 3 rounds have been played
    When the host sends game:next-round
    Then the host receives an error event with "All rounds have been played"

  # Design: Game songs are deleted but settings songs are preserved so
  # the host can replay with the same playlist without reselecting it.
  Scenario: Host ends game
    Given a room is in playing phase
    When the host sends game:end
    Then the room phase changes to "finished"
    And all pending answers are cancelled
    And penalties are reset for all players (including inactive players)
    And game songs are deleted but songs in settings are preserved
    And room:state is broadcast to the room

  Scenario: Non-host cannot end game
    When a non-host player sends game:end
    Then the player receives an error event with "Only the host can end the game"

  Scenario: End game rejected when no game in progress
    Given a room is in lobby phase
    When the host sends game:end
    Then the host receives an error event with "Game is not in playing phase"

  Scenario: End game rejected when game has already finished
    Given a room is in finished phase
    When the host sends game:end
    Then the host receives an error event with "Game is not in playing phase"

  # --- Back to lobby ---

  Scenario: Non-host cannot return to lobby
    When a non-host player sends game:back-to-lobby
    Then the player receives an error event with "Only the host can return to lobby"

  Scenario: Back to lobby rejected when game has not finished
    Given a game is in progress
    When the host sends game:back-to-lobby
    Then the host receives an error event with "Game has not finished"

  # Design: Songs are reshuffled to prevent the same play order on replay.
  Scenario: Host returns to lobby after game
    Given the game has finished
    When the host sends game:back-to-lobby
    Then songs in settings are reshuffled into game songs
    And the host receives the reshuffled song IDs via game:shuffled-songs
    And activePlayers and inactivePlayers in settings are preserved
    And the roomState is destroyed
    And room:state is broadcast to the room
