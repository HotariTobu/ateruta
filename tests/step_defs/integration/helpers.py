"""Shared helpers for integration tests.

BrowserPlayer wraps a Playwright browser context for a single player.
IntegrationContext holds mutable state shared across steps within a scenario.
Helper functions orchestrate common multi-step UI flows.

Frontend contract assumed by these helpers:
- Buttons: role=button with the visible label as accessible name
- Sliders: role=slider with accessible name ("Handicap", "Rounds", ...)
- Text inputs: role=textbox/searchbox with accessible name
- Scoreboard: role=region name="Scoreboard"; each player row is role=listitem
  with aria-posinset = rank position and an accessible name including the
  player's display name and "{N} points"
- Player roster (lobby): role=region name="Players"; each row role=listitem
- Reveal panel: role=region name="Reveal"
- Toasts: role=alert
"""

import re
import time

from playwright.sync_api import BrowserContext, Locator, Page, expect


class BrowserPlayer:
    """A player represented by their own browser context + page."""

    def __init__(self, context: BrowserContext, page: Page, frontend_url: str):
        self.context = context
        self.page = page
        self.frontend_url = frontend_url

    def goto_home(self):
        self.page.goto(self.frontend_url)

    def create_room(self) -> str:
        self.page.get_by_role("button", name="Create Room").click()
        self.page.wait_for_url("**/room/*", timeout=10000)
        url = self.page.url
        return url.split("/room/")[-1]

    def join_room(self, code: str):
        room_code_input = self.page.get_by_role("textbox", name="Room Code")
        room_code_input.fill("")
        for digit in code:
            room_code_input.press_sequentially(digit, delay=50)
        self.page.wait_for_url(f"**/room/{code}", timeout=10000)


class IntegrationContext:
    """Mutable state container shared across steps within a single scenario.

    Every integration scenario populates this context via Given steps.
    Shared Then steps (e.g. result screen checks) read from it.
    """

    def __init__(self):
        self.host: BrowserPlayer | None = None
        self.players: list[BrowserPlayer] = []  # non-host players
        self.room_code: str | None = None
        self.named_players: dict[str, BrowserPlayer] = {}  # "A", "B" -> player
        self.disconnected_player: BrowserPlayer | None = None
        self.error_player: BrowserPlayer | None = None
        # Captured pre-disconnect state, keyed by player display name.
        self.captured_state: dict[str, dict] = {}
        # Ordered reveal-panel texts from the first game, for replay comparison.
        self.first_game_reveals: list[str] | None = None
        # Running per-player expected scores keyed by display name. The "earns
        # X points" step is incremental, so the cumulative total against the
        # scoreboard is reconstructed here.
        self.expected_scores: dict[str, int] = {}
        # Number of non-host players that have submitted a scoring answer in
        # the current round. Used by "remaining players" assertions to slice
        # ctx.players into scorers vs non-scorers.
        self.scored_count: int = 0

    def all_pages(self) -> list[Page]:
        """Return all pages (host + non-host players)."""
        pages = []
        if self.host:
            pages.append(self.host.page)
        for p in self.players:
            pages.append(p.page)
        return pages

    def other_player_pages(self) -> list[Page]:
        """Return pages of non-host players only."""
        return [p.page for p in self.players]

    def display_name_of(self, browser_player: BrowserPlayer) -> str:
        """Resolve the auto-assigned display name (Player N) for a BrowserPlayer."""
        if self.host is browser_player:
            return "Player 1"
        idx = self.players.index(browser_player)
        return f"Player {idx + 2}"


# --- Disconnect / reconnect ---


def simulate_disconnect(browser_player: BrowserPlayer):
    """Drop the player's network connection at the browser-context level.

    Uses Playwright's set_offline(True) — both HTTP and WebSocket fail,
    and the page object stays alive so reconnection can restore via
    re-establishing the WebSocket (not a full client re-init).
    """
    browser_player.context.set_offline(True)
    browser_player.page.wait_for_timeout(500)


def simulate_reconnect(browser_player: BrowserPlayer, room_code: str):
    """Restore the network and navigate back to the room to trigger reconnection."""
    browser_player.context.set_offline(False)
    browser_player.page.goto(f"{browser_player.frontend_url}/room/{room_code}")
    browser_player.page.wait_for_load_state("networkidle")


# --- Lobby actions ---


def set_handicap(browser_player: BrowserPlayer, seconds: int):
    """Set the player's handicap via the lobby slider."""
    slider = browser_player.page.get_by_role("slider", name="Handicap")
    expect(slider).to_be_visible(timeout=5000)
    slider.fill(str(seconds))
    browser_player.page.wait_for_timeout(1500)  # debounce


def set_rounds(host: BrowserPlayer, rounds: int):
    """Set the number of rounds via the host's lobby slider.

    The rounds slider's max is the loaded song count, so a request for more
    rounds than the playlist has songs is silently clamped. Verify the final
    value matches the requested one so scenarios that rely on a specific
    round count surface the playlist-size mismatch instead of running with
    fewer rounds than intended.
    """
    slider = host.page.get_by_role("slider", name="Rounds")
    expect(slider).to_be_visible(timeout=5000)
    slider.fill(str(rounds))
    host.page.wait_for_timeout(500)
    actual = slider.input_value()
    assert int(actual) == rounds, (
        f"Could not set rounds to {rounds}; slider clamped to {actual}. "
        "The loaded playlist has fewer songs than the scenario requires."
    )


def set_room_settings(host: BrowserPlayer, rank_points: str, durations: str):
    """Set rank points and playback durations from the host's lobby settings."""
    rank_input = host.page.get_by_role("textbox", name="Rank points")
    expect(rank_input).to_be_visible(timeout=5000)
    rank_input.fill(rank_points)
    duration_input = host.page.get_by_role("textbox", name="Playback durations")
    expect(duration_input).to_be_visible(timeout=5000)
    duration_input.fill(durations)
    host.page.wait_for_timeout(1500)  # debounce


def configure_playlist(host: BrowserPlayer):
    """Pick a playlist from the host's lobby playlist search."""
    search_input = host.page.get_by_role("textbox", name="Search Playlist")
    expect(search_input).to_be_visible(timeout=5000)
    search_input.fill("test")
    host.page.wait_for_timeout(2000)
    first_playlist = (
        host.page.get_by_role("listbox", name="Playlists").get_by_role("option").first
    )
    expect(first_playlist).to_be_visible(timeout=5000)
    first_playlist.click()
    host.page.wait_for_timeout(2000)


def set_nickname(browser_player: BrowserPlayer, nickname: str):
    """Change the player's nickname via the lobby textbox."""
    nickname_input = browser_player.page.get_by_role("textbox", name="Nickname")
    expect(nickname_input).to_be_visible(timeout=5000)
    nickname_input.fill(nickname)
    browser_player.page.wait_for_timeout(1500)  # debounce


# --- Game actions ---


def submit_answer(page: Page, query: str = "Song") -> bool:
    """Type a search query and click the first suggestion.

    Returns True if a suggestion was clicked, False if no suggestion appeared.
    """
    search_field = page.get_by_role("searchbox", name="Song Title")
    expect(search_field).to_be_enabled(timeout=5000)
    search_field.fill("")
    search_field.type(query, delay=50)
    page.wait_for_timeout(500)
    suggestions = page.get_by_role("listbox", name="Suggestions").get_by_role("option")
    if suggestions.count() > 0:
        suggestions.first.click()
        page.wait_for_timeout(500)
        return True
    return False


def submit_wrong_answer(page: Page):
    """Submit a deliberately wrong answer that triggers lockout.

    Types a query that is unlikely to fuzzy-match any real song, then presses
    Enter to commit the submission regardless of suggestion list state.
    """
    search_field = page.get_by_role("searchbox", name="Song Title")
    expect(search_field).to_be_enabled(timeout=5000)
    search_field.fill("")
    search_field.type("zzqxnonexistent", delay=50)
    page.wait_for_timeout(300)
    search_field.press("Enter")
    page.wait_for_timeout(500)


# --- Setup / lifecycle ---


def setup_room_with_players(
    make_browser_player, ctx: IntegrationContext, player_count: int
):
    """Create a room with a host and the given number of additional players."""
    host = make_browser_player()
    ctx.room_code = host.create_room()
    ctx.host = host

    for i in range(player_count):
        player = make_browser_player()
        player.join_room(ctx.room_code)
        ctx.players.append(player)
        label = chr(ord("A") + i)
        ctx.named_players[label] = player

    total = player_count + 1
    for page in ctx.all_pages():
        expect(page.get_by_text(re.compile(rf"Players\s*\({total}\)"))).to_be_visible(
            timeout=10000
        )


def start_game_via_ui(ctx: IntegrationContext):
    """Click Start Game on the host's page and wait for round 1 on all pages."""
    assert ctx.host is not None
    ctx.host.page.get_by_role("button", name="Start Game").click()
    for page in ctx.all_pages():
        expect(page.get_by_text(re.compile(r"Round\s+1\b"))).to_be_visible(
            timeout=10000
        )


def finish_game_via_ui(ctx: IntegrationContext):
    """Play through one round and end the game, reaching the result screen."""
    assert ctx.host is not None
    host_page = ctx.host.page
    host_page.get_by_role("button", name="Play").click()
    host_page.wait_for_timeout(1000)
    host_page.get_by_role("button", name="Close Answers").click()
    host_page.wait_for_timeout(500)
    host_page.get_by_role("button", name="End Game").click()
    for page in ctx.all_pages():
        expect(page.get_by_text("Game Over!")).to_be_visible(timeout=10000)


def play_and_capture_revealed_song(ctx: IntegrationContext) -> str:
    """Play the current round, close answers, return reveal-panel text."""
    assert ctx.host is not None
    host_page = ctx.host.page
    host_page.get_by_role("button", name="Play").click()
    host_page.wait_for_timeout(1000)
    host_page.get_by_role("button", name="Close Answers").click()
    host_page.wait_for_timeout(500)
    reveal_panel = host_page.get_by_role("region", name="Reveal")
    expect(reveal_panel).to_be_visible(timeout=5000)
    return reveal_panel.inner_text()


def play_all_rounds_capture_reveals(ctx: IntegrationContext) -> list[str]:
    """Play through every remaining round, return reveal texts in play order.

    Loops play → close → capture reveal, then advances via "Next Round" until
    only "See Results" is offered (= last round). The final round's reveal is
    captured but the loop does not click "See Results" — the caller decides
    whether to transition to the finished phase.
    """
    assert ctx.host is not None
    host_page = ctx.host.page
    reveals: list[str] = []
    while True:
        reveals.append(play_and_capture_revealed_song(ctx))
        next_btn = host_page.get_by_role("button", name="Next Round")
        if next_btn.count() == 0:
            break
        next_btn.click()
        host_page.wait_for_timeout(500)
    return reveals


# --- Scoped scoreboard verification ---


def _find_scoreboard_row(page: Page, player_name: str) -> Locator:
    """Locate a specific player's row in the scoreboard region."""
    scoreboard = page.get_by_role("region", name="Scoreboard")
    return scoreboard.get_by_role("listitem").filter(
        has=page.get_by_text(player_name, exact=True)
    )


def assert_player_at_rank_with_points(
    page: Page, player_name: str, rank: int, points: int
):
    """Assert a player appears at the given rank position with the given points.

    Verifies via:
    - aria-posinset on the listitem row matching `rank`
    - the row containing exact text "{points} points"
    """
    scoreboard = page.get_by_role("region", name="Scoreboard")
    expect(scoreboard).to_be_visible(timeout=5000)
    row = _find_scoreboard_row(page, player_name)
    expect(row).to_have_count(1)
    expect(row).to_have_attribute("aria-posinset", str(rank), timeout=5000)
    expect(row.get_by_text(f"{points} points", exact=True)).to_be_visible(timeout=5000)


def assert_player_score(page: Page, player_name: str, points: int):
    """Assert a player has the given points on the scoreboard (rank not checked)."""
    row = _find_scoreboard_row(page, player_name)
    expect(row).to_have_count(1)
    expect(row.get_by_text(f"{points} points", exact=True)).to_be_visible(timeout=5000)


# --- State capture / restoration verification ---


def assert_state_restored(ctx: IntegrationContext, browser_player: BrowserPlayer):
    """Verify the browser_player's state matches what was captured pre-disconnect.

    Lobby phase uses the nickname textbox and handicap slider for verification;
    game and result phases use the scoreboard (nickname text + "+Ns" badge +
    "{N} points" row text). The identifier for locating the own scoreboard row
    is the captured nickname when present (it overrides the slot-based default
    once renamed), otherwise the slot-based display name.
    """
    page = browser_player.page
    display_name = ctx.display_name_of(browser_player)
    assert display_name in ctx.captured_state, (
        f"No captured state for {display_name}; the disconnect Given must "
        "record the player's pre-disconnect nickname/handicap/points in "
        "ctx.captured_state."
    )
    captured = ctx.captured_state[display_name]
    nickname_locator = page.get_by_role("textbox", name="Nickname")
    handicap_slider = page.get_by_role("slider", name="Handicap")
    in_lobby = nickname_locator.count() > 0

    if "nickname" in captured:
        if in_lobby:
            expect(nickname_locator).to_have_value(captured["nickname"], timeout=5000)
        else:
            scoreboard = page.get_by_role("region", name="Scoreboard")
            expect(
                scoreboard.get_by_text(captured["nickname"], exact=True).first
            ).to_be_visible(timeout=5000)

    if "handicap" in captured:
        if in_lobby:
            expect(handicap_slider).to_have_value(
                str(captured["handicap"]), timeout=5000
            )
        elif captured["handicap"] > 0:
            scoreboard = page.get_by_role("region", name="Scoreboard")
            expect(
                scoreboard.get_by_text(f"+{captured['handicap']}s", exact=False).first
            ).to_be_visible(timeout=5000)

    if "points" in captured:
        identifier = captured.get("nickname", display_name)
        own_row = _find_scoreboard_row(page, identifier)
        expect(own_row).to_have_count(1)
        expect(
            own_row.get_by_text(f"{captured['points']} points", exact=True)
        ).to_be_visible(timeout=5000)


# --- Polling helpers ---


def poll_until_room_deleted(
    check_room_callable, room_code: str, timeout_seconds: int
) -> bool:
    """Poll check_room until it returns 404, up to timeout_seconds.

    Returns True if the room was deleted within the budget, False otherwise.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        resp = check_room_callable(room_code)
        if resp.status_code == 404:
            return True
        time.sleep(2)
    return False
