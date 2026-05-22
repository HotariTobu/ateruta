Feature: Home screen
  As a player
  I want to create or join a room from the home screen
  So that I can start playing

  Scenario: Home screen is displayed without waiting for WebSocket
    Given the WebSocket connection is being established
    When the player opens the home screen
    Then the home screen is displayed immediately

  Scenario: Home screen displays title and create button
    When the player opens the home screen
    Then the title "ATERUTA" is displayed
    And the subtitle "Multiplayer intro quiz game" is displayed
    And a "Create Room" button is visible

  Scenario: Room code input accepts only numeric input
    When the player types "ab12" into the room code field
    Then the field contains "12"

  Scenario: Room code input is limited to 4 digits
    When the player types "12345" into the room code field
    Then the field contains "1234"

  Scenario: Error clears when room code input changes
    Given a room check error is displayed
    When the player changes the room code input
    Then the error disappears

  Scenario: Room existence is checked on 4-digit input
    When the player enters a valid 4-digit room code
    Then "Checking..." is displayed
    And a GET /api/room/{code} request is sent

  Scenario: Valid room code navigates to room
    Given a room with code "1234" exists
    When the player enters "1234"
    Then the player is navigated to /room/1234

  # Error messages mirror GET /api/room/{code} responses in room.feature
  Scenario: Non-existent room shows error
    Given no room with code "5678" exists
    When the player enters "5678"
    Then the GET /api/room/{code} request returns 404
    And the error from the response is displayed

  Scenario: Room with game in progress shows error
    Given a room with code "1234" has a game in progress
    When the player enters "1234"
    Then the GET /api/room/{code} request returns 403
    And the error from the response is displayed

  Scenario: Room with ended game shows error
    Given a room with code "1234" has a game that has ended
    When the player enters "1234"
    Then the GET /api/room/{code} request returns 403
    And the error from the response is displayed

  Scenario: Create room button creates and navigates
    When the player clicks "Create Room"
    Then a POST /api/room request is sent
    And on success the player is navigated to /room/{code}

  Scenario: Create room failure shows error
    When the player clicks "Create Room"
    Then the server responds with a non-201 status and error
    And the error message is displayed as a toast

  Scenario: Create room shows loading state
    When the player clicks "Create Room"
    Then the button text changes to "Creating..."
    And the button is disabled
