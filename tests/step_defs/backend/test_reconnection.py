"""Step definitions for reconnection.feature — reconnection and state restoration.

Each Given step populates the unified ``ctx`` (ScenarioContext) fixture so that
the shared When/Then steps can consume it uniformly.
"""

from pytest_bdd import given, parsers, scenarios, then, when

from backend.helpers import create_room, drain_all, setup_valid_game
from backend.schemas import ShuffledSongsPayload, WrongAnswerPayload

scenarios("../../features/backend/reconnection.feature")


@given("a player has a player ID")
def player_has_id(ctx, make_player):
    host, [player], room_code = create_room(make_player, 1)
    ctx.host = host
    ctx.players = [player]
    ctx.room_code = room_code
    ctx.original_id = player.player_id


@when("the player disconnects and reconnects with the same session")
def player_reconnects_same_session(ctx):
    player = ctx.players[0]
    player.disconnect()
    ctx.host.drain_events(wait=0.3)
    player.reconnect()
    player.join_room(ctx.room_code)


@when("the player disconnects")
def player_disconnects(ctx):
    ctx.players[0].disconnect()
    if ctx.host is not None:
        ctx.host.drain_events(wait=0.3)


@when("the player reconnects with the same session")
def player_reconnects_with_same_session(ctx):
    ctx.players[0].reconnect()
    ctx.players[0].join_room(ctx.room_code)


@then("the player is recognized as the same person")
def player_recognized(ctx):
    player = ctx.players[0]
    assert player.player_id == ctx.original_id
    event = player.expect_event("room:settings")
    active_ids = [pl["id"] for pl in event["payload"]["activePlayers"]]
    assert player.player_id in active_ids


@given(
    parsers.parse("a player with score {score:d} is in inactivePlayers during a game")
)
@given(parsers.parse("a player with score {score:d} disconnects during a game"))
def player_with_score_disconnects(ctx, make_player, score):
    host, [player, player2], room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(host, [player, player2], room_code, rank_points=[score])

    host.send("game:play-song")
    drain_all(host, [player, player2])
    if shuffled:
        player.send("game:answer", {"songId": shuffled[0]})
        drain_all(host, [player, player2])

    player.disconnect()
    drain_all(host, [player2])
    ctx.host = host
    ctx.players = [player, player2]
    ctx.room_code = room_code


@when("the player reconnects")
@when("the player rejoins the room")
def player_reconnects(ctx):
    player = ctx.players[0]
    player.reconnect()
    player.join_room(ctx.room_code)


@then(parsers.parse("the player's score is {score:d}"))
def player_score_is(ctx, score):
    event = ctx.host.expect_event("room:state")
    all_players = event["payload"]["activePlayers"] + event["payload"].get(
        "inactivePlayers", []
    )
    player = next(pl for pl in all_players if pl["id"] == ctx.players[0].player_id)
    assert player["score"] == score


@given(
    parsers.parse(
        "a player with handicap {seconds:d} seconds is in inactivePlayers during a game"
    )
)
@given(
    parsers.parse(
        "a player with handicap {seconds:d} seconds disconnects during a game"
    )
)
def player_with_handicap_disconnects(ctx, make_player, seconds):
    host, [player, player2], room_code = create_room(make_player, 2)
    player.send("room:handicap", {"handicap": seconds})
    host.expect_event("room:settings")
    player.drain_events(wait=0.3)
    player2.drain_events(wait=0.3)
    setup_valid_game(host, [player, player2], room_code)
    player.disconnect()
    drain_all(host, [player2])
    ctx.host = host
    ctx.players = [player, player2]
    ctx.room_code = room_code
    ctx.handicap = seconds


@then(parsers.parse("the player's handicap is {seconds:d} seconds"))
def handicap_restored(ctx, seconds):
    event = ctx.host.find_last_event("room:settings")
    assert event is not None
    settings = event["payload"]
    all_players = settings["activePlayers"] + settings["inactivePlayers"]
    player = next(pl for pl in all_players if pl["id"] == ctx.players[0].player_id)
    assert player["handicap"] == seconds


@given(parsers.parse('a player with nickname "{nickname}" is in inactivePlayers'))
@given(parsers.parse('a player with nickname "{nickname}" disconnects'))
def player_with_nickname_disconnects(ctx, make_player, nickname):
    host, [player], room_code = create_room(make_player, 1)
    player.send("room:nickname", {"nickname": nickname})
    host.expect_event("room:settings")
    player.drain_events(wait=0.3)
    player.disconnect()
    host.drain_events(wait=0.3)
    ctx.host = host
    ctx.players = [player]
    ctx.room_code = room_code
    ctx.nickname = nickname


@when("the player reconnects to the same room")
@when("the player rejoins within the same round")
def player_reconnects_nickname(ctx):
    ctx.players[0].reconnect()
    ctx.players[0].join_room(ctx.room_code)


@then(parsers.parse('the player\'s nickname is "{nickname}"'))
def nickname_restored(ctx, nickname):
    event = ctx.host.find_last_event("room:settings")
    assert event is not None
    settings = event["payload"]
    all_players = settings["activePlayers"] + settings["inactivePlayers"]
    player = next(pl for pl in all_players if pl["id"] == ctx.players[0].player_id)
    assert player["nickname"] == nickname


@given(
    "a player has acquired penalty state",
)
@given(
    "a player disconnects during a game with penalty state",
)
def player_acquired_penalty_state(ctx, make_player):
    if ctx.host is None:
        host, [player, player2], room_code = create_room(make_player, 2)
        shuffled = setup_valid_game(host, [player, player2], room_code)
        ctx.host = host
        ctx.players = [player, player2]
        ctx.room_code = room_code
        ctx.shuffled = shuffled
    host = ctx.host
    player = ctx.players[0]
    other_players = ctx.players[1:]
    shuffled = ctx.shuffled
    if shuffled is None:
        event = host.find_last_event("game:shuffled-songs")
        assert event is not None, "Expected game:shuffled-songs from game setup"
        payload = ShuffledSongsPayload.model_validate(event["payload"])
        shuffled = payload.shuffledSongIds

    host.send("game:play-song")
    drain_all(host, ctx.players)
    if shuffled and len(shuffled) > 1:
        wrong_id = [s for s in shuffled if s != shuffled[0]][0]
        player.send("game:answer", {"songId": wrong_id})
        player_state = WrongAnswerPayload.model_validate(
            player.expect_event("game:wrong-answer")["payload"]
        )
        drain_all(host, other_players)
        ctx.original_player_state = {
            "lockoutExpiresAt": player_state.lockoutExpiresAt,
            "pendingExpiresAt": None,
        }
    ctx.shuffled = shuffled


@when("the player reconnects within the same round")
def player_reconnects_same_round(ctx):
    ctx.players[0].reconnect()
    ctx.players[0].join_room(ctx.room_code)


@then("the player's wrong answer count is preserved")
def wrong_count_preserved(ctx):
    # The Given step sent exactly 1 wrong answer before disconnection;
    # after reconnection the count must equal that exact value.
    event = ctx.players[0].expect_event("game:player-state")
    ctx.player_state = event["payload"]
    assert ctx.player_state["wrongAnswerCount"] == 1


@then("the original lockoutExpiresAt and pendingExpiresAt are preserved")
def original_penalty_times_preserved(ctx):
    if ctx.player_state is None:
        event = ctx.players[0].expect_event("game:player-state")
        ctx.player_state = event["payload"]
    original = ctx.original_player_state or {}
    assert ctx.player_state.get("lockoutExpiresAt") == original.get("lockoutExpiresAt")
    assert ctx.player_state.get("pendingExpiresAt") == original.get("pendingExpiresAt")


@then("lockout and pending answer states reflect the current time")
def states_reflect_time(ctx):
    from datetime import datetime, timezone

    state = ctx.player_state
    now = datetime.now(tz=timezone.utc)
    has_time_field = False
    for field in ("lockoutExpiresAt", "pendingExpiresAt"):
        value = state.get(field)
        if value is not None:
            has_time_field = True
            expires = datetime.fromisoformat(value)
            assert expires > now, (
                f"{field} should be in the future after reconnection, got {value}"
            )
    assert has_time_field, (
        "Expected at least one time-relative field (lockoutExpiresAt or pendingExpiresAt)"
    )


@when("the player rejoins after the round has changed")
@when("the player reconnects after the round has changed")
def player_reconnects_after_round(ctx):
    host = ctx.host
    player2 = ctx.players[1]
    host.send("game:close-answers")
    drain_all(host, [player2])
    host.send("game:next-round")
    drain_all(host, [player2])
    ctx.players[0].reconnect()
    ctx.players[0].join_room(ctx.room_code)


@then("all penalty state is reset")
def all_penalty_reset(ctx):
    event = ctx.players[0].expect_event("game:player-state")
    state = event["payload"]
    assert state["wrongAnswerCount"] == 0
    assert state["lockoutExpiresAt"] is None
    assert state["pendingSongId"] is None
    assert state["pendingExpiresAt"] is None


@given("the host disconnects")
@given("the host is in inactivePlayers")
def host_disconnects(ctx, make_player):
    if ctx.host is None:
        host, [player], room_code = create_room(make_player, 1)
        ctx.players = [player]
        ctx.room_code = room_code
    else:
        host = ctx.host
        room_code = ctx.room_code
        if not ctx.players:
            player = make_player()
            player.join_room(room_code)
            player.expect_event("room:settings")
            ctx.players = [player]
    ctx.host_id = host.player_id
    host.disconnect()
    for player in ctx.players:
        player.drain_events(wait=0.3)
    ctx.host = host
    ctx.room_code = room_code


@when("the host reconnects with the same session")
@when("the host rejoins the room with the same session")
@when("the host rejoins the room")
def host_reconnects(ctx):
    ctx.host.reconnect()
    ctx.host.join_room(ctx.room_code)


@then("the player is marked as host via hostPlayerId matching")
@then("the player is the host")
def host_status_restored(ctx):
    event = ctx.host.expect_event("room:settings")
    assert event["payload"]["hostPlayerId"] == ctx.host_id


@when("a player rejoins a room")
def player_rejoins_room(ctx, make_player):
    host, [player], room_code = create_room(make_player, 1)
    player.disconnect()
    host.drain_events(wait=0.3)
    player.reconnect()
    player.join_room(room_code)
    ctx.host = host
    ctx.players = [player]
    ctx.room_code = room_code


@then("the following events are delivered in the listed order:")
def events_in_order(ctx, datatable):
    rows = datatable[1:]
    expected_events = [row[0] for row in rows]
    player = ctx.players[0]
    received_all = player.drain_events(wait=1.0)
    received_relevant = [
        e["event"] for e in received_all if e["event"] in expected_events
    ]
    # The "always" event (room:settings) must arrive regardless of phase/role.
    assert "room:settings" in received_relevant, (
        f"room:settings (always-broadcast) not received; got: {received_relevant}"
    )
    # Whichever conditional events arrive must follow the listed order — i.e.
    # received_relevant is a subsequence of expected_events.
    cursor = 0
    for event_name in received_relevant:
        while cursor < len(expected_events) and expected_events[cursor] != event_name:
            cursor += 1
        assert cursor < len(expected_events), (
            f"Event '{event_name}' arrived out of expected order. "
            f"Received: {received_relevant}, Expected order: {expected_events}"
        )
        cursor += 1


@given("a player reconnects during lobby phase")
def player_reconnects_lobby(ctx, make_player):
    host, [player], room_code = create_room(make_player, 1)
    player.disconnect()
    host.drain_events(wait=0.3)
    player.reconnect()
    player.join_room(room_code)
    ctx.host = host
    ctx.players = [player]
    ctx.room_code = room_code


# "room:settings is broadcast to the room" — reuses conftest step


@given("a room is in lobby phase")
def room_is_lobby_phase(ctx, make_player):
    host, players, room_code = create_room(make_player, 1)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@given("a player is in inactivePlayers")
def player_is_inactive(ctx, make_player):
    if ctx.host is None:
        host, players, room_code = create_room(make_player, 1)
        ctx.host = host
        ctx.players = players
        ctx.room_code = room_code
    if not ctx.players:
        player = make_player()
        player.join_room(ctx.room_code)
        player.expect_event("room:settings")
        ctx.players = [player]
        ctx.host.drain_events(wait=0.3)
    player = ctx.players[0]
    player.disconnect()
    ctx.host.drain_events(wait=0.3)


@given("the host reconnects during lobby phase")
def host_reconnects_lobby(ctx, make_player):
    host, [player], room_code = create_room(make_player, 1)
    host.send(
        "room:settings",
        {
            "songs": [
                {
                    "id": f"song{i}",
                    "title": f"Song {i}",
                    "artist": f"Artist {i}",
                    "artworkUrl": None,
                }
                for i in range(1, 4)
            ],
        },
    )
    drain_all(host, [player])
    host.disconnect()
    player.drain_events(wait=0.3)
    host.reconnect()
    host.join_room(room_code)
    ctx.host = host
    ctx.players = [player]
    ctx.room_code = room_code


@given("shuffled game songs exist")
def shuffled_songs_exist(ctx):
    event = ctx.host.find_last_event("room:settings")
    if event is not None and len(event["payload"]["songs"]) > 0:
        return
    ctx.host.reconnect()
    ctx.host.join_room(ctx.room_code)
    ctx.host.expect_event("room:settings")
    ctx.host.send(
        "room:settings",
        {
            "songs": [
                {
                    "id": f"song{i}",
                    "title": f"Song {i}",
                    "artist": f"Artist {i}",
                    "artworkUrl": None,
                }
                for i in range(1, 4)
            ],
        },
    )
    event = ctx.host.expect_event("room:settings")
    assert len(event["payload"]["songs"]) > 0
    ctx.host.expect_event("game:shuffled-songs")
    for player in ctx.players:
        player.drain_events(wait=0.3)
    ctx.host.disconnect()
    for player in ctx.players:
        player.drain_events(wait=0.3)


@then("the host receives the shuffled song IDs via game:shuffled-songs")
def host_receives_shuffled_lobby(ctx):
    event = ctx.host.expect_event("game:shuffled-songs")
    assert "shuffledSongIds" in event["payload"]


@given("a player reconnects during an active game")
def player_reconnects_game(ctx, make_player):
    host, [player, player2], room_code = create_room(make_player, 2)
    setup_valid_game(host, [player, player2], room_code)
    player.disconnect()
    drain_all(host, [player2])
    player.reconnect()
    player.join_room(room_code)
    ctx.host = host
    ctx.players = [player, player2]
    ctx.room_code = room_code


@then("room:settings and room:state are broadcast to the room")
def settings_and_state_broadcast(ctx):
    ctx.players[0].expect_event("room:settings")
    ctx.players[0].expect_event("room:state")


@given("the current round has been revealed")
def round_has_been_revealed(ctx):
    host = ctx.host
    host.send("game:play-song")
    drain_all(host, ctx.players)
    host.send("game:close-answers")
    drain_all(host, ctx.players)


@then("game:restore-reveal is sent to the player")
def restore_reveal_sent(ctx):
    events = ctx.players[0].drain_events(wait=2.0)
    restore = [e for e in events if e["event"] == "game:restore-reveal"]
    assert len(restore) > 0
    assert "songId" in restore[0]["payload"]
    assert "winners" in restore[0]["payload"]


@given("the host reconnects during an active game")
def host_reconnects_game(ctx, make_player):
    host, [player, player2], room_code = create_room(make_player, 2)
    setup_valid_game(host, [player, player2], room_code)
    host.disconnect()
    drain_all(player, [player2])
    host.reconnect()
    host.join_room(room_code)
    ctx.host = host
    ctx.players = [player, player2]
    ctx.room_code = room_code


@then("the host receives the shuffled game song IDs via game:shuffled-songs")
def host_receives_shuffled_game(ctx):
    event = ctx.host.expect_event("game:shuffled-songs")
    assert "shuffledSongIds" in event["payload"]


@given("a player reconnects during finished phase")
def player_reconnects_finished(ctx, make_player):
    host, [player, player2], room_code = create_room(make_player, 2)
    setup_valid_game(host, [player, player2], room_code)
    host.send("game:end")
    drain_all(host, [player, player2])
    player.disconnect()
    drain_all(host, [player2])
    player.reconnect()
    player.join_room(room_code)
    ctx.host = host
    ctx.players = [player, player2]
    ctx.room_code = room_code


# "room:settings and room:state are broadcast to the room" — reuses step above


@given("the current round has not been revealed")
def round_not_revealed(ctx):
    assert ctx.host.find_event("game:reveal") is None


@then("game:player-state is sent to the player")
def player_state_sent(ctx):
    events = ctx.players[0].drain_events(wait=2.0)
    states = [e for e in events if e["event"] == "game:player-state"]
    assert len(states) > 0
    state = states[0]["payload"]
    assert "scored" in state
    assert "wrongAnswerCount" in state


# "a game is in progress" — reuses conftest step


@when("a player who was not in the lobby sends room:join")
def non_participant_joins(ctx, make_player):
    player = make_player()
    player.join_room(ctx.room_code)
    ctx.error_target = player
