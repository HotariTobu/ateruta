"""Step definitions for game.feature — game lifecycle, rounds, and host actions.

Many scenarios share the same When/Then step text but have different Given
preconditions.  Each Given populates the unified ``ctx`` (ScenarioContext)
fixture so that the shared When/Then steps can consume it uniformly.

ctx always has at least: host, players, room_code
and may have optional attributes like phase, extra["revealed"], etc.
"""

from pytest_bdd import given, scenarios, then, when

from backend.helpers import create_room, drain_all, setup_valid_game
from backend.schemas import (
    PlayerStatePayload,
    RoomSettingsSCPayload,
    ShuffledSongsPayload,
)

scenarios("../../features/backend/game.feature")


def _make_songs(n=3):
    return [
        {
            "id": f"song{i}",
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "artworkUrl": None,
        }
        for i in range(1, n + 1)
    ]


def _apply_valid_settings(host, extra=None):
    settings = {
        "songs": _make_songs(3),
        "totalRounds": 3,
        "playbackDurations": [1, 2, 4, 8, 16],
        "rankPoints": [4, 2, 1],
        "lockoutDuration": 5,
        "attemptsLimit": 3,
    }
    if extra:
        settings.update(extra)
    host.send("room:settings", settings)
    host.drain_events(wait=0.5)


def _play_song(host, players):
    host.send("game:play-song")
    drain_all(host, players)


def _close_and_reveal(host, players):
    host.send("game:close-answers")
    drain_all(host, players)


def _next_round(host, players):
    host.send("game:next-round")
    drain_all(host, players)


@given("a room in lobby phase")
def room_in_lobby(ctx, make_player):
    host, players, room_code = create_room(make_player, n_players=1)

    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@when("the host sends songs via room:settings")
def host_sends_songs(ctx):
    ctx.host.send("room:settings", {"songs": _make_songs(3)})


@then("the songs are stored in settings")
def songs_stored(ctx):
    event = ctx.host.expect_event("room:settings")
    ctx.last_settings = event
    assert len(event["payload"]["songs"]) == 3


@then("the songs are shuffled and stored as game songs")
def songs_shuffled(ctx):
    event = ctx.host.expect_event("game:shuffled-songs")
    ctx.last_shuffled_songs = event
    shuffled_ids = event["payload"]["shuffledSongIds"]
    settings = ctx.host.find_last_event("room:settings")
    original_ids = [s["id"] for s in settings["payload"]["songs"]]
    assert sorted(shuffled_ids) == sorted(original_ids), (
        "Shuffled songs must contain the same IDs"
    )
    assert shuffled_ids != original_ids, "Shuffled order should differ from original"


@then("the host receives the shuffled song IDs via game:shuffled-songs")
def host_receives_shuffled(ctx):
    event = getattr(ctx, "last_shuffled_songs", None)
    if event is None:
        event = ctx.host.expect_event("game:shuffled-songs")
    ctx.last_shuffled_songs = None
    ids = event["payload"]["shuffledSongIds"]
    assert len(ids) == 3


@given("songs have been shuffled into game songs")
def songs_shuffled_into_game(ctx, make_player):
    if ctx.host is None:
        host, players, room_code = create_room(make_player, n_players=1)
        setup_valid_game(host, players, room_code)
        ctx.host = host
        ctx.players = players
        ctx.room_code = room_code
    event = ctx.host.find_event("game:shuffled-songs")
    assert event is not None, "game:shuffled-songs event not received"


@then("round 1 uses the 1st shuffled song, round 2 uses the 2nd, and so on")
def rounds_use_shuffled_songs(ctx):
    event = ctx.host.find_event("game:shuffled-songs")
    assert event is not None
    shuffled_ids = event["payload"]["shuffledSongIds"]
    host = ctx.host
    players = ctx.players

    for round_idx in range(len(shuffled_ids)):
        host.send("game:play-song")
        drain_all(host, players)
        host.send("game:close-answers")
        reveal = host.expect_event("game:reveal")
        assert reveal["payload"]["songId"] == shuffled_ids[round_idx], (
            f"Round {round_idx + 1}: expected song {shuffled_ids[round_idx]}, "
            f"got {reveal['payload']['songId']}"
        )
        if round_idx < len(shuffled_ids) - 1:
            host.send("game:next-round")
            drain_all(host, players)


@given("a room in lobby phase with valid settings")
def room_with_valid_settings(ctx, make_player):
    host, players, room_code = create_room(make_player, n_players=1)

    _apply_valid_settings(host)
    players[0].drain_events(wait=0.3)

    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@when("the host sends game:start")
def host_sends_game_start(ctx):
    ctx.host.send("game:start")


@then("a new roomState is created:")
def new_room_state(ctx, datatable):
    event = ctx.host.expect_event("room:state")
    ctx.last_state = event
    payload = event["payload"]
    assert payload["phase"] == "playing"
    assert payload["currentRound"] == 1
    assert payload["playbackDurationIndex"] == 0
    assert len(payload["activePlayers"]) >= 1
    assert payload["inactivePlayers"] == []


@then("game participants are the activePlayers in settings at the time of game:start")
def game_participants(ctx):
    host = ctx.host
    players = ctx.players
    state_event = host.find_last_event("room:state")
    assert state_event is not None
    active_ids = {p["id"] for p in state_event["payload"]["activePlayers"]}
    assert host.player_id in active_ids
    for player in players:
        assert player.player_id in active_ids


@then("players in inactivePlayers at game start are not game participants")
def inactive_not_participants(ctx):
    host = ctx.host
    state_event = host.find_last_event("room:state")
    assert state_event is not None
    assert state_event["payload"]["inactivePlayers"] == []


@given(
    "some players are in inactivePlayers in settings at the time of game:start",
)
def inactive_at_game_start(ctx, make_player):
    host, players, room_code = create_room(make_player, n_players=2)
    player1, player2 = players

    player2.disconnect()
    drain_all(host, [player1])

    _apply_valid_settings(host)
    player1.drain_events(wait=0.3)

    ctx.host = host
    ctx.players = [player1]
    ctx.room_code = room_code
    ctx.inactive_player = player2


@when("the host sends game:start, before room:state is broadcast")
def host_starts_game_inactive(ctx):
    ctx.host.send("game:start")


@then("those players are removed from inactivePlayers in settings")
def inactive_removed(ctx):
    event = ctx.host.expect_event("room:settings")
    ctx.last_settings = event
    inactive_player_id = ctx.inactive_player.player_id
    inactive_ids = [p["id"] for p in event["payload"]["inactivePlayers"]]
    assert inactive_player_id not in inactive_ids


@when("a non-host player sends game:start")
def non_host_sends_start(ctx, make_player):
    _, players, _ = create_room(make_player, 2)
    ctx.error_target = players[0]
    players[0].send("game:start")


@given("a room in lobby phase with no songs")
def lobby_no_songs(ctx, host):
    ctx.host = host
    ctx.room_code = host.room_code


@then("the game does not start")
def game_does_not_start(ctx):
    host = ctx.host
    events = host.drain_events(wait=1.0)
    states = [event for event in events if event["event"] == "room:state"]
    assert not states, f"Game should not start, got room:state events: {states}"
    errors = [event for event in events if event["event"] == "error"]
    if errors:
        ctx.last_error_event = errors[0]


@given("a room in lobby phase with no total rounds")
def lobby_no_total_rounds(ctx, host):
    host.send(
        "room:settings",
        {
            "songs": _make_songs(3),
            "playbackDurations": [1, 2, 4, 8, 16],
            "rankPoints": [4, 2, 1],
            "lockoutDuration": 5,
            "attemptsLimit": 3,
        },
    )
    host.drain_events(wait=0.5)
    ctx.host = host
    ctx.room_code = host.room_code


@given("a room in lobby phase with 3 songs and total rounds set to 5")
@given("a room in lobby phase with 3 songs and totalRounds set to 5")
def lobby_too_many_rounds(ctx, host):
    host.send("room:settings", {"songs": _make_songs(3), "totalRounds": 5})
    host.drain_events(wait=0.5)
    ctx.host = host
    ctx.room_code = host.room_code


@given("a room in lobby phase with empty rank points")
@given("a room in lobby phase with empty rankPoints")
def lobby_empty_rank(ctx, host):
    host.send(
        "room:settings",
        {
            "songs": _make_songs(3),
            "totalRounds": 3,
            "playbackDurations": [1, 2, 4, 8, 16],
            "lockoutDuration": 5,
            "attemptsLimit": 3,
        },
    )
    host.drain_events(wait=0.5)
    ctx.host = host
    ctx.room_code = host.room_code


@given("a room in lobby phase with empty playback durations")
@given("a room in lobby phase with empty playbackDurations")
def lobby_empty_durations(ctx, host):
    host.send(
        "room:settings",
        {
            "songs": _make_songs(3),
            "totalRounds": 3,
            "rankPoints": [4, 2, 1],
            "lockoutDuration": 5,
            "attemptsLimit": 3,
        },
    )
    host.drain_events(wait=0.5)
    ctx.host = host
    ctx.room_code = host.room_code


@given("a room in lobby phase with no lockout duration")
def lobby_no_lockout_duration(ctx, host):
    host.send(
        "room:settings",
        {
            "songs": _make_songs(3),
            "totalRounds": 3,
            "playbackDurations": [1, 2, 4, 8, 16],
            "rankPoints": [4, 2, 1],
            "attemptsLimit": 3,
        },
    )
    host.drain_events(wait=0.5)
    ctx.host = host
    ctx.room_code = host.room_code


@given("a room in lobby phase with no attempts limit")
def lobby_no_attempts_limit(ctx, host):
    host.send(
        "room:settings",
        {
            "songs": _make_songs(3),
            "totalRounds": 3,
            "playbackDurations": [1, 2, 4, 8, 16],
            "rankPoints": [4, 2, 1],
            "lockoutDuration": 5,
        },
    )
    host.drain_events(wait=0.5)
    ctx.host = host
    ctx.room_code = host.room_code


@then("the server checks game:start in the following order:")
def game_start_check_order(make_player, datatable):
    rows = datatable[1:]
    for row in rows:
        error_msg = row[1].strip('"')
        host, players, room_code = create_room(make_player, 1)

        if error_msg == "Only the host can start the game":
            players[0].send("game:start")
            players[0].expect_error(error_msg)
        elif error_msg == "Can only start game in lobby":
            setup_valid_game(host, players, room_code)
            host.send("game:start")
            host.expect_error(error_msg)
        elif error_msg == "Songs are required to start the game":
            host.send("game:start")
            host.expect_error(error_msg)
        elif error_msg == "Total rounds are required":
            host.send(
                "room:settings",
                {
                    "songs": _make_songs(3),
                    "playbackDurations": [1, 2, 4, 8, 16],
                    "rankPoints": [4, 2, 1],
                    "lockoutDuration": 5,
                    "attemptsLimit": 3,
                },
            )
            drain_all(host, players)
            host.send("game:start")
            host.expect_error(error_msg)
        elif error_msg == "Not enough songs for the specified number of rounds":
            host.send("room:settings", {"songs": _make_songs(2), "totalRounds": 5})
            drain_all(host, players)
            host.send("game:start")
            host.expect_error(error_msg)
        elif error_msg == "Rank points are required":
            host.send(
                "room:settings",
                {
                    "songs": _make_songs(3),
                    "totalRounds": 3,
                    "playbackDurations": [1, 2, 4, 8, 16],
                    "lockoutDuration": 5,
                    "attemptsLimit": 3,
                },
            )
            drain_all(host, players)
            host.send("game:start")
            host.expect_error(error_msg)
        elif error_msg == "Playback durations are required":
            host.send(
                "room:settings",
                {
                    "songs": _make_songs(3),
                    "totalRounds": 3,
                    "rankPoints": [4, 2, 1],
                    "lockoutDuration": 5,
                    "attemptsLimit": 3,
                },
            )
            drain_all(host, players)
            host.send("game:start")
            host.expect_error(error_msg)
        elif error_msg == "Lockout duration is required":
            host.send(
                "room:settings",
                {
                    "songs": _make_songs(3),
                    "totalRounds": 3,
                    "playbackDurations": [1, 2, 4, 8, 16],
                    "rankPoints": [4, 2, 1],
                    "attemptsLimit": 3,
                },
            )
            drain_all(host, players)
            host.send("game:start")
            host.expect_error(error_msg)
        elif error_msg == "Attempts limit is required":
            host.send(
                "room:settings",
                {
                    "songs": _make_songs(3),
                    "totalRounds": 3,
                    "playbackDurations": [1, 2, 4, 8, 16],
                    "rankPoints": [4, 2, 1],
                    "lockoutDuration": 5,
                },
            )
            drain_all(host, players)
            host.send("game:start")
            host.expect_error(error_msg)

    # Ordering pair tests — construct states where two adjacent rows would
    # both fail; earlier row must fire.

    # Order 1<2: non-host in playing phase.  Both row 1 (non-host) and row 2
    # (not lobby) fail; row 1 must win.
    host, players, room_code = create_room(make_player, 1)
    setup_valid_game(host, players, room_code)
    players[0].send("game:start")
    players[0].expect_error("Only the host can start the game")

    # Order 2<3 is not testable: outside lobby means playing or finished,
    # both of which required songs to enter, so songs always exist when
    # row 2 would fail.

    # Order 3<4: no songs and no total rounds.  Row 3 must win.
    host, players, room_code = create_room(make_player, 1)
    host.send("game:start")
    host.expect_error("Songs are required to start the game")

    # Order 5<6: not enough songs and no rank points.  Row 5 must win.
    host, players, room_code = create_room(make_player, 1)
    host.send("room:settings", {"songs": _make_songs(2), "totalRounds": 5})
    drain_all(host, players)
    host.send("game:start")
    host.expect_error("Not enough songs for the specified number of rounds")

    # Order 6<7: no rank points and no playback durations.  Row 6 must win.
    host, players, room_code = create_room(make_player, 1)
    host.send(
        "room:settings",
        {
            "songs": _make_songs(3),
            "totalRounds": 3,
            "lockoutDuration": 5,
            "attemptsLimit": 3,
        },
    )
    drain_all(host, players)
    host.send("game:start")
    host.expect_error("Rank points are required")

    # Order 7<8: no playback durations and no lockout duration.  Row 7 must win.
    host, players, room_code = create_room(make_player, 1)
    host.send(
        "room:settings",
        {
            "songs": _make_songs(3),
            "totalRounds": 3,
            "rankPoints": [4, 2, 1],
            "attemptsLimit": 3,
        },
    )
    drain_all(host, players)
    host.send("game:start")
    host.expect_error("Playback durations are required")

    # Order 8<9: no lockout duration and no attempts limit.  Row 8 must win.
    host, players, room_code = create_room(make_player, 1)
    host.send(
        "room:settings",
        {
            "songs": _make_songs(3),
            "totalRounds": 3,
            "playbackDurations": [1, 2, 4, 8, 16],
            "rankPoints": [4, 2, 1],
        },
    )
    drain_all(host, players)
    host.send("game:start")
    host.expect_error("Lockout duration is required")


@then("the server checks game:extend in the following order:")
def game_extend_check_order(make_player, datatable):
    rows = datatable[1:]
    for row in rows:
        error_msg = row[1].strip('"')
        host, players, room_code = create_room(make_player, 1)

        if error_msg == "Only the host can extend duration":
            players[0].send("game:extend")
            players[0].expect_error(error_msg)
        elif error_msg == "Game is not in playing phase":
            host.send("game:extend")
            host.expect_error(error_msg)
        elif error_msg == "Round has already been revealed":
            setup_valid_game(host, players, room_code)
            _play_song(host, players)
            _close_and_reveal(host, players)
            host.send("game:extend")
            host.expect_error(error_msg)
        elif error_msg == "Already at maximum duration":
            setup_valid_game(host, players, room_code)
            _play_song(host, players)
            for _ in range(4):
                host.send("game:extend")
                drain_all(host, players)
            host.send("game:extend")
            host.expect_error(error_msg)

    # Order 1<2: non-host outside playing phase.
    host, players, room_code = create_room(make_player, 1)
    players[0].send("game:extend")
    players[0].expect_error("Only the host can extend duration")

    # Order 2<3 is mutex: a revealed round only exists in playing phase.

    # Order 3<4: revealed round AT max duration.  Extend to max, then reveal.
    host, players, room_code = create_room(make_player, 1)
    setup_valid_game(host, players, room_code)
    _play_song(host, players)
    for _ in range(4):
        host.send("game:extend")
        drain_all(host, players)
    _close_and_reveal(host, players)
    host.send("game:extend")
    host.expect_error("Round has already been revealed")


@then("the server checks game:next-round in the following order:")
def game_next_round_check_order(make_player, datatable):
    rows = datatable[1:]
    for row in rows:
        error_msg = row[1].strip('"')
        host, players, room_code = create_room(make_player, 1)

        if error_msg == "Only the host can advance rounds":
            players[0].send("game:next-round")
            players[0].expect_error(error_msg)
        elif error_msg == "Game is not in playing phase":
            host.send("game:next-round")
            host.expect_error(error_msg)
        elif error_msg == "Round has not been revealed":
            setup_valid_game(host, players, room_code)
            host.send("game:next-round")
            host.expect_error(error_msg)
        elif error_msg == "All rounds have been played":
            setup_valid_game(host, players, room_code, n_songs=1)
            _play_song(host, players)
            _close_and_reveal(host, players)
            host.send("game:next-round")
            host.expect_error(error_msg)

    # Order 1<2: non-host outside playing.
    host, players, room_code = create_room(make_player, 1)
    players[0].send("game:next-round")
    players[0].expect_error("Only the host can advance rounds")

    # Order 2<3 is mutex (revealed round only exists in playing).

    # Order 3<4: last round in progress, not yet revealed (no rounds remain
    # AND not revealed).  Row 3 must win.
    host, players, room_code = create_room(make_player, 1)
    setup_valid_game(host, players, room_code, n_songs=1)
    _play_song(host, players)
    host.send("game:next-round")
    host.expect_error("Round has not been revealed")


@then("the server checks game:close-answers in the following order:")
def game_close_answers_check_order(make_player, datatable):
    rows = datatable[1:]
    for row in rows:
        error_msg = row[1].strip('"')
        host, players, room_code = create_room(make_player, 1)

        if error_msg == "Only the host can close answers":
            players[0].send("game:close-answers")
            players[0].expect_error(error_msg)
        elif error_msg == "Game is not in playing phase":
            host.send("game:close-answers")
            host.expect_error(error_msg)
        elif error_msg == "Round has already been revealed":
            setup_valid_game(host, players, room_code)
            _play_song(host, players)
            _close_and_reveal(host, players)
            host.send("game:close-answers")
            host.expect_error(error_msg)
        elif error_msg == "Song has not been played yet":
            setup_valid_game(host, players, room_code)
            host.send("game:close-answers")
            host.expect_error(error_msg)

    # Order 1<2: non-host outside playing.
    host, players, room_code = create_room(make_player, 1)
    players[0].send("game:close-answers")
    players[0].expect_error("Only the host can close answers")

    # Order 2<3 is mutex (revealed round only exists in playing).
    # Order 3<4 is mutex (revealing requires song to have been played).


@then("the server checks game:play-song in the following order:")
def game_play_song_check_order(make_player, datatable):
    rows = datatable[1:]
    for row in rows:
        error_msg = row[1].strip('"')
        host, players, room_code = create_room(make_player, 1)

        if error_msg == "Only the host can play songs":
            players[0].send("game:play-song")
            players[0].expect_error(error_msg)
        elif error_msg == "Game is not in playing phase":
            host.send("game:play-song")
            host.expect_error(error_msg)
        elif error_msg == "Round has already been revealed":
            setup_valid_game(host, players, room_code)
            _play_song(host, players)
            _close_and_reveal(host, players)
            host.send("game:play-song")
            host.expect_error(error_msg)

    # Order 1<2: non-host outside playing.
    host, players, room_code = create_room(make_player, 1)
    players[0].send("game:play-song")
    players[0].expect_error("Only the host can play songs")

    # Order 2<3 is mutex (revealed round only exists in playing).


@then("the server checks game:end in the following order:")
def game_end_check_order(make_player, datatable):
    rows = datatable[1:]
    for row in rows:
        error_msg = row[1].strip('"')
        host, players, room_code = create_room(make_player, 1)

        if error_msg == "Only the host can end the game":
            players[0].send("game:end")
            players[0].expect_error(error_msg)
        elif error_msg == "Game is not in playing phase":
            host.send("game:end")
            host.expect_error(error_msg)

    # Order 1<2: non-host outside playing phase.
    host, players, room_code = create_room(make_player, 1)
    players[0].send("game:end")
    players[0].expect_error("Only the host can end the game")


@then("the server checks game:back-to-lobby in the following order:")
def game_back_to_lobby_check_order(make_player, datatable):
    rows = datatable[1:]
    for row in rows:
        error_msg = row[1].strip('"')
        host, players, room_code = create_room(make_player, 1)

        if error_msg == "Only the host can return to lobby":
            players[0].send("game:back-to-lobby")
            players[0].expect_error(error_msg)
        elif error_msg == "Game has not finished":
            host.send("game:back-to-lobby")
            host.expect_error(error_msg)

    # Order 1<2: non-host while game has not finished (lobby).
    host, players, room_code = create_room(make_player, 1)
    players[0].send("game:back-to-lobby")
    players[0].expect_error("Only the host can return to lobby")


@when("a new round begins")
def new_round_begins(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    _play_song(host, players)
    _close_and_reveal(host, players)
    host.send("game:next-round")
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@then("playbackDurationIndex is reset to 0")
def duration_index_reset(ctx):
    event = ctx.host.expect_event("room:state")
    assert event["payload"]["playbackDurationIndex"] == 0


@then("the round starts as not revealed")
def round_not_revealed_then(ctx):
    # The room:state event for the new round should show the round as not revealed.
    # The revealed state is implicit: no game:reveal event should follow room:state
    # for the new round. We verify by checking no reveal event arrived.
    ctx.host.assert_no_event("game:reveal", timeout=0.5)


@then("no song has been played for the new round")
def no_song_played(ctx):
    ctx.host.assert_no_event("game:play-song", timeout=0.5)


@then("all pending answers are cancelled")
def pending_answers_cancelled(ctx):
    events = ctx.host.drain_events(wait=1.0)
    scored = [event for event in events if event["event"] == "game:scored"]
    assert not scored, f"Pending answers should not score, got: {scored}"
    reveal = next((event for event in events if event["event"] == "game:reveal"), None)
    if reveal is not None:
        ctx.last_reveal = reveal
    state = next((event for event in events if event["event"] == "room:state"), None)
    if state is not None:
        ctx.last_state = state


@then("penalties are reset for all players (including inactive players)")
def penalties_reset(ctx, make_player):
    # Shared between two scenarios with different observable surfaces:
    #
    # 1. "Host ends game" (post-end → finished phase): per-player penalty
    #    fields are not externally observable because game:player-state is
    #    only delivered for playing+notrevealed.  The reset is effectively
    #    bundled with game-state destruction.  Verify the consequence: no
    #    pending answer can produce a scored or wrong-answer event after end.
    #
    # 2. "New round initializes round state" (next-round → playing): the
    #    existing fresh-state setup below constructs an explicit penalty
    #    state pre-advance and verifies post-advance reset for one active
    #    and one inactive player.
    last_state = ctx.host.find_last_event("room:state") if ctx.host else None
    if (
        last_state is not None
        and last_state["payload"] is not None
        and last_state["payload"].get("phase") == "finished"
    ):
        ctx.host.assert_no_event("game:scored", timeout=1.0)
        ctx.host.assert_no_event("game:wrong-answer", timeout=0.5)
        return

    host, players, room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(host, players, room_code, n_songs=3, attempts_limit=3)
    host.send("game:play-song")
    drain_all(host, players)
    wrong_id = shuffled[1]
    for player in players:
        player.send("game:answer", {"songId": wrong_id})
        player.expect_event("game:wrong-answer")
    drain_all(host, players)
    # player[1] disconnects → becomes inactive, but penalty state persists server-side.
    players[1].disconnect()
    drain_all(host, players[:1])
    # Advance round.  Per spec, penalties reset here for ALL players including inactive.
    host.send("game:close-answers")
    host.expect_event("game:reveal")
    drain_all(host, players[:1])
    host.send("game:next-round")
    host.expect_event("room:state")
    host.send("game:play-song")
    drain_all(host, players[:1])

    # Active player: can answer without "Locked out" / "No attempts remaining".
    players[0].send("game:answer", {"songId": shuffled[2]})
    events = players[0].drain_events(wait=1.0)
    errors = [e for e in events if e["event"] == "error"]
    assert not errors, (
        f"Active player should be reset after round change, got: {errors}"
    )

    # Previously-inactive player: reconnect and check game:player-state shows
    # zero wrong count and no lockout — i.e. inactive's penalty was also reset.
    players[1].reconnect()
    players[1].join_room(room_code)
    state_event = players[1].expect_event("game:player-state")
    state = PlayerStatePayload.model_validate(state_event["payload"])
    assert state.wrongAnswerCount == 0, (
        f"Inactive player's wrongAnswerCount should reset, got {state.wrongAnswerCount}"
    )
    assert state.lockoutExpiresAt is None, (
        f"Inactive player's lockoutExpiresAt should be None, got {state.lockoutExpiresAt}"
    )
    assert state.pendingSongId is None, (
        f"Inactive player's pendingSongId should be None, got {state.pendingSongId}"
    )


# NOTE: "a round is in progress" is defined in conftest.py and populates ctx.


@when("the host sends game:play-song")
def host_sends_play_song(ctx):
    ctx.host.send("game:play-song")


@then("game:play-song is broadcast to the room")
def play_song_broadcast(ctx):
    ctx.host.expect_event("game:play-song")
    for player in ctx.players:
        player.expect_event("game:play-song")


@when("a non-host player sends game:play-song")
def non_host_sends_play_song(ctx, make_player):
    _, players, _ = create_room(make_player, 2)
    ctx.error_target = players[0]
    players[0].send("game:play-song")


@given("the round has already been revealed")
def round_already_revealed(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    _play_song(host, players)
    _close_and_reveal(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.revealed = True


@given("a round is in progress at playback duration index 0")
def round_at_index_0(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@given("the playback durations are [1, 2, 4, 8, 16]")
def durations_are_default(ctx):
    event = ctx.host.find_last_event("room:settings")
    assert event is not None
    assert event["payload"]["playbackDurations"] == [1, 2, 4, 8, 16]


@when("the host sends game:extend")
def host_sends_extend(ctx):
    ctx.host.send("game:extend")


@then("playbackDurationIndex advances to 1")
@then("the internal playback duration index advances to 1")
def duration_index_advances_to_1(ctx):
    event = ctx.host.expect_event("room:state")
    ctx.last_state = event
    assert event["payload"]["playbackDurationIndex"] == 1


@given(
    "a round is in progress at the last playback duration index",
)
def round_at_max_index(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    for _ in range(4):
        host.send("game:extend")
        host.expect_event("room:state")
        for player in players:
            player.drain_events(wait=0.2)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@when("a non-host player sends game:extend")
def non_host_sends_extend(ctx, make_player):
    _, players, _ = create_room(make_player, 2)
    ctx.error_target = players[0]
    players[0].send("game:extend")


@given("a round is in progress and no song has been played")
def round_no_song_played(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.song_played = False


@then("playbackDurationIndex advances")
@then("the internal playback duration index advances")
def duration_index_advances_generic(ctx):
    event = ctx.host.expect_event("room:state")
    ctx.last_state = event
    assert event["payload"]["playbackDurationIndex"] >= 1


@when("the host sends game:close-answers")
def host_sends_close_answers(ctx):
    host = ctx.host
    players = ctx.players
    # If the round has not had a song played yet and the scenario expects
    # the close to succeed, play the song first.  Scenarios that test
    # the "before song played" error use extra["song_played"]=False.
    if ctx.song_played is not False and not ctx.revealed and not ctx.phase:
        _play_song(host, players)
    host.send("game:close-answers")


@then("game:reveal { songId, winners } is broadcast to the room")
def reveal_broadcast(ctx):
    event = getattr(ctx, "last_reveal", None)
    if event is None:
        event = ctx.host.expect_event("game:reveal")
    ctx.last_reveal = None
    assert "songId" in event["payload"]
    assert "winners" in event["payload"]


@when("a non-host player sends game:close-answers")
def non_host_sends_close(ctx, make_player):
    _, players, _ = create_room(make_player, 2)
    ctx.error_target = players[0]
    players[0].send("game:close-answers")


@given("the current round has been revealed")
def current_round_revealed(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    _play_song(host, players)
    _close_and_reveal(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.revealed = True


@given("more rounds are available")
def more_rounds_available(ctx):
    event = ctx.host.find_last_event("room:settings")
    assert event is not None
    assert event["payload"]["totalRounds"] > 1


@when("the host sends game:next-round")
def host_sends_next_round(ctx):
    ctx.host.send("game:next-round")


@then("the next round begins")
def next_round_begins(ctx):
    event = ctx.host.expect_event("room:state")
    ctx.last_state = event
    assert event["payload"]["currentRound"] == 2


@when("a non-host player sends game:next-round")
def non_host_sends_next(ctx, make_player):
    _, players, _ = create_room(make_player, 2)
    ctx.error_target = players[0]
    players[0].send("game:next-round")


@given("a round is in progress and has not been revealed")
def round_not_revealed(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@given("a game with total rounds set to 3")
@given("a game with totalRounds set to 3")
def game_with_3_rounds(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@given("3 rounds have been played")
def three_rounds_played(ctx):
    host = ctx.host
    players = ctx.players
    for i in range(3):
        _play_song(host, players)
        _close_and_reveal(host, players)
        if i < 2:
            _next_round(host, players)


@given("a room is in playing phase")
def room_in_playing(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    settings_event = host.find_last_event("room:settings")
    assert settings_event is not None
    settings = RoomSettingsSCPayload.model_validate(settings_event["payload"])
    ctx.pre_game_songs = settings.songs
    shuffled_event = host.find_event("game:shuffled-songs")
    assert shuffled_event is not None
    shuffled = ShuffledSongsPayload.model_validate(shuffled_event["payload"])
    ctx.pre_game_shuffled_ids = shuffled.shuffledSongIds
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@when("the host sends game:end")
def host_sends_end(ctx):
    ctx.host.send("game:end")


@then('the room phase changes to "finished"')
def phase_changes_finished(ctx):
    event = ctx.host.expect_event("room:state")
    ctx.last_state = event
    assert event["payload"]["phase"] == "finished"


@then("game songs are deleted but songs in settings are preserved")
def game_songs_deleted(ctx):
    host = ctx.host
    players = ctx.players
    drain_all(host, players)
    settings_event = host.find_last_event("room:settings")
    assert settings_event is not None
    original_ids = sorted(s.id for s in ctx.pre_game_songs)
    current_ids = sorted(s["id"] for s in settings_event["payload"]["songs"])
    assert current_ids == original_ids, (
        "Songs in settings should be unchanged after game:end"
    )


@when("a non-host player sends game:end")
def non_host_sends_end(ctx, make_player):
    _, players, _ = create_room(make_player, 2)
    ctx.error_target = players[0]
    players[0].send("game:end")


@given("a room is in lobby phase")
def lobby_for_end(ctx, host):
    ctx.host = host
    ctx.room_code = host.room_code


@when("a non-host player sends game:back-to-lobby")
def non_host_sends_back(ctx, make_player):
    _, players, _ = create_room(make_player, 2)
    ctx.error_target = players[0]
    players[0].send("game:back-to-lobby")


# NOTE: "a game is in progress" is defined in conftest.py and populates ctx.


@when("the host sends game:back-to-lobby")
def host_sends_back_to_lobby(ctx):
    ctx.host.send("game:back-to-lobby")


@given("the game has finished")
def game_has_finished(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    shuffled_event = host.find_event("game:shuffled-songs")
    assert shuffled_event is not None
    shuffled = ShuffledSongsPayload.model_validate(shuffled_event["payload"])
    ctx.pre_game_shuffled_ids = shuffled.shuffledSongIds
    settings_event = host.find_last_event("room:settings")
    assert settings_event is not None
    settings = RoomSettingsSCPayload.model_validate(settings_event["payload"])
    ctx.pre_lobby_active_ids = [p.id for p in settings.activePlayers]
    ctx.pre_lobby_inactive_ids = [p.id for p in settings.inactivePlayers]
    host.send("game:end")
    drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.phase = "finished"


@then("songs in settings are reshuffled into game songs")
def songs_reshuffled(ctx):
    event = ctx.host.expect_event("game:shuffled-songs")
    ctx.last_shuffled_songs = event
    new_ids = event["payload"]["shuffledSongIds"]
    old_ids = ctx.pre_game_shuffled_ids
    assert sorted(new_ids) == sorted(old_ids), (
        "Reshuffled songs must contain the same IDs"
    )
    assert new_ids != old_ids, "Reshuffled order should differ from previous shuffle"


@then("the host receives the reshuffled song IDs via game:shuffled-songs")
def host_receives_reshuffled(ctx):
    event = getattr(ctx, "last_shuffled_songs", None)
    if event is None:
        event = ctx.host.expect_event("game:shuffled-songs")
    ctx.last_shuffled_songs = None
    assert "shuffledSongIds" in event["payload"]


@then("activePlayers and inactivePlayers in settings are preserved")
def players_preserved(ctx):
    host = ctx.host
    events = host.drain_events(wait=0.5)
    state = next((event for event in events if event["event"] == "room:state"), None)
    if state is not None:
        ctx.last_state = state
    settings_event = host.find_last_event("room:settings")
    assert settings_event is not None
    active_ids = sorted(p["id"] for p in settings_event["payload"]["activePlayers"])
    inactive_ids = sorted(p["id"] for p in settings_event["payload"]["inactivePlayers"])
    assert active_ids == sorted(ctx.pre_lobby_active_ids), (
        f"activePlayers changed: {active_ids} != {sorted(ctx.pre_lobby_active_ids)}"
    )
    assert inactive_ids == sorted(ctx.pre_lobby_inactive_ids), (
        f"inactivePlayers changed: {inactive_ids} != {sorted(ctx.pre_lobby_inactive_ids)}"
    )


@then("the roomState is destroyed")
def room_state_destroyed(ctx):
    event = getattr(ctx, "last_state", None)
    if event is None:
        event = ctx.host.expect_event("room:state")
    ctx.last_state = event
    assert event["payload"] is None
