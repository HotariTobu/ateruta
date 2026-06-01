Feature: Answer submission, scoring, and penalties
  As a player
  I want to submit answers and earn points
  So that I can compete in the quiz

  # --- Answer payload ---

  Scenario: Answer includes song ID
    When a player sends game:answer
    Then the payload contains { songId }

  Scenario: Answer with empty song ID is rejected
    When a player sends game:answer with an empty songId
    Then the player receives an error event with "Song ID is required"

  Scenario: Answer with non-existent song ID is rejected
    Given a round is in progress
    When a player sends game:answer with a songId that is not in the game songs
    Then the player receives an error event with "Song not found"

  # --- Correct answers ---

  Scenario: First correct answer earns maximum points
    Given a game with rank points [4, 2, 1]
    And a round is in progress
    When a player sends game:answer with the correct song ID
    Then the player earns 4 points
    And the player is recorded as a winner
    And game:scored { winner } is broadcast to the room
    And room:state is broadcast to the room

  Scenario: Second correct answer earns second-tier points
    Given a game with rank points [4, 2, 1]
    And one player has already scored
    When another player sends game:answer with the correct song ID
    Then the player earns 2 points
    And the player is recorded as a winner

  Scenario: Third correct answer earns third-tier points
    Given a game with rank points [4, 2, 1]
    And two players have already scored
    When another player sends game:answer with the correct song ID
    Then the player earns 1 point
    And the player is recorded as a winner

  Scenario: Points are added to cumulative score
    Given a player with score 4
    When the player earns 2 points in the current round
    Then the player's total score is 6

  # --- Wrong answers ---

  Scenario: Wrong answer earns no points
    Given a round is in progress
    When a player sends game:answer with an incorrect song ID
    Then the player earns 0 points
    And the player receives game:wrong-answer with { lockoutExpiresAt }

  # --- Error cases ---

  Scenario: Answer rejected when room phase is not "playing"
    Given the room phase is "finished"
    When a player sends game:answer
    Then the player receives an error event with "Game is not in playing phase"

  Scenario: Answer rejected when round has been revealed
    Given the round has been revealed
    When a player sends game:answer
    Then the player receives an error event with "Round has been revealed"

  Scenario: Answer rejected when player already scored
    Given a player has already scored in this round
    When the same player sends game:answer again
    Then the player receives an error event with "Already scored this round"

  Scenario: Answer rejected when all scoring slots are filled
    Given a game with rank points [4, 2, 1] and 3 or more players
    And 3 players have already scored
    When another player sends game:answer with the correct song ID
    Then the player receives an error event with "Round has been revealed"

  # --- Answer rejection check order ---

  Scenario: Answer rejection check order
    Then the server checks game:answer in the following order:
      | check                         | error message                    |
      | Room phase is "playing"       | "Game is not in playing phase"   |
      | Round is not revealed         | "Round has been revealed"        |
      | Song ID is not empty          | "Song ID is required"            |
      | Song ID exists in game songs  | "Song not found"                 |
      | All scoring slots not full    | "All scoring slots are filled"   |
      | Player has not scored         | "Already scored this round"      |
      | Player has attempts remaining | "No attempts remaining"          |
      | Player is not locked out      | "Locked out"                     |

  # --- Auto-reveal ---
  # Design: Auto-reveal fires because there is no reason to wait for the
  # host when all scoring slots are filled. game:scored is not broadcast
  # for the last answer because game:reveal already includes the winners.

  Scenario: All scoring slots filled triggers auto-reveal
    Given a game with rank points [4, 2, 1] and 3 players
    And 2 players have already scored
    When the 3rd player sends game:answer with the correct song ID
    Then the player earns points and is recorded as a winner
    And game:scored is not broadcast for this answer
    And all pending answers are cancelled
    And game:reveal is broadcast to the room
    And room:state is broadcast to the room

  # Design: activePlayerCount uses only currently active (connected) players.
  # Including inactive players would block the game waiting for answers
  # from disconnected players who cannot respond.
  Scenario: Auto-reveal when all active players score with fewer active players than rank points
    Given a game with rank points [4, 2, 1] and 2 active players
    When both players send game:answer with the correct song ID
    Then game:reveal is broadcast to the room

  Scenario: After mid-round disconnect, the next correct answer can trigger auto-reveal at the reduced cap
    Given a game with rank points [4, 2, 1] and 3 active players
    And 1 player has scored
    When 1 other player disconnects
    And the remaining active player sends game:answer with the correct song ID
    Then game:reveal is broadcast to the room

  Scenario: Mid-round rejoin restores the cap
    Given a game with rank points [4, 2, 1] and 3 active players
    And 1 player is in inactivePlayers
    And 1 active player has scored
    When the inactive player rejoins
    And one of the unscored active players sends game:answer with the correct song ID
    Then game:reveal is not broadcast

  # Design: Auto-reveal is not triggered when player disconnection causes
  # all scoring slots to be filled. Adding this would couple connection
  # management with scoring logic and introduce race conditions with
  # pending answers. The host can close answers manually instead.
  Scenario: Disconnection that would fill all slots does not trigger auto-reveal
    Given a game with rank points [4, 2, 1] and 3 active players
    And 2 players have scored
    When the remaining active player disconnects
    Then game:reveal is not broadcast

  Scenario: Scored player disconnect does not retroactively fill slots
    Given a game with rank points [4, 2, 1] and 3 active players
    And player A has scored
    When player A disconnects
    Then game:reveal is not broadcast

  # --- Handicap delay ---
  # Design: Handicap allows skilled players to voluntarily add a delay,
  # giving less experienced players a better chance.

  Scenario: Answer with handicap is delayed
    Given a player with handicap 5 seconds
    When the player sends game:answer
    Then the answer is processed after a 5000ms delay

  Scenario: Handicap affects scoring order
    Given player A with handicap 0 seconds and player B with handicap 5 seconds
    When player A sends game:answer with the correct song ID
    And player B sends game:answer with the correct song ID at the same time
    Then player A's answer is processed immediately
    And player B's answer is processed after 5000ms
    And player A earns a higher scoring slot than player B

  # Design: Overwriting allows players to change their mind mid-delay.
  Scenario: New answer overwrites pending answer
    Given a player has a pending answer due to handicap delay
    When the same player sends a new game:answer
    Then the previous pending answer is cancelled
    And the new answer starts its own delay

  Scenario: Pending answer is discarded when round changes
    Given a player's answer is pending due to handicap
    When the handicap delay expires but the round number has changed
    Then the pending answer is discarded

  # Design: No notification is sent when a pending answer is cancelled.
  # The game:reveal broadcast implicitly signals the end of the round.
  Scenario: Pending answer is cancelled when host closes answers
    Given a player's answer is pending due to handicap
    When the host sends game:close-answers
    Then the pending answer is cancelled

  # --- Penalty ---

  Scenario: Wrong answer triggers lockout
    Given a game with lockout duration 5
    When a player sends game:answer with a wrong answer
    Then the player is locked out for 5 seconds
    And game:wrong-answer includes { lockoutExpiresAt }

  Scenario: Locked-out player cannot answer
    Given a player is locked out
    When the player sends game:answer
    Then the player receives an error event with "Locked out"

  Scenario: Lockout expires and player can answer again
    Given a player was locked out for 5 seconds
    When 5 seconds have elapsed
    Then the player can submit an answer

  Scenario: Wrong answer count is tracked
    Given a game with attempts limit 3
    When a player sends game:answer with 2 wrong answers
    Then the player receives game:wrong-answer

  Scenario: Player with no attempts remaining cannot answer
    Given a game with attempts limit 3
    And a player has submitted 3 wrong answers
    When the player sends game:answer
    Then the player receives an error event with "No attempts remaining"

  Scenario: Check order is attempts limit before lockout
    Given a player has exceeded the attempts limit and is also locked out
    When the player sends game:answer
    Then the error is "No attempts remaining" not "Locked out"

  Scenario: Penalties reset at the start of each round
    Given a player used all attempts in the previous round
    When a new round begins
    Then the player can answer again with full attempts

  # Design: 0 disables the lockout to support penalty-free configurations.
  Scenario: Lockout disabled when lockout duration is 0
    Given a game with lockout duration 0
    When a player sends game:answer with a wrong answer
    Then the player is not locked out
    And game:wrong-answer includes lockoutExpiresAt: null
    And the player can immediately submit another answer

  # Design: 0 means unlimited to support no-limit configurations.
  Scenario: Unlimited attempts when attempts limit is 0
    Given a game with attempts limit 0
    When a player sends game:answer 10 times with wrong answers
    Then the player can still submit another answer
    And the player receives game:wrong-answer

  # Design: Accepting answers before playback avoids blocking players
  # during the latency between the host starting playback and the server
  # processing the event.
  Scenario: Answer is accepted before song is played
    Given a round is in progress and no song has been played yet
    When a player sends game:answer
    Then the answer is processed normally

  # Design: No notification because a state change makes the previous
  # answer obviously irrelevant.
  Scenario: Game state re-checked after handicap delay
    Given a player has a pending answer due to handicap delay
    When the handicap delay expires
    Then if any rejection check would fail under the current state, the answer is silently discarded with no notification to the player

  # Design: A disconnected player's pending answer can still score because
  # the answer was submitted before disconnection. The answer rejection
  # checks do not include an "active player" condition.
  Scenario: Disconnected player's pending answer can still score
    Given a player with handicap has a pending answer with the correct song ID
    When the player disconnects before the handicap delay expires
    And the delay expires
    Then the answer is processed and the player earns points
