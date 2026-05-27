"""Step definitions for multiplayer.feature — concurrent player interaction tests.

Tests room joining errors, lobby synchronization, concurrent answers with
scoring order, handicaps, auto-reveal, and player lifecycle during games.
"""

import re
from concurrent.futures import ThreadPoolExecutor

from playwright.sync_api import expect
from pytest_bdd import given, parsers, scenarios, then, when

from integration.helpers import (
    BrowserPlayer,
    assert_player_at_rank_with_points,
    assert_player_score,
    configure_playlist,
    finish_game_via_ui,
    set_handicap,
    set_nickname,
    set_room_settings,
    setup_room_with_players,
    simulate_disconnect,
    start_game_via_ui,
    submit_answer,
    submit_wrong_answer,
)

scenarios("../../features/integration/multiplayer.feature")


def _start_game_with_play(ctx):
    """Start the game and play the first song."""
    configure_playlist(ctx.host)
    start_game_via_ui(ctx)
    ctx.host.page.get_by_role("button", name="Play").click()
    ctx.host.page.wait_for_timeout(500)


def _attempt_room_code_entry(player: BrowserPlayer, code: str):
    """Type a room code on the home page (for error scenarios)."""
    room_code_input = player.page.get_by_role("textbox", name="Room Code")
    expect(room_code_input).to_be_visible(timeout=5000)
    room_code_input.fill("")
    for digit in code:
        room_code_input.press_sequentially(digit, delay=50)
    player.page.wait_for_timeout(2000)


@when("a player enters a room code that does not exist")
def enter_nonexistent_code(make_browser_player, ctx):
    player = make_browser_player()
    ctx.error_player = player
    _attempt_room_code_entry(player, "9999")


@then("an error is displayed")
def error_displayed(ctx):
    page = ctx.error_player.page if ctx.error_player else ctx.players[-1].page
    expect(page.get_by_role("alert").first).to_be_visible(timeout=5000)


@given("a room has a game in progress")
def room_game_in_progress(make_browser_player, ctx):
    setup_room_with_players(make_browser_player, ctx, 2)
    configure_playlist(ctx.host)
    start_game_via_ui(ctx)


@when("a non-participant enters the room code")
def nonparticipant_enters_code(make_browser_player, ctx):
    outsider = make_browser_player()
    ctx.error_player = outsider
    _attempt_room_code_entry(outsider, ctx.room_code)


@given("a room's game has finished")
def room_game_finished(make_browser_player, ctx):
    setup_room_with_players(make_browser_player, ctx, 2)
    configure_playlist(ctx.host)
    start_game_via_ui(ctx)
    finish_game_via_ui(ctx)


@given("a room has reached the maximum number of players")
def room_is_full(make_browser_player, ctx, make_player_client):
    host = make_browser_player()
    ctx.room_code = host.create_room()
    ctx.host = host
    # Fill remaining 19 slots via direct WS clients (faster than browsers)
    for _ in range(19):
        client = make_player_client()
        client.join_room(ctx.room_code)
        client.expect_event("room:settings")
    host.page.wait_for_timeout(2000)


@when("another player tries to join")
def another_tries_join(make_browser_player, ctx):
    outsider = make_browser_player()
    ctx.error_player = outsider
    _attempt_room_code_entry(outsider, ctx.room_code)


@then("an error is displayed indicating the room is full")
def room_full_error(ctx):
    alert = ctx.error_player.page.get_by_role("alert").filter(
        has_text=re.compile(r"full", re.I)
    )
    expect(alert.first).to_be_visible(timeout=5000)


# "a host creates a room" is defined in conftest.py


@when(parsers.parse("{count:d} players join the room using the room code"))
def n_players_join(make_browser_player, ctx, count):
    for i in range(count):
        player = make_browser_player()
        player.join_room(ctx.room_code)
        ctx.players.append(player)
        label = chr(ord("A") + i)
        ctx.named_players[label] = player
    ctx.host.page.wait_for_timeout(2000)


@then(parsers.parse("all {total:d} players appear in the player list"))
def all_appear_in_list(ctx, total):
    for page in ctx.all_pages():
        expect(page.get_by_text(re.compile(rf"Players\s*\({total}\)"))).to_be_visible(
            timeout=10000
        )


@then("each player has a unique auto-assigned nickname")
def unique_nicknames(ctx):
    host_page = ctx.host.page
    total = len(ctx.players) + 1
    seen: set[str] = set()
    for i in range(1, total + 1):
        name = f"Player {i}"
        row = (
            host_page.get_by_role("region", name="Players")
            .get_by_role("listitem")
            .filter(has=host_page.get_by_text(name, exact=True))
        )
        expect(row).to_have_count(1)
        assert name not in seen, f"Nickname {name} appears more than once in the roster"
        seen.add(name)
    assert len(seen) == total, f"Expected {total} unique nicknames, got {len(seen)}"


@given(parsers.parse("a room with {count:d} players"))
def room_with_n_players(make_browser_player, ctx, count):
    setup_room_with_players(make_browser_player, ctx, count - 1)


@when("a player changes their nickname")
def player_changes_nickname(ctx):
    set_nickname(ctx.players[0], "TestNick")


@then("all other players see the updated nickname in the player list")
def others_see_nickname(ctx):
    # The changing player is ctx.players[0]; every OTHER page (host + remaining
    # non-host players) must show "TestNick".
    other_pages = [ctx.host.page] + [p.page for p in ctx.players[1:]]
    for page in other_pages:
        expect(page.get_by_text("TestNick")).to_be_visible(timeout=5000)


@when(parsers.parse("a player sets their handicap to {seconds:d} seconds"))
def player_sets_handicap(ctx, seconds):
    set_handicap(ctx.players[0], seconds)


@then("all other players see the handicap badge next to that player's name")
def others_see_handicap(ctx):
    # The preceding "a player changes their nickname" step renamed
    # ctx.players[0] to "TestNick"; the row is now identified by that name,
    # not the slot-based default returned by display_name_of.
    changed_player_name = "TestNick"
    other_pages = [ctx.host.page] + [p.page for p in ctx.players[1:]]
    for page in other_pages:
        row = (
            page.get_by_role("region", name="Players")
            .get_by_role("listitem")
            .filter(has=page.get_by_text(changed_player_name, exact=True))
        )
        expect(row).to_have_count(1)
        expect(row.get_by_text(re.compile(r"\+\d+s"))).to_be_visible(timeout=5000)


@given("a room with a host and 2 other players")
def room_host_and_2(make_browser_player, ctx):
    setup_room_with_players(make_browser_player, ctx, 2)


@when(
    parsers.parse(
        'the host changes the rank points to "{rank_points}" and playback durations to "{durations}"'
    )
)
def host_changes_settings(ctx, rank_points, durations):
    set_room_settings(ctx.host, rank_points, durations)


@then("non-host players see the updated rank points and playback duration values")
def nonhost_see_settings(ctx):
    for player in ctx.players:
        page = player.page
        expect(page.get_by_text("4, 2")).to_be_visible(timeout=5000)
        expect(page.get_by_text("1, 2, 4")).to_be_visible(timeout=5000)


@given(parsers.parse("a game is in progress with {count:d} players and no handicaps"))
def game_with_n_no_handicap(make_browser_player, ctx, count):
    setup_room_with_players(make_browser_player, ctx, count - 1)
    _start_game_with_play(ctx)


@when("player A submits the correct answer")
def player_a_correct(ctx):
    submitted = submit_answer(ctx.named_players["A"].page)
    assert submitted, "player A's submission did not match any suggestion"


@when("player B submits the correct answer after player A")
def player_b_correct_after_a(ctx):
    submitted = submit_answer(ctx.named_players["B"].page)
    assert submitted, "player B's submission did not match any suggestion"


# Default rank points per backend: [4, 2, 1]
_DEFAULT_RANK_POINTS = [4, 2, 1]


@then("player A earns 1st place points")
def player_a_first(ctx):
    a_name = ctx.display_name_of(ctx.named_players["A"])
    assert_player_at_rank_with_points(ctx.host.page, a_name, 1, _DEFAULT_RANK_POINTS[0])


@then("player B earns 2nd place points")
def player_b_second(ctx):
    b_name = ctx.display_name_of(ctx.named_players["B"])
    assert_player_at_rank_with_points(ctx.host.page, b_name, 2, _DEFAULT_RANK_POINTS[1])


@given(parsers.parse("a game is in progress with {count:d} players"))
def game_with_n_players(make_browser_player, ctx, count):
    setup_room_with_players(make_browser_player, ctx, count - 1)
    _start_game_with_play(ctx)


@when("player A submits a wrong answer")
@when("player A submits a wrong answer and gets locked out")
def player_a_wrong_answer(ctx):
    player = ctx.named_players["A"]
    submit_wrong_answer(player.page)


@then("player A is locked out")
def player_a_locked_out(ctx):
    player = ctx.named_players["A"]
    expect(player.page.get_by_role("searchbox", name="Song Title")).to_be_disabled(
        timeout=5000
    )


@then("player B and player C can still submit answers")
def b_and_c_can_answer(ctx):
    for label in ["B", "C"]:
        assert label in ctx.named_players, (
            f"Scenario expects player {label} to exist but none was set up; "
            "check the Given step's player count."
        )
        page = ctx.named_players[label].page
        expect(page.get_by_role("searchbox", name="Song Title")).to_be_enabled(
            timeout=5000
        )


@given("players have configured their handicaps in the lobby")
@given("players set their handicaps in the lobby")
def players_set_handicaps(make_browser_player, ctx):
    host = make_browser_player()
    ctx.room_code = host.create_room()
    ctx.host = host

    for label in ["A", "B"]:
        player = make_browser_player()
        player.join_room(ctx.room_code)
        ctx.players.append(player)
        ctx.named_players[label] = player

    total = 3
    for page in ctx.all_pages():
        expect(page.get_by_text(re.compile(rf"Players\s*\({total}\)"))).to_be_visible(
            timeout=10000
        )


# "a game is in progress" is defined in conftest.py


@given(parsers.parse("player A has handicap of {seconds:d} seconds"))
def player_a_handicap(ctx, seconds):
    set_handicap(ctx.named_players["A"], seconds)


@given(parsers.parse("player B has handicap of {seconds:d} seconds"))
def player_b_handicap(ctx, seconds):
    set_handicap(ctx.named_players["B"], seconds)


@when("both players submit the correct answer at the same time")
def both_submit_simultaneously(ctx):
    # Use a thread pool so the two browser pages submit truly concurrently —
    # sequential submission would defeat the handicap-ordering test entirely.
    players = [ctx.named_players["A"], ctx.named_players["B"]]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit_answer, p.page) for p in players]
        for f in futures:
            f.result()
    ctx.host.page.wait_for_timeout(2000)


@when("player B submits the correct answer at the same time")
def player_b_correct_at_same_time(ctx):
    submitted = submit_answer(ctx.named_players["B"].page)
    assert submitted, "player B's simultaneous submission did not match any suggestion"
    ctx.host.page.wait_for_timeout(2000)


@then("player A scores before player B")
def a_scores_before_b(ctx):
    host_page = ctx.host.page
    scoreboard = host_page.get_by_role("region", name="Scoreboard")
    expect(scoreboard).to_be_visible(timeout=5000)
    a_name = ctx.display_name_of(ctx.named_players["A"])
    b_name = ctx.display_name_of(ctx.named_players["B"])
    a_row = scoreboard.get_by_role("listitem").filter(
        has=host_page.get_by_text(a_name, exact=True)
    )
    b_row = scoreboard.get_by_role("listitem").filter(
        has=host_page.get_by_text(b_name, exact=True)
    )
    a_pos = a_row.get_attribute("aria-posinset")
    b_pos = b_row.get_attribute("aria-posinset")
    assert a_pos is not None and b_pos is not None, (
        "Scoreboard rows are missing aria-posinset; rank ordering cannot be verified"
    )
    assert int(a_pos) < int(b_pos), (
        f"Expected player A (pos {a_pos}) to score before player B (pos {b_pos})"
    )


@given(parsers.parse("a game with {slots:d} scoring slots and {count:d} players"))
def game_with_scoring_slots(make_browser_player, ctx, slots, count):
    setup_room_with_players(make_browser_player, ctx, count - 1)
    # Configure rank points to a list of exactly `slots` entries (e.g., 3 → "4, 2, 1").
    # Defaults to descending integers starting at the slot count.
    rank_points = ", ".join(str(slots - i) for i in range(slots))
    set_room_settings(ctx.host, rank_points, "1, 2, 4")
    _start_game_with_play(ctx)


@given(parsers.parse('a game with rank points "{rank_points}" and {count:d} players'))
def game_with_rank_points(make_browser_player, ctx, rank_points, count):
    setup_room_with_players(make_browser_player, ctx, count - 1)
    set_room_settings(ctx.host, rank_points, "1, 2, 4")
    _start_game_with_play(ctx)


@when(parsers.parse("{count:d} players submit correct answers"))
def n_players_submit_correct(ctx, count):
    assert count <= len(ctx.players), (
        f"Scenario asks {count} players to submit, but only {len(ctx.players)} "
        "non-host players exist. Setup step did not create enough players."
    )
    for i in range(count):
        submitted = submit_answer(ctx.players[i].page)
        assert submitted, f"Player {i + 2}'s submission did not match any suggestion"
    ctx.scored_count = count


@then("the song is automatically revealed")
def song_auto_revealed(ctx):
    for page in ctx.all_pages():
        expect(page.get_by_role("region", name="Reveal")).to_be_visible(timeout=10000)


@then("the remaining players cannot score")
def remaining_cannot_score(ctx):
    # "Remaining" = the non-host players who did NOT submit (i.e. those after
    # the first ctx.scored_count in ctx.players). For each, the answer UI is
    # removed on reveal (game_answer.feature "Answer UI resets on reveal"),
    # so submission is impossible.
    remaining = ctx.players[ctx.scored_count :]
    assert remaining, (
        "Scenario expects remaining (non-scoring) players, but all non-host "
        "players submitted. Check the preceding 'N players submit correct "
        "answers' step's count."
    )
    for player in remaining:
        search = player.page.get_by_role("searchbox", name="Song Title")
        expect(search).to_have_count(0)


# "a game is in progress with {count} players" is defined above


@when("a non-host player disconnects")
def nonhost_disconnects(ctx):
    player = ctx.players[0]
    simulate_disconnect(player)
    ctx.host.page.wait_for_timeout(1000)


@then("the game continues with the remaining players")
def game_continues(ctx):
    host_page = ctx.host.page
    expect(host_page.get_by_text(re.compile(r"Round\s+\d+"))).to_be_visible(
        timeout=5000
    )
    for player in ctx.players[1:]:
        expect(player.page.get_by_text(re.compile(r"Round\s+\d+"))).to_be_visible(
            timeout=5000
        )


# "a game is in progress with {count} players" is defined above


@given("player A has earned points")
def player_a_has_points(ctx):
    player = ctx.named_players.get("A", ctx.players[0])
    submitted = submit_answer(player.page)
    assert submitted, "player A's setup submission did not match any suggestion"


@when("player A disconnects")
def player_a_disconnects(ctx):
    player = ctx.named_players.get("A", ctx.players[0])
    simulate_disconnect(player)
    ctx.host.page.wait_for_timeout(1000)


# "the host ends the game" is in conftest.py


@then("the result screen shows player A's score")
def result_shows_a_score(ctx):
    host_page = ctx.host.page
    expect(host_page.get_by_text("Game Over!")).to_be_visible(timeout=5000)
    a_name = ctx.display_name_of(ctx.named_players.get("A", ctx.players[0]))
    assert_player_score(host_page, a_name, _DEFAULT_RANK_POINTS[0])
