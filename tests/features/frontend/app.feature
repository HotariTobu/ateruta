Feature: App initialization
  As a player
  I want the app to initialize properly
  So that I can use the game

  Scenario: Session is initialized on app start
    When the app starts
    Then GET /api/session is called
    And the player session cookie is established

  Scenario: Session initialization failure shows error
    When the app starts
    Then GET /api/session fails
    And "Server unavailable" is displayed as the entire page content

  Scenario: WebSocket connection is established after session
    Given the session cookie has been established
    Then a WebSocket connection is established in the background

  Scenario: WebSocket initial connection retries with backoff
    Given the session cookie has been established
    When the app attempts the initial WebSocket connection
    Then the connection is retried with intervals of 1, 2, 4, 8, 16 seconds
    And after the last retry fails, "Connection failed" is displayed as the entire page content
