"""Frontend test fixtures and shared step definitions.

Frontend tests use Playwright with a mock WebSocket server.
The Go backend is NOT started—all server behavior is mocked in Python.
"""

import pytest
from playwright.sync_api import Page, expect

from pytest_bdd import parsers, then

from frontend.helpers import (
    SELF_PLAYER_ID,
    MockWSServer,
    get_session_response_json,
    get_token_response_json,
    install_websocket_route,
    only_button,
    only_role,
    only_status,
    session_cookie_header,
    utc_datetime,
    visible_alert,
)
from frontend.musickit_mock import make_developer_token, configure_musickit_api_mock


@pytest.fixture(scope="session")
def mock_ws_server():
    """Session-scoped mock WebSocket server."""
    server = MockWSServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture(autouse=True)
def _reset_mock_ws(mock_ws_server):
    """Reset mock WS state before each test.

    Restarts the server if a prior test stopped it (port may change; later
    fixtures that read ``mock_ws_server.url`` will see the current bind).
    """
    mock_ws_server.ensure_running()
    mock_ws_server.reset()


@pytest.fixture(autouse=True)
def _default_musickit_mock(page: Page):
    """Route Apple Music traffic through the MusicKit API mock on every page."""
    configure_musickit_api_mock(page)


@pytest.fixture
def request_log(page: Page) -> list[dict[str, str]]:
    """Records every request the page makes, for verification by steps."""
    log: list[dict[str, str]] = []
    page.on(
        "request",
        lambda r: log.append({"method": r.method, "url": r.url}),
    )
    return log


@pytest.fixture
def response_log(page: Page) -> list[dict[str, object]]:
    """Records every response the page receives, for verification by steps."""
    log: list[dict[str, object]] = []
    page.on(
        "response",
        lambda r: log.append({"status": r.status, "url": r.url}),
    )
    return log


@pytest.fixture
def frontend_state() -> dict[str, object]:
    """Small per-scenario state bag for multi-step frontend assertions."""
    return {}


@pytest.fixture
def spa_page(
    page: Page, frontend_url, mock_ws_server, request_log, response_log
) -> Page:
    """Playwright page configured for frontend testing.

    Intercepts API calls and configures the SPA to use the mock WS server.
    Depends on request_log / response_log so listeners are attached before
    any navigation, enabling steps to verify HTTP traffic after the fact.
    """
    page.route(
        "**/api/session",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=get_session_response_json(),
            headers={"Set-Cookie": session_cookie_header(SELF_PLAYER_ID)},
        ),
    )

    page.route(
        "**/api/token",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=get_token_response_json(
                make_developer_token(), utc_datetime(2099, 1, 1)
            ),
        ),
    )

    install_websocket_route(page, mock_ws_server.url)

    return page


# ---------------------------------------------------------------------------
# Shared display assertions
# ---------------------------------------------------------------------------


@then(
    parsers.re(
        r'^"(?P<text>(?!Loading songs\.\.\.|Connecting\.\.\.|Reconnecting\.\.\.).+)" is displayed$'
    )
)
def text_is_displayed(spa_page, text):
    expect(spa_page.get_by_text(text, exact=True)).to_be_visible()


@then(parsers.parse('a toast "{text}" is displayed'))
def toast_displayed(spa_page, text):
    visible_alert(spa_page, text)


@then(parsers.parse('"{text}" is displayed as a toast'))
def text_displayed_as_toast(spa_page, text):
    visible_alert(spa_page, text)


@then("the error message is displayed as a toast")
def error_toast_displayed(spa_page):
    visible_alert(spa_page)


@then(parsers.parse("the player is navigated to /{destination}"))
def navigated_to(spa_page, destination):
    spa_page.wait_for_url(f"**/{destination}", timeout=5000)


@then("the player is navigated to the home screen")
def navigated_to_home(spa_page):
    spa_page.wait_for_function("() => window.location.pathname === '/'", timeout=5000)
    expect(spa_page.get_by_role("heading", name="ATERUTA")).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# Shared button / link assertions
# ---------------------------------------------------------------------------


@then(parsers.parse('a "{text}" button is visible'))
def button_visible(spa_page, text):
    expect(only_button(spa_page, text)).to_be_visible(timeout=5000)


@then(parsers.parse('no "{text}" button is visible'))
def no_button_visible(spa_page, text):
    expect(spa_page.get_by_role("button", name=text)).to_have_count(0)


@then(parsers.parse('an "{text}" button is visible'))
def button_visible_an(spa_page, text):
    expect(only_button(spa_page, text)).to_be_visible(timeout=5000)


@then(parsers.parse('a "{text}" link is visible'))
def link_visible(spa_page, text):
    expect(only_role(spa_page, "link", name=text)).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# Host disconnection banner — shared by game_play / result screens
# ---------------------------------------------------------------------------


@then('a banner displays "The host has disconnected. Waiting for reconnection..."')
def host_disconnect_banner(spa_page):
    expect(only_status(spa_page, "The host has disconnected")).to_be_visible(
        timeout=5000
    )


@then("the banner is dismissed")
def banner_dismissed(spa_page):
    expect(
        spa_page.get_by_role("status").filter(has_text="The host has disconnected")
    ).to_have_count(0)
