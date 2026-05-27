"""Step definitions for full_game.feature — complete game flow integration tests.

Tests the full lifecycle: room creation, player join, game rounds with
answers and scoring, duration extension, reveal, results, replay, and
early game end.
"""

import re

from playwright.sync_api import expect
from pytest_bdd import given, parsers, scenarios, then, when

from integration.helpers import (
    assert_player_at_rank_with_points,
    assert_player_score,
    configure_playlist,
    play_all_rounds_capture_reveals,
    set_rounds,
    setup_room_with_players,
    start_game_via_ui,
    submit_answer,
)

scenarios("../../features/integration/full_game.feature")


def _wait_for_round(pages, round_num, timeout=10000):
    """Wait until all pages display the given round number."""
    for page in pages:
        expect(page.get_by_text(re.compile(rf"Round\s+{round_num}\b"))).to_be_visible(
            timeout=timeout
        )


def _host_click(ctx, button_text, timeout=5000):
    """Click a button on the host's page."""
    ctx.host.page.get_by_role("button", name=button_text).click(timeout=timeout)


# "a host creates a room" is defined in conftest.py


@given(parsers.parse("{count:d} other players join the room"))
def players_join(make_browser_player, ctx, count):
    for i in range(count):
        player = make_browser_player()
        player.join_room(ctx.room_code)
        ctx.players.append(player)
        label = chr(ord("A") + i)
        ctx.named_players[label] = player
    total = count + 1
    for page in ctx.all_pages():
        expect(page.get_by_text(re.compile(rf"Players\s*\({total}\)"))).to_be_visible(
            timeout=10000
        )


@given(parsers.parse("the host selects a playlist with {count:d} songs"))
def host_selects_playlist(ctx, count):
    configure_playlist(ctx.host)


@given(parsers.parse("the host sets the rounds to {rounds:d}"))
def host_sets_rounds(ctx, rounds):
    set_rounds(ctx.host, rounds)


@when("the host starts the game")
def host_starts_game(ctx):
    _host_click(ctx, "Start Game")


@then(parsers.parse("all players see round {round_num:d}"))
def all_see_round(ctx, round_num):
    _wait_for_round(ctx.all_pages(), round_num)


@when("the host plays the song")
def host_plays_song(ctx):
    _host_click(ctx, "Play")
    ctx.host.page.wait_for_timeout(500)


@when(parsers.parse("player {n:d} submits the correct answer"))
def player_submits_correct(ctx, n):
    player_page = ctx.players[n - 1].page
    submit_answer(player_page)


@then(parsers.parse("player {n:d} earns {points:d} points"))
def player_earns_points(ctx, n, points):
    # Player {n} is the (n-1)th non-host player → display name "Player {n+1}".
    # "earns" is incremental: the scoreboard reflects the running cumulative.
    player_name = f"Player {n + 1}"
    ctx.expected_scores[player_name] = ctx.expected_scores.get(player_name, 0) + points
    assert_player_score(ctx.host.page, player_name, ctx.expected_scores[player_name])


@when("the host closes answers")
def host_closes_answers(ctx):
    _host_click(ctx, "Close Answers")
    ctx.host.page.wait_for_timeout(500)


@then("the correct song is revealed")
def correct_song_revealed(ctx):
    for page in ctx.all_pages():
        expect(page.get_by_role("region", name="Reveal")).to_be_visible(timeout=5000)


@when("the host advances to the next round")
def host_next_round(ctx):
    _host_click(ctx, "Next Round")
    ctx.host.page.wait_for_timeout(500)


@when("the host extends the duration")
def host_extends_duration(ctx):
    _host_click(ctx, "Extend")
    ctx.host.page.wait_for_timeout(500)


@then("all players see the updated duration")
def all_see_updated_duration(ctx):
    for page in ctx.all_pages():
        expect(page.get_by_text(re.compile(r"Duration:\s*\d+s"))).to_be_visible(
            timeout=5000
        )


@then("the correct song is revealed and no winners are shown")
def revealed_no_winners(ctx):
    for page in ctx.all_pages():
        expect(page.get_by_role("region", name="Reveal")).to_be_visible(timeout=5000)
        expect(page.get_by_text("No one got it")).to_be_visible(timeout=5000)


@when("the host proceeds to the results")
def host_proceeds_to_results(ctx):
    _host_click(ctx, "See Results")
    ctx.host.page.wait_for_timeout(1000)


# "all players are navigated to the result screen" is in conftest.py


@then(parsers.parse("player {n:d} is in 1st place with {points:d} points"))
def player_in_1st_place(ctx, n, points):
    player_name = f"Player {n + 1}"
    assert_player_at_rank_with_points(ctx.host.page, player_name, 1, points)


@then(parsers.parse("player {n:d} is in 2nd place with {points:d} points"))
def player_in_2nd_place(ctx, n, points):
    player_name = f"Player {n + 1}"
    assert_player_at_rank_with_points(ctx.host.page, player_name, 2, points)


@then(parsers.parse("player {n:d} is in 3rd place with {points:d} points"))
def player_in_3rd_place(ctx, n, points):
    player_name = f"Player {n + 1}"
    assert_player_at_rank_with_points(ctx.host.page, player_name, 3, points)


@then(parsers.parse("the host is in 3rd place with {points:d} points"))
def host_in_3rd_place(ctx, points):
    assert_player_at_rank_with_points(ctx.host.page, "Player 1", 3, points)


@given("a game has just finished")
def game_just_finished(make_browser_player, ctx):
    setup_room_with_players(make_browser_player, ctx, 2)
    configure_playlist(ctx.host)
    set_rounds(ctx.host, 10)
    start_game_via_ui(ctx)
    ctx.first_game_reveals = play_all_rounds_capture_reveals(ctx)
    ctx.host.page.get_by_role("button", name="See Results").click()
    for page in ctx.all_pages():
        expect(page.get_by_text("Game Over!")).to_be_visible(timeout=10000)


@when("the host returns to lobby")
def host_returns_to_lobby(ctx):
    _host_click(ctx, "Back to Lobby")
    ctx.host.page.wait_for_timeout(1000)


# "all players are navigated to the lobby screen" is in conftest.py


@when("the host starts a new game")
def host_starts_new_game(ctx):
    _host_click(ctx, "Start Game")
    ctx.host.page.wait_for_timeout(1000)


@then("all players start with 0 points")
def all_start_zero(ctx):
    # Verify each player's own row shows exactly 0 points on every page.
    total_players = len(ctx.players) + 1
    for page in ctx.all_pages():
        for i in range(1, total_players + 1):
            assert_player_score(page, f"Player {i}", 0)


@then("round 1 begins with a new song order")
def round_1_new_order(ctx):
    _wait_for_round(ctx.all_pages(), 1)
    assert ctx.first_game_reveals is not None, (
        "Expected first_game_reveals to be captured by the 'a game has just "
        "finished' Given step"
    )
    second_game_reveals = play_all_rounds_capture_reveals(ctx)
    assert len(second_game_reveals) == len(ctx.first_game_reveals), (
        f"Replay round count differs ({len(second_game_reveals)} vs "
        f"{len(ctx.first_game_reveals)}); shuffle comparison is not meaningful"
    )
    assert second_game_reveals != ctx.first_game_reveals, (
        f"Expected reshuffled song order on replay, got identical sequence: "
        f"{second_game_reveals!r}"
    )


# "a host creates a room" is in conftest.py
# "{count} other players join the room" is defined above


@given(parsers.parse("the host starts a game with {rounds:d} rounds"))
def host_starts_game_with_rounds(ctx, rounds):
    configure_playlist(ctx.host)
    set_rounds(ctx.host, rounds)
    _host_click(ctx, "Start Game")
    ctx.host.page.wait_for_timeout(1000)


@when(parsers.parse("the host plays the song in round {round_num:d}"))
def host_plays_song_in_round(ctx, round_num):
    _wait_for_round(ctx.all_pages(), round_num)
    _host_click(ctx, "Play")
    ctx.host.page.wait_for_timeout(500)


# "the host ends the game" is in conftest.py
# "all players are navigated to the result screen" is in conftest.py


@then("player 1's score reflects only round 1")
def player1_score_round1(ctx):
    # Player 1 in the feature = first non-host player = display "Player 2",
    # who scored 4 (default 1st place) in round 1 only.
    expect(ctx.host.page.get_by_text("Game Over!")).to_be_visible(timeout=5000)
    assert_player_score(ctx.host.page, "Player 2", 4)
