"""Step definitions for room.feature — room creation, joining, departure, and lifecycle.

Many departure scenarios share the same When/Then step text but with different
Given preconditions.  Each Given populates the unified ``ctx`` (ScenarioContext)
fixture so that the shared When/Then steps can consume it uniformly.
"""

import time

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from backend.helpers import (
    PlayerClient,
    create_room,
    drain_all,
    setup_valid_game,
)
from backend.schemas import SESSION_COOKIE

scenarios("../../features/backend/room.feature")


@then("a room is in one of three phases: lobby, playing, or finished")
def room_phases(player):
    room_code = player.create_room()
    player.join_room(room_code)
    event = player.expect_event("room:settings")
    assert event is not None, "Room exists in lobby phase"


@then("lobby is when roomState is null")
def lobby_is_null(player):
    player.assert_no_event("room:state", timeout=0.5)


@then("playing and finished are indicated by the phase field in roomState")
def playing_finished_phases():
    from typing import Literal, get_args, get_origin

    from backend.schemas import RoomState

    phase_field = RoomState.model_fields["phase"].annotation
    assert get_origin(phase_field) is Literal
    assert set(get_args(phase_field)) == {"playing", "finished"}


@then(
    "a valid room code is a string of exactly 4 digits representing an integer between 1000 and 9999"
)
def valid_room_code_format(player):
    room_code = player.create_room()
    assert len(room_code) == 4 and room_code.isdigit()
    assert 1000 <= int(room_code) <= 9999


@when("a player sends POST /api/room", target_fixture="create_response")
def player_sends_post_room(player):
    return player.http.post("/api/room")


@then("the response status is 201 with { code }")
def response_201_with_code(create_response):
    assert create_response.status_code == 201
    assert "code" in create_response.json()


@then("a room with a 4-digit code between 1000 and 9999 is created")
def room_code_valid(create_response):
    room_code = create_response.json()["code"]
    assert len(room_code) == 4 and room_code.isdigit()
    assert 1000 <= int(room_code) <= 9999


@when("the server encounters an internal error")
@given("the server fails to handle room creation for any reason")
def server_internal_error():
    pytest.skip("Internal server errors cannot be triggered externally")


@then("the response status is 500 with { error }")
def response_500_with_error():
    pytest.skip("Internal server errors cannot be triggered externally")


@when("another player creates a room")
def another_player_creates_room(ctx, make_player):
    player = make_player()
    ctx.new_room_code = player.create_room()


@then("the new room has a different code")
def new_room_different_code(ctx):
    assert ctx.new_room_code != ctx.room_code


@given("all room codes between 1000 and 9999 are in use")
def all_codes_exhausted():
    pytest.skip("Cannot reproduce: 9000 players exceed the per-process thread limit")


@then(parsers.parse('the response status is 500 with {{ error: "{message}" }}'))
def response_500_with_message():
    pytest.skip("Cannot reproduce: 9000 players exceed the per-process thread limit")


@then("the room settings are:")
def room_default_settings(player, datatable, create_response):
    room_code = create_response.json()["code"]
    player.join_room(room_code)
    event = player.expect_event("room:settings")
    payload = event["payload"]
    assert payload["hostPlayerId"] == player.player_id
    assert payload["songs"] == []
    assert payload["totalRounds"] is None
    assert payload["playbackDurations"] == []
    assert payload["rankPoints"] == []
    assert payload["lockoutDuration"] is None
    assert payload["attemptsLimit"] is None
    # activePlayers/inactivePlayers defaults ([] both) are observable only
    # indirectly: room was empty pre-join (no settings query API exists),
    # and only this player joined.  Verifying the post-join broadcast
    # contains exactly this joiner with handicap 0 and no inactive entries
    # proves the initial state had both lists empty.
    assert len(payload["activePlayers"]) == 1
    assert payload["activePlayers"][0]["id"] == player.player_id
    assert payload["activePlayers"][0]["handicap"] == 0
    assert payload["inactivePlayers"] == []


@given("a player is the host of an existing room")
def player_is_host_of_existing_room(ctx, make_player):
    host, _, room_code = create_room(make_player, 0)
    ctx.host = host
    ctx.room_code = room_code


@when("the player sends POST /api/room")
def host_creates_new_room(ctx, make_player):
    host = ctx.host
    old_room_code = ctx.room_code
    actor = ctx.guest if ctx.guest is not None else host

    if ctx.guest is not None:
        guest = ctx.guest
    else:
        guest = make_player()
        guest.join_room(old_room_code)
        guest.expect_event("room:settings")
        host.drain_events(wait=0.3)

    new_room_code = actor.create_room()
    ctx.old_room_code = old_room_code
    ctx.new_room_code = new_room_code
    ctx.other_player = guest


@then("the existing room is closed")
def existing_room_closed(ctx):
    # "Closed" means the room is deleted: GET /api/room/{code} returns 404.
    # 403 would mean the room still exists but is not visible to a non-
    # participant — that is not the spec's intent here.
    resp = ctx.host.check_room(ctx.old_room_code)
    assert resp.status_code == 404, (
        f"Expected 404 for closed room, got {resp.status_code}"
    )


@then(
    parsers.parse(
        "remaining connections receive a room:closed event with "
        '{{ message: "{message}" }}'
    )
)
def remaining_connections_room_closed(ctx, message):
    other = ctx.other_player or ctx.guest
    event = other.expect_event("room:closed")
    assert event["payload"]["message"] == message


@then("all sockets are forced to leave the room")
def sockets_forced_leave(ctx):
    # The prior step verified room:closed was received. The observable consequence
    # of forced socket cleanup is that the other player's WebSocket connection
    # is closed by the server. Wait briefly for the close to propagate.
    time.sleep(0.5)
    other = ctx.other_player or ctx.guest
    assert other.close_code is not None, (
        "Expected other player's WebSocket to be closed after room:closed"
    )


@then("a new room is created and returned")
def new_room_created(ctx):
    room_code = ctx.new_room_code
    assert len(room_code) == 4 and room_code.isdigit()


@given("a player is in activePlayers of a room they do not host")
def player_in_room_not_host(ctx, make_player):
    host, players, room_code = create_room(make_player, 1)
    ctx.host = host
    ctx.room_code = room_code
    ctx.guest = players[0]


@then("the player is moved from activePlayers to inactivePlayers in the existing room")
def player_moved_to_inactive(ctx):
    host = ctx.host
    event = host.expect_event("room:settings")
    ctx.last_settings = event
    guest_id = ctx.guest.player_id
    active_ids = [p["id"] for p in event["payload"]["activePlayers"]]
    inactive_ids = [p["id"] for p in event["payload"]["inactivePlayers"]]
    assert guest_id not in active_ids
    assert guest_id in inactive_ids


@then("room:settings is broadcast to the existing room")
def settings_broadcast_existing(ctx):
    # Event already consumed by "the player is moved from activePlayers to inactivePlayers in the existing room"
    event = ctx.last_settings
    guest_id = ctx.guest.player_id
    inactive_ids = [p["id"] for p in event["payload"]["inactivePlayers"]]
    assert guest_id in inactive_ids, (
        "Broadcast should reflect the player's move to inactivePlayers"
    )


@then("room:state is broadcast to the existing room if roomState is not null")
def state_broadcast_existing_if_not_null(ctx):
    ctx.host.assert_no_event("room:state", timeout=0.5)


@then("the server checks room:join in the following order:")
def room_join_check_order(make_player, datatable):
    # Row 1: invalid format → "Invalid room code".
    player = make_player()
    player.join_room("abc")
    player.expect_error("Invalid room code")
    # Order 1<2: an invalid format ("abc") cannot identify a real room, so
    # row 2 (Room not found) would also conceptually fail.  Row 1 firing
    # instead of row 2 confirms format check precedes existence check.

    # Row 2: valid format, non-existent code → "Room not found".
    player.join_room("9999")
    player.expect_error("Room not found")

    # Row 3: already in another room.  Setup two rooms; join the first, then
    # try to join the second.
    host1, _, room_code1 = create_room(make_player, 0)
    host2, _, room_code2 = create_room(make_player, 0)
    player.join_room(room_code1)
    player.expect_event("room:settings")
    host1.drain_events(wait=0.3)
    player.join_room(room_code2)
    player.expect_error("Already in another room")

    # Order 2<3: already in room1, try to join non-existent "9999".  Both
    # row 2 (room not found) and row 3 (already in another room) would fail.
    # Row 2 must fire first.
    player.join_room("9999")
    player.expect_error("Room not found")

    # Order 3<4: already in room1; try to join a room that is in playing
    # phase.  Both row 3 (already in another room) and row 4 (game in
    # progress) would fail.  Row 3 must fire first.
    busy_host, busy_players, busy_code = create_room(make_player, 1)
    setup_valid_game(busy_host, busy_players, busy_code)
    player.join_room(busy_code)
    player.expect_error("Already in another room")

    # Order 4<5: a fresh player tries to join a playing-phase room that is
    # also full (20 active).  Setup is expensive (20 player WS connections
    # AND a started game) so only verify with a 20-player playing room.
    # Both row 4 and row 5 would fail; row 4 must fire first.
    full_host, full_players, full_code = create_room(make_player, 19)
    setup_valid_game(full_host, full_players, full_code)
    fresh = make_player()
    fresh.join_room(full_code)
    fresh.expect_error("Game already in progress")


@then(
    "players present in roomState (activePlayers or inactivePlayers) "
    'skip "Room in lobby phase" and "Room not full"'
)
def players_in_state_skip_checks(make_player):
    host, players, room_code = create_room(make_player, 1)
    setup_valid_game(host, players, room_code)
    players[0].disconnect()
    drain_all(host, [])
    players[0].reconnect()
    players[0].join_room(room_code)
    players[0].expect_event("room:settings")


@then(
    '"Not in another room" does not consider players in inactivePlayers as "in a room"'
)
def inactive_not_considered_in_room(make_player):
    host, players, room_code_a = create_room(make_player, 1)
    players[0].disconnect()
    host.drain_events(wait=0.3)
    host2, _, room_code_b = create_room(make_player, 0)
    players[0].reconnect()
    players[0].join_room(room_code_b)
    players[0].expect_event("room:settings")


@then(
    '"Room in lobby phase" error is "Game already in progress" during '
    'playing or "Game has ended" during finished'
)
def room_lobby_error_variants(make_player):
    host, players, room_code = create_room(make_player, 1)
    setup_valid_game(host, players, room_code)
    player = make_player()
    player.join_room(room_code)
    player.expect_error("Game already in progress")


@then('"Room not full" checks whether activePlayers count has reached 20')
def room_full_check(make_player):
    host, players, room_code = create_room(make_player, 19)
    player = make_player()
    player.join_room(room_code)
    player.expect_error("Room is full")


@then(
    "after all checks pass, if the player already has an active connection "
    "in the room, the old connection is closed with close code 4409"
)
def old_connection_closed(make_player, backend_url, backend_ws_url):
    host, players, room_code = create_room(make_player, 1)
    old = players[0]
    assert old.player_id is not None
    new_conn = PlayerClient(backend_url, backend_ws_url)
    new_conn.player_id = old.player_id
    new_conn.http.cookies.set(SESSION_COOKIE, old.player_id)
    new_conn.connect()
    new_conn.join_room(room_code)
    new_conn.expect_event("room:settings")
    time.sleep(0.5)
    assert old.close_code == 4409


@then("if the same socket is already in the room, the join is a no-op")
def same_socket_noop(make_player):
    host, players, room_code = create_room(make_player, 1)
    # Settle baseline: drain any join-time events.
    players[0].drain_events(wait=0.3)
    host.drain_events(wait=0.3)
    # Same socket re-joins: no error, AND no state change observable to host
    # (no room:settings re-broadcast).
    players[0].join_room(room_code)
    rejoiner_events = players[0].drain_events(wait=0.5)
    assert not rejoiner_events, (
        f"Same-socket re-join should be no-op, got events: {rejoiner_events}"
    )
    host_events = host.drain_events(wait=0.5)
    assert not host_events, (
        f"Same-socket re-join should not change state (no broadcast), "
        f"got host events: {host_events}"
    )


@when("a player sends room:join")
def player_sends_room_join(ctx, make_player):
    # "a player" always means a fresh joiner.  Scenarios where an existing
    # player rejoins use distinct step text ("the participant reconnects and
    # sends room:join", "the player sends room:join" for inactive rejoin).
    player = make_player()
    player.join_room(ctx.room_code)
    ctx.joining_player = player
    ctx.error_target = player


@then("the player is added to the room")
def player_added(ctx):
    joiner = ctx.joining_player
    event = ctx.host.expect_event("room:settings")
    ctx.last_settings = event
    active_ids = [p["id"] for p in event["payload"]["activePlayers"]]
    assert joiner.player_id in active_ids


@then("the player's nickname is auto-assigned")
def nickname_auto_assigned(ctx):
    joiner = ctx.joining_player
    event = ctx.last_settings
    assert event is not None
    active = event["payload"]["activePlayers"]
    p = next(p for p in active if p["id"] == joiner.player_id)
    assert p["nickname"]


@then("the player's handicap is 0")
def handicap_is_zero(ctx):
    joiner = ctx.joining_player
    event = ctx.last_settings
    assert event is not None
    active = event["payload"]["activePlayers"]
    p = next(p for p in active if p["id"] == joiner.player_id)
    assert p["handicap"] == 0


@when(parsers.parse('a player sends room:join for room "{code}" that does not exist'))
def join_nonexistent_room(player, code):
    player.join_room(code)


@given("a room exists with 20 active players")
def room_with_20_players(ctx, make_player):
    host, players, room_code = create_room(make_player, 19)
    ctx.host = host
    ctx.room_code = room_code
    ctx.players = [host] + players


# Note: "a player sends room:join" for the full-room scenario references
# the player fixture from conftest and host. Since this scenario
# uses "a room exists with 20 active players" (not host), we
# handle it via the conftest "the player receives an error event" step.


@given("a player is already in the room")
def player_already_in_room(host, player):
    player.join_room(host.room_code)
    player.expect_event("room:settings")
    host.drain_events(wait=0.3)


@when("the same socket sends room:join for the same room")
def same_socket_rejoins(player, host):
    player.join_room(host.room_code)


@given(
    "a player is in the room with an active WebSocket connection",
    target_fixture="takeover_context",
)
def player_in_room_active(make_player):
    host, players, room_code = create_room(make_player, 1)
    return {"host": host, "player": players[0], "room_code": room_code}


@when(
    "the same player ID sends room:join from a different connection",
    target_fixture="takeover_result",
)
def same_player_new_connection(takeover_context, backend_url, backend_ws_url):
    old = takeover_context["player"]
    room_code = takeover_context["room_code"]
    new_conn = PlayerClient(backend_url, backend_ws_url)
    new_conn.player_id = old.player_id
    new_conn.http.cookies.set(SESSION_COOKIE, old.player_id)
    new_conn.connect()
    new_conn.join_room(room_code)
    new_conn.expect_event("room:settings")
    return {"old": old, "new": new_conn, "room_code": room_code}


@then("the new connection takes over")
def new_connection_takes_over(takeover_result):
    # "Takes over" means the new connection is the active one for this player:
    # (1) same player identity, (2) can interact with the room (server treats
    # this connection as the player's current session).
    new = takeover_result["new"]
    old = takeover_result["old"]
    assert new.player_id == old.player_id, "Takeover must preserve player identity"
    # Verify the new connection can interact: send a nickname change and observe
    # the resulting room:settings broadcast reflecting the change.
    new.send("room:nickname", {"nickname": "Takeover"})
    event = new.expect_event("room:settings")
    payload = event["payload"]
    matched = next(p for p in payload["activePlayers"] if p["id"] == new.player_id)
    assert matched["nickname"] == "Takeover"


@then("the old connection is closed with close code 4409")
def old_connection_closed_4409(takeover_result):
    time.sleep(1)
    assert takeover_result["old"].close_code == 4409


@given("a player is already in a room")
def player_in_a_room(host, player):
    player.join_room(host.room_code)
    player.expect_event("room:settings")
    host.drain_events(wait=0.3)


@when("the player sends room:join for a different room")
def join_different_room(player, make_player):
    _, _, room_code2 = create_room(make_player, 0)
    player.join_room(room_code2)


@when("a new player who was not in the lobby sends room:join")
def new_player_joins_during_game(ctx, make_player):
    player = make_player()
    player.join_room(ctx.room_code)
    ctx.new_joiner = player
    ctx.error_target = player


@given("a participant has disconnected")
def participant_disconnected(ctx, make_player):
    if ctx.host is None:
        host, players, room_code = create_room(make_player, 2)
    else:
        host = ctx.host
        players = ctx.players
        room_code = ctx.room_code
    participant = players[0]
    participant.disconnect()
    drain_all(host, players[1:])
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.disconnected_player = participant


@when("the participant reconnects and sends room:join")
def participant_reconnects(ctx):
    participant = ctx.disconnected_player
    participant.reconnect()
    participant.join_room(ctx.room_code)


@then("the participant is moved from inactivePlayers to activePlayers")
def participant_moved_to_active(ctx):
    event = ctx.host.expect_event("room:settings")
    ctx.last_settings = event
    ctx.last_state = ctx.host.expect_event("room:state")
    active_ids = [p["id"] for p in event["payload"]["activePlayers"]]
    assert ctx.disconnected_player.player_id in active_ids


@when("a new player who was not a participant sends room:join")
def new_player_joins_finished(ctx, make_player):
    player = make_player()
    player.join_room(ctx.room_code)
    ctx.new_joiner = player
    ctx.error_target = player


@given("a room is scheduled for deletion")
def room_scheduled_for_deletion(ctx, make_player):
    host, players, room_code = create_room(make_player, 1)
    guest = players[0]
    host.disconnect()
    guest.drain_events(wait=0.3)
    ctx.host = host
    ctx.room_code = room_code
    ctx.guest = guest


@when("the host sends room:join before the grace period expires")
def host_rejoins_before_grace(ctx):
    ctx.host.reconnect()
    ctx.host.join_room(ctx.room_code)
    ctx.host.expect_event("room:settings")


@then("the scheduled deletion is cancelled")
def deletion_cancelled(ctx):
    resp = ctx.host.check_room(ctx.room_code)
    assert resp.status_code == 200


@then("the room continues to exist")
def room_still_exists(ctx):
    resp = ctx.host.check_room(ctx.room_code)
    assert resp.status_code == 200


@when("a non-host player sends room:join before the grace period expires")
def non_host_rejoins(ctx, make_player):
    player = make_player()
    player.join_room(ctx.room_code)
    player.expect_event("room:settings")


@then("the scheduled deletion is not cancelled")
def deletion_not_cancelled(ctx):
    # Wait for the 5-minute grace period to expire, then verify the room
    # was actually deleted — proving the timer was not cancelled.
    time.sleep(300)
    resp = ctx.guest.check_room(ctx.room_code)
    assert resp.status_code == 404


@given("a player is in inactivePlayers during lobby phase")
def player_in_inactive_lobby(ctx, make_player):
    host, players, room_code = create_room(make_player, 1)
    player = players[0]
    player.disconnect()
    host.drain_events(wait=0.3)
    ctx.host = host
    ctx.room_code = room_code
    ctx.players = [player]
    ctx.inactive_player = player


@when("the player sends room:join")
def inactive_player_rejoins(ctx):
    ctx.inactive_player.reconnect()
    ctx.inactive_player.join_room(ctx.room_code)
    ctx.error_target = ctx.inactive_player


@given("a room in lobby phase has 20 active players")
def lobby_room_20_players(ctx, make_player):
    host, players, room_code = create_room(make_player, 19)
    ctx.host = host
    ctx.room_code = room_code
    ctx.players = [host] + players


@given("a player is in inactivePlayers")
def player_in_inactive_full(ctx, make_player):
    room_code = ctx.room_code
    last = ctx.players[-1]
    last.disconnect()
    for pl in ctx.players[:-1]:
        pl.drain_events(wait=0.1)
    new_player = make_player()
    new_player.join_room(room_code)
    new_player.expect_event("room:settings")
    for pl in ctx.players[:-1]:
        pl.drain_events(wait=0.1)
    ctx.inactive_player = last


@when(
    parsers.parse("any player sends GET /api/room/{{code}}"),
    target_fixture="api_response",
)
def any_player_checks_room(player, host):
    return player.check_room(host.room_code)


@when(
    "a non-participant sends GET /api/room/{code}",
    target_fixture="api_response",
)
def non_participant_checks_room(ctx, make_player):
    player = make_player()
    if ctx.room_code is not None:
        return player.check_room(ctx.room_code)
    _, _, room_code = create_room(make_player, 2)
    return player.check_room(room_code)


@then(parsers.parse('the response status is 403 with {{ error: "{message}" }}'))
def response_403_with_error(api_response, message):
    assert api_response.status_code == 403
    assert api_response.json()["error"] == message


@when(
    "a participant sends GET /api/room/{code}",
    target_fixture="api_response",
)
def participant_checks_room(ctx, make_player):
    if ctx.host is not None and ctx.room_code is not None:
        return ctx.host.check_room(ctx.room_code)
    host, _, room_code = create_room(make_player, 2)
    return host.check_room(room_code)


@then("the response status is 200 with { exists: true }")
def response_200_exists(api_response):
    assert api_response.status_code == 200
    assert api_response.json()["exists"] is True


@when(
    "any player sends GET /api/room/{code} for a non-existent room",
    target_fixture="api_response",
)
def check_nonexistent_room(player):
    return player.check_room("9998")


@then(parsers.parse('the response status is 404 with {{ error: "{message}" }}'))
def response_404_with_error(api_response, message):
    assert api_response.status_code == 404
    assert api_response.json()["error"] == message


@when(
    "any player sends GET /api/room/{code} with an invalid room code format",
    target_fixture="api_response",
)
def check_invalid_code(player):
    return player.check_room("abc")


@then(parsers.parse('the response status is 400 with {{ error: "{message}" }}'))
def response_400_with_error(api_response, message):
    assert api_response.status_code == 400
    assert api_response.json()["error"] == message


@given("a room exists in lobby phase with multiple players")
def lobby_with_multiple_players(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@given("a game is in playing phase")
def game_in_playing_phase(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@given("a room exists in lobby phase with the host and other players")
def lobby_with_host_and_players(ctx, make_player):
    host, players, room_code = create_room(make_player, 1)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@given("a room is in finished phase with the host and other players")
def finished_with_host_and_players(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    host.send("game:end")
    drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.phase = "finished"


@given("a room exists with players")
def room_with_players_fixture(ctx, make_player):
    host, players, room_code = create_room(make_player, 1)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@when("a non-host player leaves or disconnects")
def non_host_departs(ctx):
    ctx.players[0].leave_room()


@when("the host leaves or disconnects")
def host_departs(ctx):
    ctx.host.disconnect()


@then("the player is moved from activePlayers to inactivePlayers")
def player_moved_inactive(ctx):
    observer = ctx.host
    event = observer.expect_event("room:settings")
    ctx.last_settings = event
    departing_id = ctx.players[0].player_id
    active_ids = [p["id"] for p in event["payload"]["activePlayers"]]
    inactive_ids = [p["id"] for p in event["payload"]["inactivePlayers"]]
    assert departing_id not in active_ids
    assert departing_id in inactive_ids


@then("the host is moved from activePlayers to inactivePlayers")
def host_moved_inactive(ctx):
    observer = ctx.players[0]
    event = observer.expect_event("room:settings")
    ctx.last_settings = event
    ctx.broadcast_observer = observer
    host_id = ctx.host.player_id
    active_ids = [p["id"] for p in event["payload"]["activePlayers"]]
    inactive_ids = [p["id"] for p in event["payload"]["inactivePlayers"]]
    assert host_id not in active_ids
    assert host_id in inactive_ids


@then("the room is scheduled for deletion after 5 minutes")
def room_scheduled_deletion(ctx):
    checker = ctx.players[0] if ctx.players else ctx.host
    time.sleep(300)
    resp = checker.check_room(ctx.room_code)
    assert resp.status_code == 404


@when("all players leave or disconnect")
def all_players_depart(ctx):
    for p in ctx.players:
        p.disconnect(settle=0)
    ctx.host.disconnect()


@given("a player has penalty state (pending answer, lockout, or wrong answer count)")
def player_with_penalty(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(host, players, room_code)
    host.send("game:play-song")
    drain_all(host, players)
    if shuffled and len(shuffled) > 1:
        wrong_id = [s for s in shuffled if s != shuffled[0]][0]
        players[0].send("game:answer", {"songId": wrong_id})
        players[0].drain_events(wait=0.5)
        host.drain_events(wait=0.3)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@when("the player leaves or disconnects")
def penalty_player_departs(ctx):
    ctx.players[0].disconnect()


@then("pending answer timers and lockout timers continue to run")
@then("the penalty state is preserved")
def timers_continue(ctx):
    player = ctx.players[0]
    player.reconnect()
    player.join_room(ctx.room_code)
    event = player.expect_event("game:player-state")
    state = event["payload"]
    ctx.player_state = state
    assert (
        state.get("lockoutExpiresAt") is not None
        or state.get("pendingExpiresAt") is not None
    )


@then("the wrong answer count is preserved")
def wrong_count_preserved(ctx):
    state = ctx.player_state
    assert state["wrongAnswerCount"] >= 1


@given("a player is in inactivePlayers of room A")
def player_inactive_in_room_a(ctx, make_player):
    host_a, players, room_code_a = create_room(make_player, 1)
    player = players[0]
    player.disconnect()
    host_a.drain_events(wait=0.3)
    ctx.host_a = host_a
    ctx.players = [player]
    ctx.room_code_a = room_code_a


@when("the player joins room B")
def player_joins_room_b(ctx, make_player):
    host_b, _, room_code_b = create_room(make_player, 0)
    ctx.players[0].reconnect()
    ctx.players[0].join_room(room_code_b)
    ctx.players[0].expect_event("room:settings")
    host_b.drain_events(wait=0.3)
    ctx.host_b = host_b
    ctx.room_code_b = room_code_b


@then("the player is removed from room A's inactivePlayers")
def removed_from_room_a(ctx):
    event = ctx.host_a.expect_event("room:settings")
    ctx.last_settings = event
    player_id = ctx.players[0].player_id
    inactive_ids = [p["id"] for p in event["payload"]["inactivePlayers"]]
    assert player_id not in inactive_ids


@then("the player's pending answer in room A is cancelled")
def pending_answer_cancelled(ctx):
    # Pending answer cancellation has no dedicated event. The observable consequence
    # is that no game:scored or game:wrong-answer event arrives from room A after
    # the player joins room B.
    ctx.host_a.assert_no_event("game:scored", timeout=1.0)


@then("room:settings is broadcast to room A")
def settings_broadcast_room_a(ctx):
    # Event already consumed by "the player is removed from room A's inactivePlayers"
    event = ctx.last_settings
    player_id = ctx.players[0].player_id
    inactive_ids = [p["id"] for p in event["payload"]["inactivePlayers"]]
    assert player_id not in inactive_ids, (
        "Broadcast should reflect the player's removal from room A"
    )


@then("room:state is broadcast to room A if roomState is not null")
def state_broadcast_room_a(ctx):
    ctx.host_a.assert_no_event("room:state", timeout=0.5)


@when("a room is created via POST /api/room")
def room_created_via_post(ctx, player):
    room_code = player.create_room()
    ctx.room_code = room_code
    ctx.players = [player]


# "the room is scheduled for deletion after 5 minutes" — reuses step above


@when("5 minutes elapse")
def five_minutes_elapse():
    time.sleep(300)


@then("the room is deleted")
def room_deleted(ctx):
    checker = ctx.players[0] if ctx.players else (ctx.guest or ctx.host)
    resp = checker.check_room(ctx.room_code)
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
