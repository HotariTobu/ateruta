"""Step definitions for room_screen.feature — Room screen."""

import json
import re
import time
from collections.abc import Mapping, Sequence

from playwright.sync_api import expect
from pytest_bdd import given, parsers, scenarios, then, when

from frontend.helpers import (
    SELF_PLAYER_ID,
    Scenario,
    install_failing_websocket_route,
    make_room_state_payload,
    make_settings_payload,
    only_alert,
    only_region,
    only_status,
    setup_room_route,
    setup_scenario,
    visible_alert,
)

scenarios("../../features/frontend/room_screen.feature")

_DEFAULT_PLAYERS: Sequence[Mapping[str, object]] = [
    {"id": SELF_PLAYER_ID, "nickname": "Host", "handicap": 0},
]


def _app_ws_attempts(spa_page) -> list[float]:
    return spa_page.evaluate("""
        () => (window.__ATERUTA_WS_ATTEMPTS__ ?? [])
            .filter((attempt) => !attempt.url.includes("?token="))
            .map((attempt) => attempt.at / 1000)
    """)


def _setup_join_handler(
    mock_ws_server,
    host_player_id: str = SELF_PLAYER_ID,
    active_players: Sequence[Mapping[str, object]] = _DEFAULT_PLAYERS,
):
    """Register a room:join handler that responds with room:settings."""
    mock_ws_server.on_respond(
        "room:join",
        "room:settings",
        make_settings_payload(host_player_id, active_players),
    )


def _navigate_to_room(spa_page, mock_ws_server, frontend_url, code="1234"):
    """Full setup to get a player into a room."""
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        Scenario(
            host_player_id=SELF_PLAYER_ID,
            active_players=list(_DEFAULT_PLAYERS),
            code=code,
        ),
    )


@given(parsers.parse('a room with code "{code}" exists'), target_fixture="room_code")
def room_exists(spa_page, code):
    setup_room_route(spa_page, code)
    return code


@when(parsers.parse("the player navigates to /room/{code}"))
def navigate_to_room(spa_page, mock_ws_server, frontend_url, frontend_state, code):
    if code == "{code}":
        mode = frontend_state.get("generic_room_code_mode")
        if mode in {"connect_pending", "join_pending"}:
            setup_room_route(spa_page, "1234")
            spa_page.goto(f"{frontend_url}room/1234")
            return

        setup_room_route(spa_page, "9999", status=404, error="Room not found")
        spa_page.goto(f"{frontend_url}room/9999")
        return

    _setup_join_handler(mock_ws_server)
    spa_page.goto(f"{frontend_url}room/{code}")


@then(parsers.parse("a GET /api/room/{code} request is sent"))
def room_check_sent(spa_page, request_log, code):
    spa_page.wait_for_load_state("networkidle")
    matches = [
        r
        for r in request_log
        if r["method"] == "GET" and f"/api/room/{code}" in r["url"]
    ]
    assert matches, (
        f"Expected GET /api/room/{code}, got {[r['url'] for r in request_log]}"
    )


@given("the room check has passed")
def room_check_passed(spa_page, frontend_state):
    setup_room_route(spa_page, "1234")
    frontend_state["room_check_passed"] = True


@given("the WebSocket connection is established")
def ws_established(spa_page, mock_ws_server, frontend_url, frontend_state):
    if not frontend_state.get("room_check_passed"):
        setup_room_route(spa_page, "1234")
        frontend_state["generic_room_code_mode"] = "join_pending"
        return

    _setup_join_handler(mock_ws_server)
    spa_page.goto(f"{frontend_url}room/1234")
    spa_page.wait_for_timeout(2000)


@then("room:join is sent to the server")
def room_join_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None, "No WebSocket connection established"
    join_events = conn.events_of("room:join")
    assert len(join_events) > 0, "room:join was not sent"


@then(parsers.parse("the GET /api/room/{{code}} request returns a non-200 status"))
@when(parsers.parse("the GET /api/room/{{code}} request returns a non-200 status"))
def room_check_non_200(spa_page, response_log):
    deadline = time.time() + 5
    while time.time() < deadline:
        room_responses = [r for r in response_log if "/api/room/" in r["url"]]
        if any(r["status"] != 200 for r in room_responses):
            return
        spa_page.wait_for_timeout(50)

    room_responses = [r for r in response_log if "/api/room/" in r["url"]]
    assert any(r["status"] != 200 for r in room_responses), (
        "Expected a non-200 response for /api/room/*, got "
        f"{[(r['url'], r['status']) for r in room_responses]}"
    )


@then("the error from the response is displayed as a toast")
def error_toast_from_response(spa_page):
    expect(only_alert(spa_page)).to_be_visible(timeout=5000)


@given("the player is on a room page")
def player_on_room_page(spa_page, mock_ws_server, frontend_url):
    setup_room_route(spa_page, "1234")
    mock_ws_server.on(
        "room:join",
        lambda conn, _: conn.send_event("error", {"message": "Room is full"}),
    )
    spa_page.goto(f"{frontend_url}room/1234")
    spa_page.wait_for_timeout(1000)


@given("room:join has been sent")
def room_join_already_sent(mock_ws_server):
    room_join_sent(mock_ws_server)


@when("the server returns an error")
@when("room:join fails with an error")
def room_join_fails(spa_page):
    # The Given step already configured the room:join handler to send an
    # error event. Verify that error reached the page by asserting the
    # alert is visible before the Then chain runs.
    visible_alert(spa_page, "Room is full")


# "the error message is displayed as a toast" is in conftest
# "the player is navigated to the home screen" is in conftest


@given("the WebSocket connection is not yet established")
def ws_not_established(spa_page, frontend_state):
    install_failing_websocket_route(spa_page)
    frontend_state["generic_room_code_mode"] = "connect_pending"


@then('"Connecting..." is displayed')
def connecting_displayed(spa_page):
    expect(only_status(spa_page, "Connecting...")).to_be_visible(timeout=5000)


@given("the join is in progress")
def join_in_progress(mock_ws_server):
    # No room:join handler is registered, so the SPA's join request hangs
    # waiting for a response — exactly the "in progress" state.
    assert not mock_ws_server.has_handler("room:join"), (
        "Expected no room:join handler so the join request stays pending"
    )


@then('"Joining room..." is displayed while the join is in progress')
@then('"Joining room..." is displayed')
def joining_displayed(spa_page):
    expect(only_status(spa_page, "Joining room...")).to_be_visible(timeout=5000)


@given("the player is in a room")
def player_in_room(spa_page, mock_ws_server, frontend_url):
    _navigate_to_room(spa_page, mock_ws_server, frontend_url)


# 'a "{text}" button is visible' is handled by conftest


@when(parsers.parse('the player clicks "{button_text}"'))
def click_button(spa_page, button_text):
    spa_page.get_by_role("button", name=button_text).click()


# "the player is navigated to the home screen" is in conftest


@when("the player navigates away from the room page")
def navigate_away(spa_page, frontend_url):
    spa_page.goto(frontend_url)
    spa_page.wait_for_load_state("networkidle")


@then("room:leave is sent")
def room_leave_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None, "Expected a live WS connection to send room:leave on"
    leave_events = conn.events_of("room:leave")
    assert len(leave_events) > 0, "room:leave was not sent"


@when("the player receives an error event from the server")
def receive_error_event(spa_page, mock_ws_server, frontend_url):
    _navigate_to_room(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "error", {"message": "Something went wrong", "code": "ERR_001"}
    )


@then("the message field is displayed as a toast")
def message_as_toast(spa_page):
    expect(only_alert(spa_page, "Something went wrong")).to_be_visible(timeout=5000)


@then("all other fields in the error payload are ignored")
def other_fields_ignored(spa_page):
    expect(spa_page.get_by_role("alert").filter(has_text="ERR_001")).to_have_count(0)


@when("the WebSocket connection is lost")
def ws_connection_lost(spa_page, mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None, "Expected an active connection to drop"
    install_failing_websocket_route(spa_page)
    conn.close()


@then('"Reconnecting..." is displayed')
def reconnecting_displayed(spa_page):
    expect(only_status(spa_page, "Reconnecting...")).to_be_visible(timeout=5000)


@given("the WebSocket connection is lost")
def ws_lost(spa_page, mock_ws_server, frontend_url):
    _navigate_to_room(spa_page, mock_ws_server, frontend_url)
    conn = mock_ws_server.latest_connection
    assert conn is not None, "Expected an active connection to drop"
    conn.close()
    spa_page.wait_for_timeout(1000)


@then("reconnection is attempted with intervals of 1, 2, 4, 8, 16 seconds")
def reconnection_with_backoff(spa_page, mock_ws_server):
    expected = [1, 2, 4, 8, 16]
    baseline = len(_app_ws_attempts(spa_page))
    spa_page.wait_for_timeout(sum(expected) * 1000 + 5000)
    timestamps = _app_ws_attempts(spa_page)[baseline:]

    assert len(timestamps) >= len(expected), (
        f"Expected at least {len(expected)} WS retry attempts, got {len(timestamps)}"
    )

    for i in range(1, len(expected)):
        actual_interval = timestamps[i] - timestamps[i - 1]
        expected_interval = expected[i]
        assert expected_interval * 0.7 <= actual_interval <= expected_interval * 1.5, (
            f"Retry {i + 1}: expected ~{expected_interval}s, got {actual_interval:.1f}s"
        )


@then(parsers.parse('after all retries fail, "{text}" is displayed'))
@then(parsers.parse('if all retries fail, "{text}" is displayed'))
def all_retries_fail(spa_page, text):
    expect(spa_page.get_by_role("heading", name=text)).to_be_visible(timeout=40000)


# "a 'Retry' button is visible" reuses conftest button_visible


@given("all reconnection retries have failed")
def all_retries_failed(spa_page, mock_ws_server, frontend_url):
    _navigate_to_room(spa_page, mock_ws_server, frontend_url)
    conn = mock_ws_server.latest_connection
    if conn is not None:
        install_failing_websocket_route(spa_page)
        conn.close()
    spa_page.wait_for_timeout(35000)
    mock_ws_server.ensure_running()


# "the player clicks 'Retry'" reuses click_button


@then("reconnection is attempted again with the same backoff intervals")
def reconnection_restarted(spa_page):
    expect(only_status(spa_page, "Reconnecting...")).to_be_visible(timeout=5000)


@given("the WebSocket disconnection indicator is shown")
def ws_disconnection_indicator(spa_page, mock_ws_server, frontend_url):
    _navigate_to_room(spa_page, mock_ws_server, frontend_url)
    conn = mock_ws_server.latest_connection
    assert conn is not None, "Expected a live connection to drop"
    conn.close()
    expect(only_status(spa_page, "Reconnecting...")).to_be_visible(timeout=5000)


@when("the connection is re-established")
def connection_reestablished(spa_page, mock_ws_server):
    _setup_join_handler(mock_ws_server)
    spa_page.wait_for_timeout(3000)


@then("the indicator is dismissed")
def indicator_dismissed(spa_page):
    expect(
        spa_page.get_by_role("status").filter(has_text="Reconnecting...")
    ).to_have_count(0)


@then("room:join is sent to the server to rejoin the room")
def room_join_rejoin(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None, "No WebSocket connection after reconnection"
    join_events = conn.events_of("room:join")
    assert len(join_events) > 0, "room:join was not sent on reconnection"


@when("a room:closed event is received")
def room_closed_received(mock_ws_server):
    mock_ws_server.latest_connection.send_event(
        "room:closed", {"message": "Room has been closed"}
    )


@then("the message is displayed as a toast")
def message_toast(spa_page):
    expect(only_alert(spa_page, "Room has been closed")).to_be_visible(timeout=5000)


@then("the screen is determined by room:state:")
def screen_determined_by_state(spa_page, mock_ws_server):
    """Verify screen routing based on room:state values.

    Table rows:
      | room:state          | screen        |
      | null                | lobby screen  |
      | phase is "playing"  | game screen   |
      | phase is "finished" | result screen |
    """
    conn = mock_ws_server.latest_connection
    state_players = [{"id": SELF_PLAYER_ID, "score": 0}]

    # null -> lobby screen (send_event coerces None to {}, so send raw JSON null)
    conn.send_raw(json.dumps({"event": "room:state", "payload": None}))
    expect(spa_page.get_by_role("button", name="Start Game")).to_be_visible(
        timeout=5000
    )

    conn.send_event("room:state", make_room_state_payload("playing", state_players))
    expect(
        spa_page.get_by_role("heading", name=re.compile(r"^Round \d+\/\d+$"))
    ).to_be_visible(timeout=5000)

    conn.send_event("room:state", make_room_state_payload("finished", state_players))
    expect(spa_page.get_by_role("heading", name="Game Over!")).to_be_visible(
        timeout=5000
    )


@when("room:settings is received")
def room_settings_received(spa_page, mock_ws_server, frontend_url):
    _navigate_to_room(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "room:settings",
        make_settings_payload(
            SELF_PLAYER_ID,
            [
                {"id": SELF_PLAYER_ID, "nickname": "Updated Player", "handicap": 0},
                {"id": "player-2", "nickname": "Player 2", "handicap": 0},
            ],
        ),
    )


@then("all settings-derived UI is updated to reflect the latest data")
def settings_ui_updated(spa_page):
    expect(
        only_region(spa_page, "Players").get_by_text("Updated Player", exact=True)
    ).to_be_visible(timeout=5000)


@when("room:state is received")
def room_state_received(spa_page, mock_ws_server, frontend_url):
    _navigate_to_room(spa_page, mock_ws_server, frontend_url)
    state_players = [{"id": SELF_PLAYER_ID, "score": 0}]
    mock_ws_server.latest_connection.send_event(
        "room:state",
        make_room_state_payload("playing", state_players, current_round=2),
    )


@then("all state-derived UI is updated to reflect the latest data")
def state_ui_updated(spa_page):
    expect(
        spa_page.get_by_role("heading", name=re.compile(r"^Round 2\/\d+$"))
    ).to_be_visible(timeout=5000)


@given("the WebSocket connection was closed with close code 4409")
def ws_closed_4409(spa_page, mock_ws_server, frontend_url):
    _navigate_to_room(spa_page, mock_ws_server, frontend_url)
    conn = mock_ws_server.latest_connection
    assert conn is not None, "Expected an active connection to close with 4409"
    conn.close(4409, "Connected from another location")
    spa_page.wait_for_timeout(2000)


@then("automatic reconnection is not attempted")
def no_auto_reconnect(spa_page, mock_ws_server):
    expect(
        spa_page.get_by_role("status").filter(has_text="Reconnecting...")
    ).to_have_count(0)
    # A silent reconnect would open a new WebSocket; the mock retains every
    # connection it accepted, so the count must not grow past the original one.
    assert len(mock_ws_server.connections) == 1, (
        f"Expected no reconnection attempt after a 4409 close, but "
        f"{len(mock_ws_server.connections)} connections were opened"
    )


# '"{text}" is displayed as a toast' is in conftest
