"""Step definitions for host_reconnection.feature — host and player reconnection tests.

Tests disconnect/reconnect scenarios during various game phases,
verifying state restoration, banner display, and grace period behavior.
"""

import os
import re

from playwright.sync_api import expect
from pytest_bdd import given, parsers, scenarios, then, when

from integration.helpers import (
    assert_state_restored,
    configure_playlist,
    poll_until_room_deleted,
    set_handicap,
    set_nickname,
    setup_room_with_players,
    simulate_disconnect,
    simulate_reconnect,
    start_game_via_ui,
    submit_answer,
)

scenarios("../../features/integration/host_reconnection.feature")


# Grace-period polling budget, in seconds. Default = backend spec
# (room.feature: "the room is scheduled for deletion after 5 minutes" = 300s)
# plus a 60s margin so timing jitter does not flake the poll. Override via
# ATERUTA_GRACE_POLL_TIMEOUT when the backend is configured with a shorter
# grace.
_GRACE_POLL_TIMEOUT = int(os.environ.get("ATERUTA_GRACE_POLL_TIMEOUT", "360"))


@given(parsers.parse("a game is in progress with a host and {count:d} players"))
def game_in_progress_with_players(make_browser_player, ctx, count):
    setup_room_with_players(make_browser_player, ctx, count)
    configure_playlist(ctx.host)
    start_game_via_ui(ctx)


@when("the host disconnects")
def host_disconnects(ctx):
    simulate_disconnect(ctx.host)
    ctx.disconnected_player = ctx.host


@then("the game remains in playing phase")
def game_remains_playing(ctx):
    # Verify positively: other players' answer input is still enabled
    # (would be disabled / removed if the room transitioned out of playing).
    for page in ctx.other_player_pages():
        expect(page.get_by_role("searchbox", name="Song Title")).to_be_enabled(
            timeout=5000
        )


@then("other players can still submit answers")
def others_can_answer(ctx):
    for page in ctx.other_player_pages():
        expect(page.get_by_role("searchbox", name="Song Title")).to_be_enabled(
            timeout=5000
        )


@then(parsers.parse('a banner displays "{message}"'))
def banner_displays_message(ctx, message):
    for page in ctx.other_player_pages():
        expect(page.get_by_text(message)).to_be_visible(timeout=5000)


@given("the host disconnected during a game")
def host_disconnected_during_game(make_browser_player, ctx):
    setup_room_with_players(make_browser_player, ctx, 2)
    # Establish non-default nickname/handicap so the post-reconnect
    # "score, handicap, and nickname are restored" check is observable
    # rather than tautological (defaults vs defaults).
    set_nickname(ctx.host, "Captain")
    set_handicap(ctx.host, 5)
    configure_playlist(ctx.host)
    start_game_via_ui(ctx)
    ctx.captured_state[ctx.display_name_of(ctx.host)] = {
        "nickname": "Captain",
        "handicap": 5,
        "points": 0,
    }
    simulate_disconnect(ctx.host)
    ctx.disconnected_player = ctx.host


@given("the host has disconnected")
def host_has_disconnected(make_browser_player, ctx):
    if not ctx.host:
        setup_room_with_players(make_browser_player, ctx, 2)

    display_name = ctx.display_name_of(ctx.host)
    ctx.captured_state[display_name] = {
        "nickname": display_name,
        "handicap": 0,
        "points": 0,
    }
    simulate_disconnect(ctx.host)
    ctx.disconnected_player = ctx.host


@when("the host reconnects")
def host_reconnects(ctx):
    simulate_reconnect(ctx.host, ctx.room_code)


@then("the host can resume controlling the game")
def host_can_control(ctx):
    host_page = ctx.host.page
    expect(
        host_page.get_by_role("button", name=re.compile(r"Play|Close Answers|Extend"))
    ).to_be_visible(timeout=5000)


@then("the host's score, handicap, and nickname are restored")
def host_state_restored(ctx):
    assert_state_restored(ctx, ctx.host)


@then("the banner is dismissed")
def banner_dismissed(ctx):
    for page in ctx.other_player_pages():
        expect(page.get_by_text("The host has disconnected")).not_to_be_visible(
            timeout=10000
        )


@given("the host disconnected")
def host_disconnected(make_browser_player, ctx):
    setup_room_with_players(make_browser_player, ctx, 2)
    simulate_disconnect(ctx.host)
    ctx.disconnected_player = ctx.host


@when("the grace period expires without the host returning")
def grace_period_expires(ctx, make_player_client):
    # Poll the room status until it 404s, with a configurable budget,
    # instead of sleeping for a hard-coded magic duration. The actual
    # grace period is owned by the backend.
    client = make_player_client()
    deleted = poll_until_room_deleted(
        lambda code: client.check_room(code), ctx.room_code, _GRACE_POLL_TIMEOUT
    )
    assert deleted, (
        f"Room {ctx.room_code} was not deleted within {_GRACE_POLL_TIMEOUT}s; "
        "either grace period exceeds the polling budget or the backend "
        "did not clean up the room."
    )


@then("the room is deleted")
def room_is_deleted(ctx, make_player_client):
    client = make_player_client()
    resp = client.check_room(ctx.room_code)
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


@then("the room closure message is displayed as a toast to all remaining players")
def closure_toast(ctx):
    for page in ctx.other_player_pages():
        toast = page.get_by_role("alert").filter(has_text="closed")
        expect(toast.first).to_be_visible(timeout=10000)


# "a game is in progress" is defined in conftest.py


def _disconnect_first_nonhost(ctx):
    player = ctx.players[0]
    # Earn points before disconnect so the post-reconnect "score preserved"
    # check is observable instead of "0 == 0".
    submit_answer(player.page)
    # Handicap = 3s (set by game_in_progress_plain); wait past it + margin
    # so the answer is processed and the scoreboard reflects the new total.
    player.page.wait_for_timeout(5000)
    # Defaults: rankPoints[0] = 4 → first scorer earns 4 points.
    ctx.captured_state[ctx.display_name_of(player)] = {
        "nickname": "Mate",
        "handicap": 3,
        "points": 4,
    }
    simulate_disconnect(player)
    player.page.wait_for_timeout(1000)
    ctx.disconnected_player = player


@when("a non-host player disconnects")
def nonhost_disconnects(ctx):
    _disconnect_first_nonhost(ctx)


@when("the non-host player reconnects")
def nonhost_reconnects(ctx):
    simulate_reconnect(ctx.disconnected_player, ctx.room_code)


@when("a non-host player disconnects and reconnects")
def nonhost_disconnect_reconnect(ctx):
    _disconnect_first_nonhost(ctx)
    simulate_reconnect(ctx.disconnected_player, ctx.room_code)


@then("the player's score, handicap, and nickname are preserved")
def player_state_preserved(ctx):
    assert_state_restored(ctx, ctx.players[0])


@given(parsers.parse("a game has finished with {count:d} players"))
def game_finished_with_players(make_browser_player, ctx, count):
    setup_room_with_players(make_browser_player, ctx, count - 1)
    # Non-default state for both host and first non-host so either
    # disconnect target's "state preserved on the result screen" check is
    # observable.
    set_nickname(ctx.host, "Captain")
    set_handicap(ctx.host, 5)
    set_nickname(ctx.players[0], "Mate")
    set_handicap(ctx.players[0], 3)
    configure_playlist(ctx.host)
    start_game_via_ui(ctx)
    # Single round: play, have player[0] score, close, end game.
    host_page = ctx.host.page
    host_page.get_by_role("button", name="Play").click()
    host_page.wait_for_timeout(1000)
    submit_answer(ctx.players[0].page)
    # Wait past player[0]'s 3s handicap before close-answers cancels pending.
    ctx.players[0].page.wait_for_timeout(5000)
    host_page.get_by_role("button", name="Close Answers").click()
    host_page.wait_for_timeout(500)
    host_page.get_by_role("button", name="End Game").click()
    for page in ctx.all_pages():
        expect(page.get_by_text("Game Over!")).to_be_visible(timeout=10000)


@given("a player has disconnected from the result screen")
@given("a player disconnects from the result screen")
def player_disconnects_result(ctx):
    player = ctx.players[0]
    ctx.captured_state[ctx.display_name_of(player)] = {
        "nickname": "Mate",
        "handicap": 3,
        "points": 4,
    }
    simulate_disconnect(player)
    ctx.disconnected_player = player


@when("the player reconnects")
def player_reconnects(ctx):
    simulate_reconnect(ctx.disconnected_player, ctx.room_code)


@then("the player sees the result screen with all scores preserved")
def player_sees_results(ctx):
    player_page = ctx.disconnected_player.page
    expect(player_page.get_by_text("Game Over!")).to_be_visible(timeout=5000)
    assert_state_restored(ctx, ctx.disconnected_player)


@given("the host has disconnected from the result screen")
@given("the host disconnects from the result screen")
def host_disconnects_result(ctx):
    ctx.captured_state[ctx.display_name_of(ctx.host)] = {
        "nickname": "Captain",
        "handicap": 5,
        "points": 0,
    }
    simulate_disconnect(ctx.host)
    ctx.disconnected_player = ctx.host


# "the host reconnects" is defined above


@then("the host sees the result screen with all scores preserved")
def host_sees_results(ctx):
    host_page = ctx.host.page
    expect(host_page.get_by_text("Game Over!")).to_be_visible(timeout=5000)
    assert_state_restored(ctx, ctx.host)


@then("the host can return to lobby")
def host_can_return_to_lobby(ctx):
    host_page = ctx.host.page
    expect(host_page.get_by_role("button", name="Back to Lobby")).to_be_visible(
        timeout=5000
    )


@given("a room is in lobby phase")
def room_in_lobby_phase(make_browser_player, ctx):
    host = make_browser_player()
    ctx.room_code = host.create_room()
    ctx.host = host


@given("the host disconnected during lobby")
def host_disconnected_lobby(make_browser_player, ctx):
    if not ctx.host:
        room_in_lobby_phase(make_browser_player, ctx)
    host = ctx.host
    simulate_disconnect(host)
    ctx.disconnected_player = host


@given("another player is still in the room")
def another_player_in_room(make_browser_player, ctx):
    # The host has already been disconnected by host_disconnected_lobby.
    # Re-enable network briefly to let another player join the room,
    # then re-disconnect the host to restore the precondition.
    was_offline = ctx.host is ctx.disconnected_player
    if was_offline:
        ctx.host.context.set_offline(False)

    player = make_browser_player()
    player.join_room(ctx.room_code)
    ctx.players.append(player)
    for page in ctx.other_player_pages():
        expect(page.get_by_text(re.compile(r"Players\s*\(2\)"))).to_be_visible(
            timeout=10000
        )

    if was_offline:
        ctx.host.context.set_offline(True)
        ctx.host.page.wait_for_timeout(500)


# "the host reconnects" is defined above


@then("the host is shown as the host in the player list")
def host_shown_as_host(ctx):
    host_page = ctx.host.page
    own_row = (
        host_page.get_by_role("region", name="Players")
        .get_by_role("listitem")
        .filter(has=host_page.get_by_text("Player 1", exact=True))
    )
    expect(own_row).to_have_count(1)
    expect(own_row.get_by_text("Host", exact=True)).to_be_visible(timeout=5000)


@then("all players remain in the lobby")
def all_in_lobby(ctx):
    for page in ctx.all_pages():
        expect(page.get_by_text(re.compile(r"Room:"))).to_be_visible(timeout=5000)
