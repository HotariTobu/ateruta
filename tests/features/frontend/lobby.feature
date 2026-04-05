Feature: Lobby screen
  As a player in a room
  I want to prepare for the game
  So that I can configure settings and wait for the host to start

  # --- Room info ---

  Scenario: Lobby displays room code
    Given the player is in a room with code "1234"
    Then "Room: 1234" is displayed
    And "Share this code with other players" is displayed

  # --- Player list ---

  Scenario: Player list shows all players
    Given 3 players are in the room
    Then the player list shows 3 entries
    And the header shows "Players (3)"

  Scenario: Host badge is displayed for the host
    Given the host is in the room
    Then the "Host" badge is visible next to the host's name

  Scenario: Handicap badge shown for players with handicap
    Given a player has handicap of 5 seconds
    Then "+5s" badge is visible next to the player's name

  Scenario: Handicap badge shows decimal when applicable
    Given a player has handicap of 5.3 seconds
    Then "+5.3s" badge is visible next to the player's name

  Scenario: No handicap badge for 0-second handicap
    Given a player has handicap of 0 seconds
    Then no handicap badge is displayed next to the player's name

  Scenario: Inactive players shown separately in lobby
    Given some players have disconnected during lobby
    Then inactive players are shown in a separate section below active players
    And the "Players" header count reflects only active players

  # --- Nickname ---

  Scenario: Nickname is sent automatically after input
    When the player types "Alice" in the nickname field
    Then room:nickname is sent to the server after a short delay

  Scenario: Nickname input has 20 character limit
    When the player types a 25-character string
    Then only the first 20 characters are in the field

  Scenario: Nickname error from server is displayed
    Given the server rejects the nickname
    Then the error message is displayed as a toast

  # --- Handicap ---

  Scenario: Handicap section visible for all players
    Given the player is in a room
    Then the "Handicap Delay" section is visible
    And "Add a delay before your answers are processed." is displayed

  Scenario: Player adjusts handicap slider
    When the player moves the handicap slider to 10
    Then "10s" is displayed next to the slider
    And room:handicap is sent to the server after a short delay

  Scenario: Handicap slider range and step
    Then the handicap slider minimum is 0
    And the handicap slider maximum is 30
    And the handicap slider step is 0.1

  # --- Playlist selection (host only) ---

  Scenario: Unauthorized host sees authorize prompt
    Given the player is the host
    And Apple Music is not authorized
    Then an "Authorize Apple Music" button is visible
    And "Sign in to Apple Music to select playlists from your library" is displayed
    And the search input is still visible for public playlist search and URL loading

  Scenario: Playlist tabs shown for authorized host
    Given the player is the host
    And Apple Music is authorized
    Then "My Library" and "Public" tabs are visible
    And a "Search or paste playlist URL" input is displayed

  Scenario: Switching tabs preserves input and results per tab
    When the host switches between "My Library" and "Public" tabs
    Then each tab retains its own search input value and results

  Scenario: Search input detects URL and loads playlist
    When the host pastes a playlist URL into the search field
    Then the playlist is loaded directly

  Scenario: Search input searches public playlists by keyword
    Given the "Public" tab is active
    When the host types a keyword in the search field
    Then matching playlists are displayed

  Scenario: Library playlists filtered by search input
    Given the "My Library" tab is active
    When the host types in the search field
    Then library playlists are filtered by name (case-insensitive)

  Scenario: No matching playlists message
    Given library playlists are displayed with a filter
    When no playlists match the filter
    Then "No matching playlists" is displayed

  Scenario: Selecting a playlist loads songs
    Given playlist results are displayed
    When the host selects a playlist
    Then the previously loaded songs are replaced with the songs from the selected playlist
    And the playlist results close

  Scenario: Loading states displayed
    Given a playlist is being loaded
    Then "Loading songs..." is displayed
    And when library playlists are loading, "Loading library playlists..." is displayed

  # --- Song list ---

  Scenario: Song list displayed when songs are selected
    Given songs have been selected
    Then the song list is visible with header "Songs ({count})"
    And each song shows numbered index, artwork (if available), title, and artist

  Scenario: Song list hidden when no songs selected
    Given no songs have been selected
    Then the song list section is not visible

  # --- Host controls ---

  Scenario: Host sees game settings panel
    Given the player is the host
    Then the game settings panel is visible with:
      | setting                | input type | details                                      |
      | Playback durations     | text       | placeholder "1, 2, 4, 8, 16", with help text |
      | Rank points            | text       | placeholder "4, 2, 1", with help text        |
      | Rounds                 | slider     | min=1, max=songCount, shown when songs exist |
      | Lockout duration       | slider     | min=0, max=30, step=0.1                      |
      | Attempts limit         | slider     | min=0, max=10, step=1, 0 means unlimited     |
    And text fields display the current effective values
    And playback durations help text reads: e.g. "1, 2, 4" = play for 1s, extend to 2s, then 4s
    And rank points help text reads: e.g. "4, 2, 1" = 1st gets 4pt(s), 2nd gets 2pt(s), 3rd gets 1pt(s)

  # Design: The backend initializes game settings as unset. The frontend owns
  # the initial game-setting values, and applying them is a browser-side
  # programmatic settings change covered by automatic sync.
  Scenario: Host applies frontend defaults to unset game settings
    Given the player is the host
    When room:settings is received with one or more unset game setting values
    Then the following frontend defaults are applied to the unset values:
      | setting                | value            |
      | Playback durations     | [1, 2, 4, 8, 16] |
      | Rank points            | [4, 2, 1]        |
      | Lockout duration       | 5                |
      | Attempts limit         | 3                |
    And configured server values are preserved
    And songs are not changed by frontend defaults
    And rounds remain unset until songs exist
    And room:settings with the applied frontend defaults is sent to the server after a short delay

  Scenario: Frontend defaults do not overwrite configured server settings
    Given the player is the host
    When room:settings is received with configured game settings
    Then the game settings panel displays the received server values
    And frontend defaults are not sent to the server

  # Design: All browser-side settings changes are synced to the server,
  # including programmatic adjustments (e.g. rounds slider clamped by song count).
  # Only changes received from the server are excluded from syncing.
  Scenario: Settings are synced automatically
    Given the player is the host
    When any setting value changes on the browser side (manual or programmatic)
    Then the setting is sent to the server after a short delay

  Scenario: Non-numeric values in settings text fields are ignored
    Given the player is the host
    And the playback durations field contains non-numeric values mixed with numbers
    When the setting is synced
    Then only positive numbers are sent

  Scenario: Settings text fields validate before syncing
    # Validations mirror room_settings.feature field validations
    Given the player is the host
    When a text field setting value is invalid
    Then an error is displayed without sending the setting

  Scenario: Rounds slider resets to song count when songs change
    Given the player is the host
    When songs are replaced by a new playlist
    Then the rounds slider is set to the new song count

  Scenario: Start game validates settings
    # Validations mirror game:start checks in backend/features/game.feature
    When the host clicks "Start Game"
    And the settings are invalid
    Then an error is displayed without sending game:start

  # --- Non-host ---

  Scenario: Non-host sees read-only settings
    Given the player is not the host
    Then all game settings are displayed as read-only values

  Scenario: Non-host rounds hidden when no songs selected
    Given the player is not the host
    And no songs have been selected
    Then the rounds value is not displayed

  Scenario: Non-host sees waiting message
    Given the player is not the host
    And no songs have been selected
    Then "Waiting for the host to select a playlist..." is displayed

  Scenario: Non-host sees start waiting message when songs selected
    Given the player is not the host
    And songs have been selected
    Then "Waiting for the host to start the game..." is displayed
