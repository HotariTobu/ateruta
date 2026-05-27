"""Step definitions for home_screen.feature — Home screen."""

import json
import re
import time

from playwright.sync_api import expect
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../../features/frontend/home_screen.feature")


def _navigate_to_home(spa_page, frontend_url):
    """Navigate to the home screen and wait for it to load."""
    spa_page.goto(frontend_url)
    spa_page.wait_for_load_state("networkidle")


@given("the WebSocket connection is being established")
def ws_connecting(mock_ws_server):
    # The session-scoped server is always running by the time a test
    # starts; verify the bind so subsequent steps can assume connectivity.
    assert mock_ws_server.port > 0


@when("the player opens the home screen")
def open_home_screen(spa_page, frontend_url):
    _navigate_to_home(spa_page, frontend_url)


@then("the home screen is displayed immediately")
def home_screen_displayed(spa_page):
    expect(spa_page.get_by_role("heading", name="ATERUTA")).to_be_visible(timeout=2000)


@then(parsers.parse('the title "{title}" is displayed'))
def title_displayed(spa_page, title):
    expect(spa_page.get_by_role("heading", name=title)).to_be_visible()


@then(parsers.parse('the subtitle "{subtitle}" is displayed'))
def subtitle_displayed(spa_page, subtitle):
    expect(spa_page.get_by_text(subtitle, exact=False)).to_be_visible()


# 'a "{text}" button is visible' is handled by conftest


@when(parsers.parse('the player types "{input_text}" into the room code field'))
def type_into_room_code(spa_page, frontend_url, input_text):
    _navigate_to_home(spa_page, frontend_url)
    spa_page.get_by_role("textbox", name="Room code").fill(input_text)


@then(parsers.parse('the field contains "{expected}"'))
def field_contains(spa_page, expected):
    expect(spa_page.get_by_role("textbox", name="Room code")).to_have_value(expected)


@given("a room check error is displayed")
def room_check_error_displayed(spa_page, frontend_url):
    _navigate_to_home(spa_page, frontend_url)
    spa_page.route(
        "**/api/room/*",
        lambda route: route.fulfill(
            status=404,
            content_type="application/json",
            body=json.dumps({"error": "Room not found"}),
        ),
    )
    spa_page.get_by_role("textbox", name="Room code").fill("9999")
    expect(spa_page.get_by_role("alert").first).to_be_visible(timeout=5000)


@when("the player changes the room code input")
def change_room_code(spa_page):
    field = spa_page.get_by_role("textbox", name="Room code")
    field.fill("")
    field.fill("1")


@then("the error disappears")
def error_disappears(spa_page):
    expect(spa_page.get_by_role("alert")).to_have_count(0)


@when("the player enters a valid 4-digit room code")
def enter_valid_4_digit(spa_page, frontend_url):
    _navigate_to_home(spa_page, frontend_url)
    spa_page.route(
        "**/api/room/*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"code": "1234", "status": "lobby"}),
        ),
    )
    spa_page.get_by_role("textbox", name="Room code").fill("1234")


@then(parsers.parse("a GET /api/room/{{code}} request is sent"))
def room_check_request_sent(spa_page, request_log):
    spa_page.wait_for_load_state("networkidle")
    matches = [
        r for r in request_log if r["method"] == "GET" and "/api/room/" in r["url"]
    ]
    assert matches, (
        f"Expected GET /api/room/* request, got {[r['url'] for r in request_log]}"
    )


@given(parsers.parse('a room with code "{code}" exists'))
def room_exists(spa_page, frontend_url, code):
    _navigate_to_home(spa_page, frontend_url)
    spa_page.route(
        f"**/api/room/{code}",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"code": code, "status": "lobby"}),
        ),
    )


@when(parsers.parse('the player enters "{code}"'))
def player_enters_code(spa_page, code):
    spa_page.get_by_role("textbox", name="Room code").fill(code)


# "the player is navigated to /room/1234" is handled by conftest


@given(parsers.parse('no room with code "{code}" exists'))
def room_not_exists(spa_page, frontend_url, code):
    _navigate_to_home(spa_page, frontend_url)
    spa_page.route(
        f"**/api/room/{code}",
        lambda route: route.fulfill(
            status=404,
            content_type="application/json",
            body=json.dumps({"error": "Room not found"}),
        ),
    )


@then(parsers.parse("the GET /api/room/{{code}} request returns {status_code:d}"))
def room_check_returns_status(spa_page, response_log, status_code):
    deadline = time.time() + 5
    while time.time() < deadline:
        room_responses = [r for r in response_log if "/api/room/" in r["url"]]
        if any(r["status"] == status_code for r in room_responses):
            return
        spa_page.wait_for_timeout(50)

    room_responses = [r for r in response_log if "/api/room/" in r["url"]]
    assert any(r["status"] == status_code for r in room_responses), (
        f"Expected response status {status_code} for /api/room/*, got "
        f"{[(r['url'], r['status']) for r in room_responses]}"
    )


@then("the error from the response is displayed")
def error_from_response_displayed(spa_page):
    expect(spa_page.get_by_role("alert").first).to_be_visible(timeout=5000)


@given(parsers.parse('a room with code "{code}" has a game in progress'))
def room_game_in_progress(spa_page, frontend_url, code):
    _navigate_to_home(spa_page, frontend_url)
    spa_page.route(
        f"**/api/room/{code}",
        lambda route: route.fulfill(
            status=403,
            content_type="application/json",
            body=json.dumps({"error": "Game is in progress"}),
        ),
    )


@given(parsers.parse('a room with code "{code}" has a game that has ended'))
def room_game_ended(spa_page, frontend_url, code):
    _navigate_to_home(spa_page, frontend_url)
    spa_page.route(
        f"**/api/room/{code}",
        lambda route: route.fulfill(
            status=403,
            content_type="application/json",
            body=json.dumps({"error": "Game has ended"}),
        ),
    )


@when(parsers.parse('the player clicks "{button_text}"'))
def player_clicks_button(spa_page, frontend_url, button_text):
    # Default route fulfills the POST with success; the failure scenario
    # overrides this in the subsequent ``server responds with non-201``
    # step before re-clicking.
    _navigate_to_home(spa_page, frontend_url)
    spa_page.route(
        "**/api/room",
        lambda route: (
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps({"code": "5678"}),
            )
            if route.request.method == "POST"
            else route.continue_()
        ),
    )
    spa_page.get_by_role("button", name=button_text).click()


@then("a POST /api/room request is sent")
def post_room_sent(spa_page):
    # The Playwright route mock intercepted the POST request. Verify it
    # was handled by confirming navigation to the created room page.
    expect(spa_page).to_have_url(re.compile(r"/room/\w+"), timeout=5000)


@then(parsers.parse("on success the player is navigated to /room/{{code}}"))
def navigated_to_room_code(spa_page):
    spa_page.wait_for_url("**/room/*", timeout=5000)


@then("the server responds with a non-201 status and error")
@when("the server responds with a non-201 status and error")
def server_responds_error(spa_page, frontend_url):
    # The previous When already clicked Create Room with a success route.
    # Override the route and re-click to drive the failure path through
    # the same UI flow.
    spa_page.unroute("**/api/room")
    spa_page.route(
        "**/api/room",
        lambda route: (
            route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps({"error": "Server error"}),
            )
            if route.request.method == "POST"
            else route.continue_()
        ),
    )
    spa_page.goto(frontend_url)
    spa_page.get_by_role("button", name="Create Room").click()


# "the error message is displayed as a toast" is handled by conftest


@then(parsers.parse('the button text changes to "{text}"'))
def button_text_changes(spa_page, text):
    expect(spa_page.get_by_role("button", name=text).first).to_be_visible(timeout=3000)


@then("the button is disabled")
def button_is_disabled(spa_page):
    expect(spa_page.get_by_role("button", name="Creating...")).to_be_disabled(
        timeout=3000
    )
