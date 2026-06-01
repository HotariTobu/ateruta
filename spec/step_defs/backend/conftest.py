"""Backend test fixtures and shared step definitions.

Backend tests connect directly to the server via WebSocket and HTTP.
No browser is involved.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, then

from backend.helpers import (
    PlayerClient,
    create_room,
    drain_all,
    setup_valid_game,
)

ROOM_SETTINGS_VALIDATION_DETAILS = frozenset(
    {
        "Songs must not exceed 1000",
        "Song ID is required",
        "Song title is required",
        "Song artist is required",
        "Duplicate song IDs are not allowed",
        "Song artwork URL must not be empty",
        "Playback durations are required",
        "Playback durations must not exceed 10 entries",
        "Playback durations must contain only positive numbers",
        "Playback durations must be in ascending order",
        "Playback durations must not exceed 300 seconds each",
        "Rank points are required",
        "Rank points must not exceed 10 entries",
        "Rank points must contain only positive numbers",
        "Rank points must contain only integers",
        "Lockout duration must be between 0 and 30 seconds",
        "Attempts limit must be between 0 and 10",
        "Attempts limit must be an integer",
        "Total rounds must be at least 1",
        "Total rounds must be an integer",
        "Total rounds must not exceed 1000",
    }
)


def expect_error_from_feature(request, player: PlayerClient, message: str):
    module_name = getattr(getattr(request.node, "module", None), "__name__", "")
    if (
        module_name.endswith("test_room_settings")
        and message in ROOM_SETTINGS_VALIDATION_DETAILS
    ):
        player.expect_settings_validation_error(message)
        return
    player.expect_error(message)


class ScenarioContext:
    """Mutable state shared across steps within a single scenario.

    Given steps populate this context. When/Then steps read from it.
    """

    def __init__(self):
        self.host: PlayerClient | None = None
        self.players: list[PlayerClient] = []
        self.answerers: list[PlayerClient] = []
        self.room_code: str | None = None
        self.error_target: PlayerClient | None = None
        self.shuffled: list[str] | None = None
        self.rank_points: list[int] | None = None
        self.phase: str | None = None
        self.next_answerer_idx: int = 0
        self.handicap: int = 0
        self.current_round: int = 1
        self.revealed: bool | None = None
        self.song_played: bool | None = None
        self.last_settings: dict[str, object] | None = None
        self.last_state: dict[str, object] | None = None
        self.last_error_event: dict[str, object] | None = None
        self.last_reveal: dict[str, object] | None = None
        self.last_shuffled_songs: dict[str, object] | None = None
        self.expected_settings_update: dict[str, object] | None = None
        self.broadcast_observer: PlayerClient | None = None

        self.guest: PlayerClient | None = None  # room (room check, deletion)
        self.other_player: PlayerClient | None = None  # room (join takeover)
        self.joining_player: PlayerClient | None = None  # room (join errors)
        self.new_joiner: PlayerClient | None = None  # room (new player join)
        self.inactive_player: PlayerClient | None = None  # game (inactive removal)
        self.inactive_answerer: PlayerClient | None = None  # answer (active cap)
        self.disconnected_player: PlayerClient | None = None  # room (rejoin)
        self.host_a: PlayerClient | None = None  # room (multi-room)
        self.host_b: PlayerClient | None = None  # room (multi-room)

        self.original_id: str | None = None  # session (ID persistence)
        self.host_id: str | None = None  # reconnection (host matching)
        self.nickname: str | None = None  # room_settings (nickname)
        self.new_room_code: str | None = None  # room (creation, room switch)
        self.old_room_code: str | None = None  # room (room switch)
        self.room_code_a: str | None = None  # room (multi-room)
        self.room_code_b: str | None = None  # room (multi-room)
        self.scored_player_ids: set[str] = set()
        self.player_state: dict[str, object] | None = None
        self.original_player_state: dict[str, object] | None = None


@pytest.fixture
def ctx():
    """Per-scenario context shared across all steps."""
    return ScenarioContext()


@pytest.fixture
def make_player(backend_url, backend_ws_url):
    """Factory fixture to create PlayerClient instances."""
    players: list[PlayerClient] = []

    def _make() -> PlayerClient:
        player = PlayerClient(backend_url, backend_ws_url)
        player.init_session()
        player.connect()
        players.append(player)
        return player

    yield _make

    for player in players:
        player.close()


@pytest.fixture
def player(make_player) -> PlayerClient:
    """A single connected player."""
    return make_player()


@pytest.fixture
def host(make_player) -> PlayerClient:
    """A connected player who creates and joins a room (becomes host)."""
    host = make_player()
    room_code = host.create_room()
    host.join_room(room_code)
    host.expect_event("room:settings")
    host.room_code = room_code
    return host


@then(parsers.parse('the player receives an error event with "{message}"'))
def player_receives_error(request, message):
    ctx = request.getfixturevalue("ctx")
    if ctx.error_target is not None:
        expect_error_from_feature(request, ctx.error_target, message)
    else:
        expect_error_from_feature(request, request.getfixturevalue("player"), message)


@then(parsers.parse('the host receives an error event with "{message}"'))
def host_receives_error(request, message):
    ctx = request.getfixturevalue("ctx")
    stored = getattr(ctx, "last_error_event", None)
    if stored is not None and stored["payload"]["message"] == message:
        ctx.last_error_event = None
        return
    if ctx.host is not None:
        expect_error_from_feature(request, ctx.host, message)
    else:
        expect_error_from_feature(request, request.getfixturevalue("host"), message)


@then("room:settings is broadcast to the room")
def settings_broadcast(request):
    # A preceding Then step in the same scenario may have already consumed
    # the room:settings event and stored it in ctx.last_settings.  In that
    # case, clear the flag (one-shot consumption) so a subsequent broadcast
    # in the same scenario is not also implicitly skipped.
    ctx = request.getfixturevalue("ctx")
    if ctx.last_settings is not None:
        ctx.last_settings = None
        return
    host = ctx.host if ctx.host is not None else request.getfixturevalue("host")
    host.expect_event("room:settings")


@then("room:state is broadcast to the room")
def state_broadcast(request):
    ctx = request.getfixturevalue("ctx")
    if ctx.last_state is not None:
        ctx.last_state = None
        return
    observer = ctx.broadcast_observer
    if observer is None:
        observer = ctx.host if ctx.host is not None else request.getfixturevalue("host")
    observer.expect_event("room:state")


@given("a room exists")
def room_exists(ctx, make_player):
    """A bare room: created via API but no one has joined via WebSocket yet."""
    host = make_player()
    room_code = host.create_room()
    ctx.host = host
    ctx.room_code = room_code


@given("a room exists in lobby phase")
def room_in_lobby(ctx, host):
    ctx.host = host
    ctx.room_code = host.room_code


@given("a room is not in lobby phase")
def room_not_in_lobby(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@given(parsers.parse('the room phase is "{phase}"'))
def room_in_phase(ctx, make_player, phase):
    host, players, room_code = create_room(make_player, 2)
    if phase in ("playing", "finished"):
        setup_valid_game(host, players, room_code)
    if phase == "finished":
        host.send("game:end")
        drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.phase = phase


@given("a round is in progress")
def round_in_progress(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled


@given("a game is in progress")
def game_in_progress(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@given("a room is in finished phase")
def room_in_finished_phase(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    host.send("game:end")
    drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.phase = "finished"


@then("the player is moved from inactivePlayers to activePlayers")
def player_moved_to_active(ctx):
    event = ctx.host.expect_event("room:settings")
    ctx.last_settings = event
    active_ids = [p["id"] for p in event["payload"]["activePlayers"]]
    inactive_ids = [p["id"] for p in event["payload"]["inactivePlayers"]]
    player_id = ctx.players[0].player_id
    assert player_id in active_ids
    assert player_id not in inactive_ids


@then("no error is returned and no state changes")
def no_error_no_change(player):
    player.assert_no_event("error")
