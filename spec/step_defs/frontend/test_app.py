"""Step definitions for app.feature — App initialization."""

from playwright.sync_api import expect
from pytest_bdd import given, parsers, scenarios, then, when

from backend.schemas import SESSION_COOKIE
from frontend.helpers import (
    error_response_json,
    install_failing_websocket_route,
    install_websocket_route,
)

scenarios("../../features/frontend/app.feature")


def _app_ws_attempts(spa_page) -> list[float]:
    return spa_page.evaluate("""
        () => (window.__ATERUTA_WS_ATTEMPTS__ ?? [])
            .filter((attempt) => !attempt.url.includes("?token="))
            .map((attempt) => attempt.at / 1000)
    """)


@when("the app starts")
def app_starts(spa_page, frontend_url):
    spa_page.goto(frontend_url)


@then("GET /api/session is called")
def session_api_called(spa_page, request_log):
    spa_page.wait_for_load_state("networkidle")
    matches = [
        r for r in request_log if r["method"] == "GET" and "/api/session" in r["url"]
    ]
    assert matches, f"Expected GET /api/session, got {[r['url'] for r in request_log]}"


@then("the player session cookie is established")
def session_cookie_established(spa_page):
    cookies = spa_page.context.cookies()
    cookie_names = [c["name"] for c in cookies]
    assert SESSION_COOKIE in cookie_names


@then("GET /api/session fails", target_fixture="spa_page")
@when("GET /api/session fails", target_fixture="spa_page")
def session_api_fails(page, frontend_url, mock_ws_server):
    """Override the session route to return a server error.

    Replaces the entire ``spa_page`` fixture so the failure-mode session
    route wins; the default ``spa_page`` route is registered at fixture
    setup time and cannot be unrouted reliably mid-test.
    """
    page.route(
        "**/api/session",
        lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body=error_response_json("Internal server error"),
        ),
    )
    install_websocket_route(page, mock_ws_server.url)
    page.goto(frontend_url)
    return page


@then(parsers.parse('"{text}" is displayed as the entire page content'))
def text_displayed_as_entire_page(spa_page, text):
    expect(spa_page.get_by_role("heading", name=text)).to_be_visible(timeout=10000)


@given("the session cookie has been established")
def session_established(spa_page, frontend_url):
    spa_page.goto(frontend_url)
    spa_page.wait_for_load_state("networkidle")


@then("a WebSocket connection is established in the background")
def ws_connection_established(spa_page, mock_ws_server):
    spa_page.wait_for_timeout(2000)
    assert len(mock_ws_server.connections) >= 1, (
        "Expected at least one WebSocket connection"
    )


@when("the app attempts the initial WebSocket connection")
def app_attempts_initial_ws_connection(spa_page, frontend_url):
    install_failing_websocket_route(spa_page)
    spa_page.goto(frontend_url)


@then("the connection is retried with intervals of 1, 2, 4, 8, 16 seconds")
@then("connection is retried with intervals of 1, 2, 4, 8, 16 seconds")
def connection_retried_with_backoff(spa_page):
    expected = [1, 2, 4, 8, 16]
    spa_page.wait_for_timeout(sum(expected) * 1000 + 5000)
    ws_attempts = _app_ws_attempts(spa_page)

    assert len(ws_attempts) >= len(expected) + 1, (
        f"Expected at least {len(expected) + 1} WS attempts, got {len(ws_attempts)}"
    )
    for i, expected_interval in enumerate(expected, start=1):
        actual_interval = ws_attempts[i] - ws_attempts[i - 1]
        assert expected_interval * 0.7 <= actual_interval <= expected_interval * 1.5, (
            f"Retry {i + 1}: expected ~{expected_interval}s, got {actual_interval:.1f}s"
        )


@then(
    parsers.parse(
        'after the last retry fails, "{text}" is displayed as the entire page content'
    )
)
@then(
    parsers.parse(
        'if all retries fail, "{text}" is displayed as the entire page content'
    )
)
def all_retries_fail_text(spa_page, text):
    # Retries total 1+2+4+8+16 = 31s; the autouse fixture's ensure_running()
    # restarts the server for subsequent tests, so this wait is allowed to
    # cover the full backoff window plus the SPA render time.
    expect(spa_page.get_by_role("heading", name=text)).to_be_visible(timeout=40000)
