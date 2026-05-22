Feature: Game screen - playback and host controls
  As a host
  I want to control song playback during the game
  So that players can listen and answer

  # --- Round display ---

  Scenario: Round info is displayed with total
    Given round 3 of a game with 10 total rounds
    Then "Round 3/10" is displayed

  Scenario: Duration is always displayed
    Given a round is in progress
    Then "Duration: {N}s" is always shown regardless of playback state

  # --- Host playback controls ---

  Scenario: Host-only controls are not visible to non-host players
    Given the player is not the host
    Then the Play, Extend, Close Answers, End Game, Next Round, and See Results buttons are not visible

  Scenario: Host clicks play
    Given the host is on the game screen and a song is ready
    When the host clicks "Play"
    Then the song is played locally
    And game:play-song is sent to the server

  Scenario: Play button disabled during playback or when not ready
    Given a song is currently playing or the song is not ready
    Then the "Play" button is disabled

  Scenario: Play button shows preparing state
    Given the song data has not yet been fetched
    Then the "Play" button shows "Preparing..."

  Scenario: Play button shows loading state
    Given the song data is being loaded
    Then the "Play" button shows "Loading..."

  Scenario: Play button re-enabled after playback ends
    Given the song has finished playing
    Then the "Play" button is enabled
    And the host can replay the song without extending

  Scenario: Host extends duration
    Given a round is in progress
    When the host clicks "Extend"
    Then game:extend is sent to the server

  Scenario: Extend button disabled at maximum step or during playback
    Given the duration is at the last step or a song is playing or not ready
    Then the "Extend" button is disabled

  # Design: Playback state is local to the host's device and is not
  # restored on reconnection. The host must play the song again.
  Scenario: Close Answers button disabled before song is played
    Given no song has been played in this round
    Then the "Close Answers" button is disabled

  Scenario: Host closes answers
    Given the song has finished playing
    When the host clicks "Close Answers"
    Then game:close-answers is sent to the server

  # Design: This restriction has no strong rationale and could be removed.
  Scenario: Close Answers button disabled during playback
    Given a song is currently playing
    Then the "Close Answers" button is disabled

  Scenario: Host controls hidden after reveal
    Given the round has been revealed
    Then the Play, Extend, and Close Answers buttons are not visible

  # --- Playing status ---

  Scenario: Playing status displayed during playback
    Given a song is currently playing
    Then "Playing..." is displayed in blue

  Scenario: Host determines playback state from local player
    Given the player is the host
    Then playback state is based on the local music player

  # Design: Non-host playback state uses a local timer to avoid
  # unnecessary network traffic for playback-end notifications.
  Scenario: Non-host determines playback state from server event
    Given the player is not the host
    Then playback state is based on the game:play-song event

  Scenario: Non-host playing status ends after playback duration
    Given a non-host player sees "Playing..." after receiving game:play-song
    When the current playback duration elapses
    Then "Playing..." is no longer displayed

  Scenario: Non-host playing status resets on new play-song event
    Given a non-host player received game:play-song and the timer is running
    When a new game:play-song is received
    Then the playing status timer is reset to the current playback duration

  # --- Reveal ---

  Scenario: Restore-reveal triggers reveal state
    Given a round has been revealed
    When game:restore-reveal is received
    Then the reveal panel is displayed with the correct song and winners

  Scenario: Reveal panel shows correct song
    Given the round has been revealed
    Then the correct song's artwork (if available), title, and artist are displayed

  Scenario: Reveal panel shows winners with format
    Given the round has been revealed with 2 winners
    Then each winner shows "{rank}. {nickname} (+{points}pt(s))"

  Scenario: Reveal panel shows no winners
    Given the round has been revealed with no winners
    Then "No one got it" is displayed

  Scenario: Host advances to next round after reveal
    Given the round has been revealed and more rounds remain
    Then the host sees a "Next Round" button
    When the host clicks "Next Round"
    Then game:next-round is sent to the server

  Scenario: Host proceeds to results from last round
    Given the last round has been revealed
    Then the host sees a "See Results" button
    When the host clicks "See Results"
    Then game:end is sent to the server

  # --- Scoreboard ---

  # Design: Tied player order is intentionally left undefined—there is no
  # meaningful criterion to sort by and no need to manage one.
  Scenario: Scoreboard shows players sorted by score
    Given players have different scores
    Then the "Scoreboard" header is displayed
    And players are sorted by score descending
    And tied players have the same rank
    And the order of tied players is not defined

  Scenario: Current player is always marked in scoreboard
    Given the player is in the game
    Then "(you)" is shown next to the player's own name regardless of score

  Scenario: Scoreboard shows handicap badge
    Given a player has handicap of 5 seconds
    Then "+5s" badge is visible next to the player's name in the scoreboard

  Scenario: Scoreboard shows inactive players separately
    Given some players have disconnected during the game
    Then inactive players are shown in a separate section below active players
    And inactive players are also sorted by score descending

  # --- Host disconnection ---

  Scenario: Banner shown when host disconnects during game
    Given a game is in progress
    When the host disconnects
    Then a banner displays "The host has disconnected. Waiting for reconnection..."
    And the banner does not block game interaction

  Scenario: Banner dismissed when host reconnects
    Given the host disconnection banner is displayed
    When the host reconnects
    Then the banner is dismissed

  # --- End game ---

  Scenario: Host can end game early
    Given a game is in progress
    Then the host sees an "End Game" button in red text
    When the host clicks "End Game"
    Then game:end is sent to the server

  Scenario: Playback cleanup on leaving game
    When the player leaves the game screen
    Then all playback is stopped and cleaned up
