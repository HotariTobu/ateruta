Feature: Room screen
  As a player in a room
  I want the room page to handle connections and navigation
  So that I can interact with the game reliably

  Scenario: Room URL triggers room check
    Given a room with code "1234" exists
    When the player navigates to /room/1234
    Then a GET /api/room/1234 request is sent

  Scenario: Room join is sent after WebSocket is established
    Given the room check has passed
    And the WebSocket connection is established
    Then room:join is sent to the server

  Scenario: Room check failure navigates to home
    When the player navigates to /room/{code}
    And the GET /api/room/{code} request returns a non-200 status
    Then the error from the response is displayed as a toast
    And the player is navigated to the home screen

  Scenario: Room join failure navigates to home
    Given the player is on a room page
    When room:join fails with an error
    Then the error message is displayed as a toast
    And the player is navigated to the home screen

  Scenario: Connecting state shown while waiting for WebSocket
    Given the player navigates to /room/{code}
    And the WebSocket connection is not yet established
    Then "Connecting..." is displayed

  Scenario: Joining room shows loading state
    Given the player navigates to /room/{code}
    And the WebSocket connection is established
    And the join is in progress
    Then "Joining room..." is displayed

  Scenario: Back to Home button always visible
    Given the player is in a room
    Then a "Back to Home" button is visible

  Scenario: Back to Home navigates to home screen
    Given the player is in a room
    When the player clicks "Back to Home"
    Then the player is navigated to the home screen

  Scenario: Leaving room page triggers leave
    Given the player is in a room
    When the player navigates away from the room page
    Then room:leave is sent

  # Design: Error toasts should not appear during normal operation—they
  # indicate a client bug or an unexpected race condition. Showing only
  # the message is intentional; the remaining payload fields are not
  # useful to the end user.
  Scenario: Server error events are displayed as toast
    When the player receives an error event from the server
    Then the message field is displayed as a toast
    And all other fields in the error payload are ignored

  # --- WebSocket reconnection ---

  Scenario: WebSocket disconnection shows reconnecting state
    Given the player is in a room
    When the WebSocket connection is lost
    Then "Reconnecting..." is displayed

  Scenario: WebSocket reconnection retries with backoff
    Given the WebSocket connection is lost
    Then reconnection is attempted with intervals of 1, 2, 4, 8, 16 seconds
    And if all retries fail, "Connection lost" is displayed
    And a "Retry" button is visible

  Scenario: Retry button restarts reconnection
    Given all reconnection retries have failed
    When the player clicks "Retry"
    Then reconnection is attempted again with the same backoff intervals

  Scenario: WebSocket reconnection restores state
    Given the WebSocket disconnection indicator is shown
    When the connection is re-established
    Then the indicator is dismissed
    And room:join is sent to the server to rejoin the room

  Scenario: Room closed event navigates to home
    Given the player is in a room
    When a room:closed event is received
    Then the message is displayed as a toast
    And the player is navigated to the home screen

  # --- Screen routing ---

  Scenario: Room state determines the displayed screen
    Given the player is in a room
    Then the screen is determined by room:state:
      | room:state          | screen        |
      | null                | lobby screen  |
      | phase is "playing"  | game screen   |
      | phase is "finished" | result screen |

  # --- State synchronization ---

  Scenario: UI reflects the latest room:settings
    When room:settings is received
    Then all settings-derived UI is updated to reflect the latest data

  Scenario: UI reflects the latest room:state
    When room:state is received
    Then all state-derived UI is updated to reflect the latest data

  # --- Connection replacement ---

  Scenario: No auto-reconnect after replaced connection
    Given the WebSocket connection was closed with close code 4409
    Then automatic reconnection is not attempted
    And the player is navigated to the home screen
    And "Connected from another location" is displayed as a toast
