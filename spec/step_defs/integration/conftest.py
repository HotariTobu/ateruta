"""Integration test fixtures and shared step definitions.

Integration tests run E2E with Playwright against an externally running
server and SPA. For direct WebSocket interactions, the PlayerClient
from backend tests is reused.
"""

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect
from pytest_bdd import given, parsers, then, when

# Reuse PlayerClient for direct WS interactions in integration tests
from backend.helpers import PlayerClient

from integration.helpers import (
    BrowserPlayer,
    IntegrationContext,
    configure_playlist,
    set_handicap,
    set_nickname,
    setup_room_with_players,
    start_game_via_ui,
)
from frontend.helpers import get_token_response_json, utc_datetime
from frontend.musickit_mock import make_developer_token, configure_musickit_api_mock


_INTEGRATION_SONG_IDS = [f"song{i}" for i in range(1, 21)]


@pytest.fixture
def make_player_client(backend_url, backend_ws_url):
    """Factory for PlayerClient instances in integration tests."""
    clients: list[PlayerClient] = []

    def _make() -> PlayerClient:
        c = PlayerClient(backend_url, backend_ws_url)
        clients.append(c)
        c.init_session()
        c.connect()
        return c

    yield _make

    for c in clients:
        c.close()


@pytest.fixture
def make_browser_player(browser, frontend_url):
    """Factory to create BrowserPlayer instances, each with its own context."""
    contexts = []

    def _make() -> BrowserPlayer:
        ctx = browser.new_context()
        contexts.append(ctx)
        page = ctx.new_page()

        def prepare_page(page: Page):
            configure_musickit_api_mock(
                page, authorized=True, songs=_INTEGRATION_SONG_IDS
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

        player = BrowserPlayer(ctx, page, frontend_url, prepare_page=prepare_page)
        page.goto(frontend_url)
        page.wait_for_load_state("networkidle")
        return player

    yield _make

    for ctx in contexts:
        try:
            ctx.close()
        except PlaywrightError:
            pass  # Context may have been closed earlier in the scenario


@pytest.fixture
def ctx():
    """Per-scenario integration test context."""
    return IntegrationContext()


@pytest.fixture
def players_pages(ctx) -> list[Page]:
    """All player pages derived from the shared context."""
    return ctx.all_pages()


@given("a host creates a room")
def host_creates_room(make_browser_player, ctx):
    host = make_browser_player()
    ctx.room_code = host.create_room()
    ctx.host = host


@when("the host ends the game")
def host_ends_game(ctx):
    host_page = ctx.host.page
    close_btn = host_page.get_by_role("button", name="Close Answers")
    # Answers may already be closed (depends on scenario flow); attempt-and-ignore.
    try:
        close_btn.click(timeout=1000)
        host_page.wait_for_timeout(500)
    except PlaywrightError:
        pass
    host_page.get_by_role("button", name="End Game").click()
    host_page.wait_for_timeout(1000)


@given("a game is in progress")
def game_in_progress_plain(make_browser_player, ctx):
    if not ctx.host:
        setup_room_with_players(make_browser_player, ctx, 2)
        # Set non-default nickname/handicap for the first non-host so any
        # downstream "state preserved across reconnect" check is observable.
        set_nickname(ctx.players[0], "Mate")
        set_handicap(ctx.players[0], 3)
    configure_playlist(ctx.host)
    start_game_via_ui(ctx)
    ctx.host.page.get_by_role("button", name="Play").click()
    ctx.host.page.wait_for_timeout(500)


@then("all players see the result screen")
def all_see_results(players_pages: list[Page]):
    for p in players_pages:
        expect(p.get_by_text("Game Over!")).to_be_visible(timeout=5000)


@then(parsers.parse("all players are navigated to the result screen"))
def all_navigated_to_results(players_pages: list[Page]):
    for p in players_pages:
        expect(p.get_by_text("Game Over!")).to_be_visible(timeout=10000)


@then("all players are navigated to the lobby screen")
def all_navigated_to_lobby(players_pages: list[Page]):
    for p in players_pages:
        expect(p.get_by_text("Room:")).to_be_visible(timeout=5000)
