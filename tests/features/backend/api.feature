Feature: API type definitions
  Defines the payload types for HTTP endpoints, C→S events, and S→C events.

  # --- Shared types ---

  Scenario: Song type
    Then a Song has the following fields:
      | field      | type            |
      | id         | string          |
      | title      | string          |
      | artist     | string          |
      | artworkUrl | string \| null  |

  Scenario: Winner type
    Then a Winner has the following fields:
      | field    | type   |
      | playerId | string |
      | rankIndex | number (0-indexed) |

  # --- WebSocket ---

  Scenario: WebSocket endpoint
    Then the WebSocket endpoint is /ws
    And the connection uses the ateruta-player-id cookie for session identification

  Scenario: WebSocket close codes
    Then the following custom close codes are used:
      | code | meaning                        |
      | 4409 | Connected from another location |

  Scenario: WebSocket message envelope
    Then all WebSocket messages use JSON with the following structure:
      | field   | type   |
      | event   | string |
      | payload | object |
    And the event field is the event name (e.g. "room:join", "game:answer")
    And the payload field contains the event-specific data

  # --- HTTP request/response types ---

  Scenario: POST /api/room response
    Then 201 response has the following fields:
      | field | type   |
      | code  | string |
    And 401 response has the following fields:
      | field | type   |
      | error | string |
    And 500 response has the following fields:
      | field | type   |
      | error | string |

  Scenario: GET /api/room/{code} response
    Then 200 response has the following fields:
      | field  | type |
      | exists | true |
    And 400 response has the following fields:
      | field | type   |
      | error | string |
    And 401 response has the following fields:
      | field | type   |
      | error | string |
    And 403 response has the following fields:
      | field | type   |
      | error | string |
    And 404 response has the following fields:
      | field | type   |
      | error | string |

  Scenario: GET /api/session response
    Then 200 response has the following fields:
      | field | type |
      | ready | true |

  Scenario: GET /api/token response
    Then 200 response has the following fields:
      | field     | type   |
      | token     | string                    |
      | expiresAt | string (ISO 8601 with TZ) |
    And 500 response has the following fields:
      | field | type   |
      | error | string |

  # --- C→S event payloads ---

  Scenario: room:join payload
    Then the payload has the following fields:
      | field | type   |
      | code  | string |

  Scenario: room:leave payload
    Then the payload is empty

  Scenario: room:nickname payload
    Then the payload has the following fields:
      | field    | type   |
      | nickname | string |

  Scenario: room:handicap payload
    Then the payload has the following fields:
      | field    | type             |
      | handicap | number (seconds) |

  Scenario: room:settings payload (C→S)
    Then the payload is a partial object with optional fields:
      | field                 | type               |
      | songs                 | Song[]             |
      | totalRounds           | number             |
      | playbackDurations         | number[] (seconds) |
      | rankPoints         | number[]           |
      | lockoutDuration | number             |
      | attemptsLimit    | number             |

  Scenario: game:start payload
    Then the payload is empty

  Scenario: game:play-song payload (C→S)
    Then the payload is empty

  Scenario: game:answer payload
    Then the payload has the following fields:
      | field  | type   |
      | songId | string |

  Scenario: game:extend payload (C→S)
    Then the payload is empty

  Scenario: game:close-answers payload
    Then the payload is empty

  Scenario: game:next-round payload
    Then the payload is empty

  Scenario: game:end payload
    Then the payload is empty

  Scenario: game:back-to-lobby payload
    Then the payload is empty

  # --- S→C event payloads ---

  Scenario: room:settings payload (S→C)
    Then the payload has the following fields:
      | field                 | type                                            |
      | hostPlayerId          | string                                          |
      | songs                 | Song[]                                                       |
      | totalRounds           | number \| null                                  |
      | playbackDurations         | number[] (seconds)                                           |
      | rankPoints         | number[]                                                     |
      | lockoutDuration        | number \| null                                              |
      | attemptsLimit    | number \| null                                              |
      | activePlayers         | { id: string, nickname: string, handicap: number (seconds) }[] |
      | inactivePlayers       | { id: string, nickname: string, handicap: number (seconds) }[] |

  Scenario: room:state payload (S→C)
    Then the payload is RoomState | null
    And RoomState has the following fields:
      | field              | type                                |
      | phase              | "playing" \| "finished" |
      | currentRound       | number                              |
      | playbackDurationIndex  | number                              |
      | activePlayers      | { id: string, score: number }[]     |
      | inactivePlayers    | { id: string, score: number }[]     |

  Scenario: error event payload
    Then the event name is "error"
    And the payload has the following fields:
      | field   | type                  |
      | message | string                |
      | details | string[] \| undefined |

  Scenario: game:shuffled-songs payload
    Then the payload has the following fields:
      | field          | type     |
      | shuffledSongIds | string[] |

  Scenario: game:play-song payload (S→C)
    Then the payload is empty

  Scenario: game:scored payload
    Then the payload has the following fields:
      | field  | type   |
      | winner | Winner |

  Scenario: game:wrong-answer payload
    Then the payload has the following fields:
      | field             | type            | description                                        |
      | lockoutExpiresAt  | string \| null  | ISO 8601 with TZ, null if no lockout               |

  Scenario: game:reveal payload
    Then the payload has the following fields:
      | field   | type     |
      | songId  | string   |
      | winners | Winner[] |

  Scenario: game:player-state payload
    Then the payload has the following fields:
      | field            | type           |
      | scored           | boolean        |
      | scoredRankIndex  | number \| null |
      | wrongAnswerCount | number         |
      | lockoutExpiresAt | string \| null |
      | pendingSongId    | string \| null |
      | pendingExpiresAt | string \| null |
    And scored is true if and only if scoredRankIndex is not null

  # Design: game:restore-reveal is behaviorally identical to game:reveal.
  # They are separate events so that each event has exactly one send-target
  # type: game:reveal is broadcast, game:restore-reveal is sent to an individual.
  Scenario: game:restore-reveal payload
    Then the payload has the following fields:
      | field   | type     |
      | songId  | string   |
      | winners | Winner[] |

  Scenario: room:closed payload
    Then the payload has the following fields:
      | field   | type   |
      | message | string |
