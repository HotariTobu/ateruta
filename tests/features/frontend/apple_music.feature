Feature: Apple Music integration
  As a host
  I want to use Apple Music to select and play songs
  So that the game has music content

  # --- Initialization ---
  # Design: Developer tokens are long-lived (up to 6 months). Token refresh
  # within a single session is not needed.

  Scenario: Apple Music SDK loads on app start
    When the app starts
    Then the Apple Music SDK is initialized with the developer token from the server

  Scenario: Already authorized on initialization
    Given the player has previously authorized Apple Music
    When the Apple Music SDK is initialized
    Then the authorized state is set

  Scenario: Not authorized on initialization
    Given the player has not authorized Apple Music
    When the Apple Music SDK is initialized
    Then the unauthorized state is set

  Scenario: Authorization is monitored
    When a user authorizes Apple Music
    Then the authorized state becomes true

  Scenario: Unauthorization is monitored
    When a user unauthorizes Apple Music
    Then the authorized state becomes false

  Scenario: SDK initialization error displayed
    When the app attempts to initialize the Apple Music SDK
    Then initialization fails
    And the error message is displayed as a toast

  # --- Authorization ---

  Scenario: Authorize button shown when not authorized
    Given the player is the host
    And Apple Music is not authorized
    Then an "Authorize Apple Music" button is visible

  Scenario: Authorizing Apple Music
    When the host clicks "Authorize Apple Music"
    Then the Apple Music authorization flow is triggered

  Scenario: Sign out link shown when authorized
    Given Apple Music is authorized
    Then a "Sign out of Apple Music" link is visible

  Scenario: Signing out of Apple Music
    When the host clicks "Sign out of Apple Music"
    Then Apple Music authorization is revoked

  # --- Playlist search ---

  # Design: Public playlist search uses the catalog API which requires only
  # a developer token, not user authorization.
  Scenario: Search returns up to 10 playlists
    When the host searches for playlists with a keyword
    Then up to 10 matching playlists are displayed with artwork (if available) and name

  Scenario: Selecting a playlist loads songs
    Given search results are displayed
    When the host selects a playlist
    Then the songs from that playlist are loaded
    And the playlist results close
    And the song list appears in the lobby

  # --- Library access ---

  Scenario: Library tab shows user's playlists
    Given Apple Music is authorized
    When the host opens the "My Library" tab
    Then the user's library playlists are displayed with artwork (if available) and name

  Scenario: Library tab prompts login when not authorized
    Given Apple Music is not authorized
    When the host opens the "My Library" tab
    Then a message prompts the user to log in to Apple Music

  Scenario: Library playlists can be filtered
    Given library playlists are displayed
    When the host types in the filter field
    Then playlists are filtered by name (case-insensitive)

  # --- URL loading ---

  Scenario: Valid URL loads playlist
    When the host pastes a valid Apple Music playlist URL into the search field
    Then the songs from the playlist are loaded

  Scenario: Invalid URL shows error
    When the host pastes a URL without a valid playlist ID into the search field
    Then "Invalid playlist URL" is displayed

  Scenario: Empty playlist shows error
    When the host pastes a URL for a playlist with no songs into the search field
    Then a toast "No songs found in this playlist" is displayed

  Scenario: Selected playlist has no songs
    Given search results or library playlists are displayed
    When the host selects a playlist that contains no songs
    Then a toast "No songs found in this playlist" is displayed

  Scenario: Network error during URL load shows error
    When the host pastes a playlist URL into the search field
    Then the playlist load fails with a network error
    And the error message is displayed as a toast

  # --- Token management ---

  # Design: Developer tokens are long-lived (up to 6 months). Re-fetching
  # within a single session is rare but handled for robustness.
  Scenario: Expired token is re-fetched
    Given the developer token has expired
    When a music operation requires a valid token
    Then a new developer token is fetched from the server

  # --- Pagination ---

  Scenario: Large playlists are fully loaded
    Given a playlist has more than 100 songs
    When the playlist songs are loaded
    Then all songs from the playlist are loaded

  # --- Song playback (host only) ---

  Scenario: Song plays for specified duration then stops
    Given the host has a song ready to play
    When the song is played with a duration
    Then the song plays for the specified duration and then stops

  Scenario: Full song playback on reveal
    When the round is revealed
    Then the host plays the revealed song without a time limit

  Scenario: Current song stopped on round change
    Given a song is currently playing on the host
    When the current round changes
    Then the host's current song is stopped

  # Design: "Round changes" includes the initial round (lobby → round 1)
  # and state restoration on reconnection (unknown → current round).
  Scenario: Song loaded on round change
    When the current round changes
    Then the song for the current round is loaded on the host

  Scenario: Revealed song plays automatically on restore-reveal
    When game:restore-reveal is received on the host
    Then the host plays the revealed song without a time limit

  Scenario: Same song index skips reload
    Given the song for the current round is already loaded on the host
    When the round state is updated without a round change
    Then the song is not reloaded

  Scenario: Song playback failure shows error
    Given the host has a song ready to play
    When the host plays the song
    Then song playback fails
    And the error message is displayed as a toast

  # --- Queue management ---

  Scenario: Queue is prepared with shuffled songs
    Given the host receives the shuffled song IDs via game:shuffled-songs
    Then round N plays the Nth song (1-indexed) from the shuffled list on the host

  # --- Host-only playback ---

  # Design: Only the host plays music due to Apple Music authorization
  # constraints and the difficulty of synchronizing playback across devices.
  Scenario: Only the host plays music locally
    Then music is played only on the host's device via Apple Music
    And non-host players do not play music locally

  # --- Cleanup ---

  Scenario: Playback stops and resets on stop
    When playback is stopped on the host
    Then the song is paused and reset to the beginning

  Scenario: Full cleanup on leaving game
    When the host leaves the game screen
    Then all playback is stopped and the queue is cleared
