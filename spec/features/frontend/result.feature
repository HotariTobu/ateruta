Feature: Result screen
  As a player
  I want to see the final game results
  So that I know who won

  Scenario: Result screen displays game over title
    Given the game has finished
    Then "Game Over!" is displayed

  Scenario: Final scores are displayed sorted by score
    Given the game has finished with players at different scores
    Then players are listed in order of score descending
    And each player shows their rank, nickname, and score

  # Design: Tied player order is intentionally left undefined—there is no
  # meaningful criterion to sort by and no need to manage one.
  Scenario: Tied players have the same rank
    Given two players have the same score
    Then they are displayed with the same rank number
    And the order of tied players is not defined

  Scenario: Current player is marked
    Given the game has finished
    Then "(you)" is shown next to the current player's name

  Scenario: Host sees back to lobby button
    Given the game has finished and the player is the host
    Then a "Back to Lobby" button is visible

  Scenario: Host clicks back to lobby
    Given the game has finished and the player is the host
    When the host clicks "Back to Lobby"
    Then game:back-to-lobby is sent to the server

  Scenario: Non-host sees waiting message
    Given the game has finished and the player is not the host
    Then "Waiting for the host to return to lobby..." is displayed
    And no "Back to Lobby" button is visible

  Scenario: Non-host returns to lobby when host triggers it
    Given the game has finished and the player is not the host
    When the host triggers back to lobby
    Then the player is navigated to the lobby screen

  Scenario: Disconnected players shown in results
    Given some players disconnected during the game
    Then disconnected players are shown in a separate section below active players
    And disconnected players are sorted by score descending within their section

  # --- Host disconnection ---

  Scenario: Banner shown when host disconnects on result screen
    Given the game has finished
    When the host disconnects
    Then a banner displays "The host has disconnected. Waiting for reconnection..."

  Scenario: Banner dismissed when host reconnects on result screen
    Given the host disconnection banner is displayed on the result screen
    When the host reconnects
    Then the banner is dismissed
