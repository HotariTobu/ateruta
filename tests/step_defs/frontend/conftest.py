"""Frontend test fixtures and shared step definitions.

Frontend tests use Playwright with a mock WebSocket server.
The Go backend is NOT started—all server behavior is mocked in Python.
"""

import json

import pytest
from playwright.sync_api import Page, expect

from backend.schemas import SESSION_COOKIE
from pytest_bdd import parsers, then

from frontend.helpers import (
    SELF_PLAYER_ID,
    MockWSServer,
)
from frontend.musickit_mock import make_developer_token


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
            body=json.dumps({"ready": True}),
            headers={"Set-Cookie": f"{SESSION_COOKIE}={SELF_PLAYER_ID}; Path=/"},
        ),
    )

    page.route(
        "**/api/token",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "token": make_developer_token(),
                    "expiresAt": "2099-01-01T00:00:00Z",
                }
            ),
        ),
    )

    page.add_init_script("""
        (() => {
            if (window.__ATERUTA_WS_ATTEMPTS__ !== undefined) {
                return;
            }
            const NativeWebSocket = window.WebSocket;
            const attempts = [];
            function WrappedWebSocket(url, protocols) {
                attempts.push({ url: String(url), at: Date.now() });
                if (protocols === undefined) {
                    return new NativeWebSocket(url);
                }
                return new NativeWebSocket(url, protocols);
            }
            WrappedWebSocket.prototype = NativeWebSocket.prototype;
            Object.setPrototypeOf(WrappedWebSocket, NativeWebSocket);
            window.__ATERUTA_WS_ATTEMPTS__ = attempts;
            window.WebSocket = WrappedWebSocket;
        })();
    """)

    page.add_init_script(f"""
        window.__TEST_WS_URL__ = {json.dumps(mock_ws_server.url)};
    """)

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
    expect(spa_page.get_by_text(text, exact=False).first).to_be_visible()


@then(parsers.parse('a toast "{text}" is displayed'))
def toast_displayed(spa_page, text):
    expect(spa_page.get_by_role("alert").filter(has_text=text).first).to_be_visible()


@then(parsers.parse('"{text}" is displayed as a toast'))
def text_displayed_as_toast(spa_page, text):
    expect(spa_page.get_by_role("alert").filter(has_text=text).first).to_be_visible()


@then("the error message is displayed as a toast")
def error_toast_displayed(spa_page):
    expect(spa_page.get_by_role("alert").first).to_be_visible()


@then(parsers.parse("the player is navigated to /{destination}"))
def navigated_to(spa_page, destination):
    spa_page.wait_for_url(f"**/{destination}", timeout=5000)


@then("the player is navigated to the home screen")
def navigated_to_home(spa_page):
    spa_page.wait_for_url("**/", timeout=5000)


# ---------------------------------------------------------------------------
# Shared button / link assertions
# ---------------------------------------------------------------------------


@then(parsers.parse('a "{text}" button is visible'))
def button_visible(spa_page, text):
    expect(spa_page.get_by_role("button", name=text).first).to_be_visible(timeout=5000)


@then(parsers.parse('no "{text}" button is visible'))
def no_button_visible(spa_page, text):
    expect(spa_page.get_by_role("button", name=text)).to_have_count(0)


@then(parsers.parse('an "{text}" button is visible'))
def button_visible_an(spa_page, text):
    expect(spa_page.get_by_role("button", name=text).first).to_be_visible(timeout=5000)


@then(parsers.parse('a "{text}" link is visible'))
def link_visible(spa_page, text):
    expect(spa_page.get_by_role("link", name=text).first).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# Host disconnection banner — shared by game_play / result screens
# ---------------------------------------------------------------------------


@then('a banner displays "The host has disconnected. Waiting for reconnection..."')
def host_disconnect_banner(spa_page):
    expect(
        spa_page.get_by_role("status").filter(has_text="The host has disconnected")
    ).to_be_visible(timeout=5000)


@then("the banner is dismissed")
def banner_dismissed(spa_page):
    expect(
        spa_page.get_by_role("status").filter(has_text="The host has disconnected")
    ).to_have_count(0)
