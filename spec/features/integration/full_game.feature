Feature: Full game flow
  As a group of players
  We want to play a complete music quiz game
  So that we can enjoy competing together

  Scenario: Complete game from room creation to results
    # Setup
    Given a host creates a room
    And 2 other players join the room
    And the host selects a playlist with 3 songs
    And the host sets the rounds to 3
    When the host starts the game
    Then all players see round 1

    # Round 1: two correct answers
    When the host plays the song
    And player 1 submits the correct answer
    And player 2 submits the correct answer
    Then player 1 earns 4 points
    And player 2 earns 2 points
    When the host closes answers
    Then the correct song is revealed

    # Round 2: duration extension, no correct answers
    When the host advances to the next round
    Then all players see round 2
    When the host plays the song
    And the host extends the duration
    Then all players see the updated duration
    When the host closes answers
    Then the correct song is revealed and no winners are shown

    # Round 3: one correct answer
    When the host advances to the next round
    Then all players see round 3
    When the host plays the song
    And player 2 submits the correct answer
    Then player 2 earns 4 points
    When the host closes answers
    Then the correct song is revealed

    # Results
    When the host proceeds to the results
    Then all players are navigated to the result screen
    And player 2 is in 1st place with 6 points
    And player 1 is in 2nd place with 4 points
    And the host is in 3rd place with 0 points

  Scenario: Back to lobby and replay
    Given a game has just finished
    When the host returns to lobby
    Then all players are navigated to the lobby screen
    When the host starts a new game
    Then all players start with 0 points
    And round 1 begins with a new song order

  Scenario: Host ends game before all rounds are played
    Given a host creates a room
    And 2 other players join the room
    And the host starts a game with 3 rounds
    When the host plays the song in round 1
    And player 1 submits the correct answer
    And the host closes answers
    And the host ends the game
    Then all players are navigated to the result screen
    And player 1's score reflects only round 1
