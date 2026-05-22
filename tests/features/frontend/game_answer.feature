Feature: Game screen - answering
  As a player
  I want to search for and submit song answers
  So that I can earn points

  # --- Song search ---

  # Design: Search matches titles only—finding by artist is considered
  # too easy. This is an intentional game design choice.
  Scenario: Fuzzy search shows suggestions
    Given the game has songs loaded
    When the player types 1 or more characters in the search field
    Then songs are matched against their titles only
    And up to 10 matching suggestions are displayed
    And each suggestion shows artwork (if available), title, and artist

  Scenario: Empty input shows no suggestions
    When the search field is empty
    Then no suggestions are displayed

  Scenario: No matching songs shows message
    Given the game has songs loaded
    When the player types a query that matches no song titles
    Then "No matching songs" is displayed

  Scenario: All answer UI resets on round change
    When a new round begins
    Then the search query, suggestions, lockout countdown, wrong answer feedback, handicap countdown, and score panel are all reset

  Scenario: Answer UI resets on reveal
    When game:reveal or game:restore-reveal is received
    Then the search query, suggestions, lockout countdown, wrong answer feedback, handicap countdown, and score panel are all cleared

  # --- Answer submission ---

  Scenario: Selecting a suggestion submits the answer
    Given suggestions are displayed
    When the player clicks a suggestion
    Then game:answer with the selected song ID is sent to the server
    And the search field and suggestions are cleared

  Scenario: Answer cannot be submitted during reveal
    Given the round has been revealed
    Then the search input and suggestions are not visible
    And the answer is not submitted

  # --- Client-side answer guard ---

  Scenario: Answer not sent when locked out
    Given the player's lockout is active
    When the player tries to submit an answer
    Then the answer is not sent to the server

  Scenario: Answer not sent when no attempts remaining
    Given the player has no attempts remaining
    When the player tries to submit an answer
    Then the answer is not sent to the server

  # --- Handicap countdown ---

  Scenario: Handicap countdown displayed after submission
    Given the player has handicap of 5 seconds
    When the player submits an answer
    Then a yellow panel shows the submitted song title
    And a countdown from 5.0 seconds is displayed updating every 100ms
    And a progress bar decreases over time

  Scenario: New answer restarts handicap countdown
    Given the handicap countdown is displayed
    When the player submits a new answer
    Then the countdown restarts from the full handicap duration
    And the panel shows the new song title

  Scenario: No handicap countdown for 0-second handicap
    Given the player has handicap of 0 seconds
    When the player submits an answer
    Then no countdown is displayed

  Scenario: Handicap countdown cleared when result is received
    Given the handicap countdown is displayed
    When game:scored or game:wrong-answer is received for the player
    Then the handicap countdown is cleared

  Scenario: Handicap countdown auto-clears at zero
    Given the handicap countdown is displayed
    When the countdown reaches 0
    Then the handicap countdown is cleared

  # --- Wrong answer feedback ---

  Scenario: Wrong answer feedback shown immediately
    Given the player submitted a wrong answer
    Then the wrong answer title is displayed in red as "Wrong: {title}"

  # Design: The 2-second duration has no special significance and can be
  # freely changed.
  Scenario: Wrong answer feedback disappears after 2 seconds
    Given the wrong answer feedback is displayed
    When 2 seconds elapse
    Then the wrong answer feedback disappears

  # --- Lockout state ---

  Scenario: Lockout state disables input
    Given the player is locked out
    Then the search field is disabled
    And the placeholder shows "Locked out..."
    And a red panel shows "Locked out for {N}s" updating every 100ms

  # --- Attempts ---

  Scenario: Attempts remaining displayed
    Given a game with attempts limit 3
    And the player has 2 attempts remaining
    Then "2 / 3 attempts left" is displayed in gray

  Scenario: No attempts remaining message
    Given a game with attempts limit 3
    And the player has used all attempts
    Then "0 / 3 attempts left" is displayed in gray

  Scenario: Attempts display hidden when unlimited
    Given a game with attempts limit 0
    Then no attempts display is shown

  # --- Scoring feedback ---

  Scenario: Own score hides search UI
    Given the player answered correctly and earned 4 points
    Then a blue panel shows "You scored 4 points!"
    And the search input and suggestions are not visible

  Scenario: Auto-reveal skips own scoring panel
    Given the player's correct answer fills the last scoring slot
    Then the scoring panel is not displayed
    And the player sees themselves in the reveal panel winners instead

  Scenario: Other players' scores displayed with ordinal
    Given another player scored 4 points as 1st place
    Then a green panel shows "{nickname} scored 4pt(s)! (1st)"
    And ordinals follow: 1st, 2nd, 3rd, 4th...

  # --- Input state ---

  Scenario: Search field has autofocus
    Given the game screen is displayed
    Then the search field is focused

  Scenario: Input disabled when locked out or no attempts
    Given the player is locked out or has no attempts remaining
    Then the search field is disabled and dimmed

  # --- State restoration ---

  Scenario: Scored state restored from game:player-state
    When game:player-state is received with scored as true
    Then the scored panel is displayed with the earned points
    And the search UI is hidden

  Scenario: Lockout restored from game:player-state
    When game:player-state is received with an active lockout
    Then the lockout countdown is displayed with the remaining time

  Scenario: Attempts restored from game:player-state
    When game:player-state is received with wrongAnswerCount greater than 0
    Then the attempts remaining display reflects the restored count

  Scenario: Pending answer restored from game:player-state
    When game:player-state is received with a pending answer
    Then the handicap countdown is displayed with the remaining time
    And the submitted song title is shown
