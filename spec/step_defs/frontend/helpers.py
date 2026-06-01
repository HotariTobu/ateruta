"""Helpers for frontend tests.

Provides a mock WebSocket server and scenario setup functions.
"""

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from playwright.sync_api import expect
from backend.schemas import (
    ErrorResponse,
    GetRoomResponse200,
    GetSessionResponse200,
    GetTokenResponse200,
    PostRoomResponse201,
    SESSION_COOKIE,
)
from websockets.sync.server import Server, ServerConnection
from websockets.sync.server import serve as ws_serve


SELF_PLAYER_ID = "player-1"


def only_searchbox(page):
    return only_role(page, "searchbox")


def only_role(scope, role: str, *, name: str | None = None):
    locator = (
        scope.get_by_role(role, name=name, exact=True)
        if name is not None
        else scope.get_by_role(role)
    )
    expect(locator).to_have_count(1, timeout=5000)
    return locator


def visible_alert(page, text: str | None = None):
    alert = page.get_by_role("alert")
    if text is not None:
        alert = alert.filter(has_text=text)
    for _ in range(50):
        if alert.count() > 0:
            return alert
        page.wait_for_timeout(100)
    raise AssertionError(f"Expected alert with text {text!r}")


def only_alert(page, text: str | None = None):
    alert = page.get_by_role("alert")
    if text is not None:
        alert = alert.filter(has_text=text)
    expect(alert).to_have_count(1, timeout=5000)
    return alert


def only_button(page, name: str):
    return only_role(page, "button", name=name)


def only_region(page, name: str):
    return only_role(page, "region", name=name)


def only_status(page, text: str):
    status = page.get_by_role("status").filter(has_text=text)
    expect(status).to_have_count(1, timeout=5000)
    return status


class MockWSConnection:
    """Wraps a single WebSocket connection from the SPA."""

    def __init__(self, ws: ServerConnection):
        self.ws = ws
        self.received: list[dict[str, object]] = []
        self.lock = threading.Lock()

    def send_event(self, event: str, payload: dict[str, object] | None = None):
        msg = json.dumps({"event": event, "payload": payload or {}})
        self.ws.send(msg)

    def send_raw(self, raw: str):
        self.ws.send(raw)

    def close(self, code: int | None = None, reason: str = ""):
        if code is None:
            self.ws.close()
        else:
            self.ws.close(code, reason)

    def events_of(self, event: str) -> list[dict[str, object]]:
        with self.lock:
            return [e for e in self.received if e.get("event") == event]


class MockWSServer:
    """Mock WebSocket server for frontend tests.

    Runs in a background thread. Supports handler registration to
    auto-respond to events from the SPA.
    """

    def __init__(self, host: str = "localhost"):
        self.host = host
        self.port: int = 0
        self.connections: list[MockWSConnection] = []
        self._handlers: dict[
            str, Callable[[MockWSConnection, dict[str, object]], None]
        ] = {}
        self._lock = threading.Lock()
        self._server: Server | None = None
        self._thread: threading.Thread | None = None
        self.last_error: Exception | None = None

    def on(
        self,
        event: str,
        handler: Callable[[MockWSConnection, dict[str, object]], None],
    ):
        with self._lock:
            self._handlers[event] = handler

    def on_respond(
        self, event: str, response_event: str, response_payload: dict[str, object]
    ):
        def _handler(conn: MockWSConnection, _payload: dict[str, object]) -> None:
            conn.send_event(response_event, response_payload)

        with self._lock:
            self._handlers[event] = _handler

    def has_handler(self, event: str) -> bool:
        with self._lock:
            return event in self._handlers

    def broadcast(self, event: str, payload: dict[str, object] | None = None):
        with self._lock:
            targets = list(self.connections)
        for conn in targets:
            try:
                conn.send_event(event, payload)
            except Exception as exc:
                self.last_error = exc

    def _handle_connection(self, ws: ServerConnection):
        conn = MockWSConnection(ws)
        with self._lock:
            self.connections.append(conn)
        try:
            for raw in ws:
                data = json.loads(raw)
                with conn.lock:
                    conn.received.append(data)
                event = data.get("event", "")
                with self._lock:
                    handler = self._handlers.get(event)
                if handler is not None:
                    handler(conn, data.get("payload", {}))
        except Exception as exc:
            self.last_error = exc

    def start(self):
        self._server = ws_serve(
            self._handle_connection,
            host=self.host,
            port=0,
        )
        self.port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=3)

    def ensure_running(self):
        """Start the server if it has been stopped (or never started).

        The port may differ after a restart; callers reading ``url`` after
        ``ensure_running`` always see the current bind.
        """
        if self._thread is None or not self._thread.is_alive():
            self.start()

    def reset(self):
        with self._lock:
            conns = list(self.connections)
            self.connections.clear()
            self._handlers.clear()
        for conn in conns:
            try:
                conn.close()
            except Exception as exc:
                self.last_error = exc

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    @property
    def latest_connection(self) -> MockWSConnection | None:
        with self._lock:
            return self.connections[-1] if self.connections else None


SAMPLE_SONGS = [
    {
        "id": f"song{i}",
        "title": f"Song {i}",
        "artist": f"Artist {i}",
        "artworkUrl": None,
    }
    for i in range(1, 11)
]


def error_response_json(message: str) -> str:
    return ErrorResponse(error=message).model_dump_json()


def get_room_response_json() -> str:
    return GetRoomResponse200(exists=True).model_dump_json()


def get_session_response_json() -> str:
    return GetSessionResponse200(ready=True).model_dump_json()


def get_token_response_json(token: str, expires_at: datetime) -> str:
    return GetTokenResponse200(token=token, expiresAt=expires_at).model_dump_json()


def post_room_response_json(code: str) -> str:
    return PostRoomResponse201(code=code).model_dump_json()


def session_cookie_header(player_id: str) -> str:
    return (
        f"{SESSION_COOKIE}={player_id}; Path=/; Max-Age=31536000; "
        "HttpOnly; Secure; SameSite=Lax"
    )


def utc_datetime(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def install_websocket_route(page, websocket_url: str) -> None:
    """Route the SPA's /ws connection to the frontend mock WebSocket server."""
    target_url = json.dumps(websocket_url)
    page.add_init_script(f"""
        (() => {{
            window.__ATERUTA_WS_TARGET__ = {target_url};
            window.__ATERUTA_WS_FAIL__ = false;
            if (window.__ATERUTA_WS_ATTEMPTS__ !== undefined) {{
                return;
            }}
            const NativeWebSocket = window.WebSocket;
            const attempts = [];
            const shouldRoute = (url) => {{
                try {{
                    return new URL(String(url), window.location.href).pathname === "/ws";
                }} catch {{
                    return false;
                }}
            }};
            class FailingWebSocket extends EventTarget {{
                constructor(url) {{
                    super();
                    this.url = String(url);
                    this.readyState = NativeWebSocket.CONNECTING;
                    this.protocol = "";
                    this.extensions = "";
                    this.binaryType = "blob";
                    this.bufferedAmount = 0;
                    window.setTimeout(() => this.fail(), 0);
                }}
                close(code = 1000, reason = "") {{
                    if (this.readyState === NativeWebSocket.CLOSED) {{
                        return;
                    }}
                    this.readyState = NativeWebSocket.CLOSED;
                    this.dispatchClose(code, reason);
                }}
                fail() {{
                    if (this.readyState === NativeWebSocket.CLOSED) {{
                        return;
                    }}
                    this.readyState = NativeWebSocket.CLOSED;
                    this.dispatchEvent(new Event("error"));
                    this.dispatchClose(1006, "");
                }}
                send() {{}}
                dispatchClose(code, reason) {{
                    const event = new CloseEvent("close", {{
                        code,
                        reason,
                        wasClean: code === 1000,
                    }});
                    this.dispatchEvent(event);
                    this.onclose?.(event);
                }}
            }}
            function WrappedWebSocket(url, protocols) {{
                const requestedUrl = String(url);
                attempts.push({{ url: requestedUrl, at: Date.now() }});
                if (shouldRoute(requestedUrl) && window.__ATERUTA_WS_FAIL__ === true) {{
                    return new FailingWebSocket(requestedUrl);
                }}
                const nextUrl = shouldRoute(requestedUrl)
                    ? window.__ATERUTA_WS_TARGET__
                    : url;
                if (protocols === undefined) {{
                    return new NativeWebSocket(nextUrl);
                }}
                return new NativeWebSocket(nextUrl, protocols);
            }}
            WrappedWebSocket.prototype = NativeWebSocket.prototype;
            Object.setPrototypeOf(WrappedWebSocket, NativeWebSocket);
            window.__ATERUTA_WS_ATTEMPTS__ = attempts;
            window.WebSocket = WrappedWebSocket;
        }})();
    """)
    page.evaluate(
        f"""() => {{
            window.__ATERUTA_WS_TARGET__ = {target_url};
            window.__ATERUTA_WS_FAIL__ = false;
        }}"""
    )


def install_failing_websocket_route(page) -> None:
    """Make the SPA's /ws connection fail inside the browser harness."""
    page.add_init_script("""
        window.__ATERUTA_WS_FAIL__ = true;
    """)
    page.evaluate("() => { window.__ATERUTA_WS_FAIL__ = true; }")


def make_settings_payload(
    host_player_id: str,
    active_players: Sequence[Mapping[str, object]],
    *,
    songs: Sequence[Mapping[str, object]] | None = None,
    inactive_players: Sequence[Mapping[str, object]] | None = None,
    total_rounds: int | None = None,
    playback_durations: Sequence[int] | None = None,
    rank_points: Sequence[int] | None = None,
    lockout_duration: float | None = None,
    attempts_limit: int | None = None,
) -> dict[str, object]:
    return {
        "hostPlayerId": host_player_id,
        "songs": list(songs) if songs is not None else [],
        "totalRounds": total_rounds,
        "playbackDurations": list(playback_durations)
        if playback_durations is not None
        else [],
        "rankPoints": list(rank_points) if rank_points is not None else [],
        "lockoutDuration": lockout_duration,
        "attemptsLimit": attempts_limit,
        "activePlayers": list(active_players),
        "inactivePlayers": list(inactive_players) if inactive_players else [],
    }


def make_room_state_payload(
    phase: str,
    active_players: Sequence[Mapping[str, object]],
    *,
    current_round: int = 1,
    playback_duration_index: int = 0,
    inactive_players: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "phase": phase,
        "currentRound": current_round,
        "playbackDurationIndex": playback_duration_index,
        "activePlayers": list(active_players),
        "inactivePlayers": list(inactive_players) if inactive_players else [],
    }


def setup_room_route(spa_page, code="1234", status=200, error=None):
    """Set up a route for GET /api/room/{code}."""
    if error:
        spa_page.route(
            f"**/api/room/{code}",
            lambda route: route.fulfill(
                status=status,
                content_type="application/json",
                body=error_response_json(error),
            ),
        )
    else:
        spa_page.route(
            f"**/api/room/{code}",
            lambda route: route.fulfill(
                status=status,
                content_type="application/json",
                body=get_room_response_json(),
            ),
        )


@dataclass
class Scenario:
    """Bundles the inputs ``setup_scenario`` needs to enter a room.

    The setter is shaped as a single named-context object so callers don't
    have to remember a long positional/keyword list when extending the
    scenario shape.
    """

    host_player_id: str
    active_players: Sequence[Mapping[str, object]]
    phase: str | None = None
    code: str = "1234"
    songs: Sequence[Mapping[str, object]] | None = None
    inactive_players: Sequence[Mapping[str, object]] | None = None
    current_round: int = 1
    total_rounds: int = 10
    lockout_duration: float = 5
    attempts_limit: int = 3
    extra_settings: Mapping[str, object] = field(default_factory=dict)


def setup_scenario(
    spa_page,
    mock_ws_server,
    frontend_url,
    scenario: Scenario,
    *,
    wait_for_networkidle: bool = True,
):
    """Set up a room scenario and navigate to it.

    ``Scenario.phase`` controls the entry screen: None for lobby, "playing"
    for game, "finished" for result. MusicKit setup (``configure_musickit_api_mock``)
    must be called BEFORE this function.
    """

    if scenario.phase:
        songs = (
            list(scenario.songs)
            if scenario.songs
            else SAMPLE_SONGS[: scenario.total_rounds]
        )
    else:
        songs = list(scenario.songs) if scenario.songs else []

    if scenario.phase is not None:
        settings = make_settings_payload(
            scenario.host_player_id,
            scenario.active_players,
            songs=songs,
            inactive_players=scenario.inactive_players,
            total_rounds=scenario.total_rounds,
            playback_durations=[1, 2, 4, 8, 16],
            rank_points=[4, 2, 1],
            lockout_duration=scenario.lockout_duration,
            attempts_limit=scenario.attempts_limit,
        )
    else:
        settings = make_settings_payload(
            scenario.host_player_id,
            scenario.active_players,
            songs=songs,
            inactive_players=scenario.inactive_players,
            total_rounds=None,
            playback_durations=[],
            rank_points=[],
            lockout_duration=None,
            attempts_limit=None,
        )
    settings.update(scenario.extra_settings)

    if scenario.phase is not None:
        phase = scenario.phase
        state_players = [{"id": p["id"], "score": 0} for p in scenario.active_players]

        def join_handler(conn, _payload):
            conn.send_event("room:settings", settings)
            conn.send_event(
                "room:state",
                make_room_state_payload(
                    phase,
                    state_players,
                    current_round=scenario.current_round,
                ),
            )
            if scenario.host_player_id == SELF_PLAYER_ID:
                conn.send_event(
                    "game:shuffled-songs",
                    {"shuffledSongIds": [s["id"] for s in songs]},
                )

        setup_room_route(spa_page, scenario.code)
        mock_ws_server.on("room:join", join_handler)
    else:
        setup_room_route(spa_page, scenario.code)
        mock_ws_server.on_respond("room:join", "room:settings", settings)

    if scenario.host_player_id == SELF_PLAYER_ID:
        spa_page.route(
            "**/api/room",
            lambda route: route.fulfill(
                status=201,
                content_type="application/json",
                body=post_room_response_json(scenario.code),
            ),
        )
        spa_page.goto(frontend_url)
        spa_page.get_by_role("button", name="Create Room").click()
        spa_page.wait_for_url(f"**/room/{scenario.code}", timeout=5000)
    else:
        spa_page.goto(f"{frontend_url}room/{scenario.code}")
    spa_page.wait_for_load_state("networkidle" if wait_for_networkidle else "load")
    spa_page.wait_for_timeout(2000 if scenario.phase else 1000)


def host_scenario(
    *,
    phase: str | None = None,
    songs: Sequence[Mapping[str, object]] | None = None,
    inactive_players: Sequence[Mapping[str, object]] | None = None,
    current_round: int = 1,
    total_rounds: int = 10,
    lockout_duration: float = 5,
    attempts_limit: int = 3,
) -> Scenario:
    """Default ``Scenario`` where SELF is the lone host."""
    return Scenario(
        host_player_id=SELF_PLAYER_ID,
        active_players=[{"id": SELF_PLAYER_ID, "nickname": "Host", "handicap": 0}],
        phase=phase,
        songs=songs,
        inactive_players=inactive_players,
        current_round=current_round,
        total_rounds=total_rounds,
        lockout_duration=lockout_duration,
        attempts_limit=attempts_limit,
    )


def guest_scenario(
    *,
    phase: str | None = None,
    handicap: float = 0,
    songs: Sequence[Mapping[str, object]] | None = None,
    inactive_players: Sequence[Mapping[str, object]] | None = None,
    current_round: int = 1,
    total_rounds: int = 10,
    lockout_duration: float = 5,
    attempts_limit: int = 3,
) -> Scenario:
    """Default ``Scenario`` where SELF is a non-host player joining a host."""
    return Scenario(
        host_player_id="player-2",
        active_players=[
            {"id": "player-2", "nickname": "Host", "handicap": 0},
            {"id": SELF_PLAYER_ID, "nickname": "Player 1", "handicap": handicap},
        ],
        phase=phase,
        songs=songs,
        inactive_players=inactive_players,
        current_round=current_round,
        total_rounds=total_rounds,
        lockout_duration=lockout_duration,
        attempts_limit=attempts_limit,
    )


def send_reveal(conn, song=None, winners=None):
    """Send a game:reveal event."""
    song = song or {
        "id": "song1",
        "title": "Song 1",
        "artist": "Artist 1",
        "artworkUrl": None,
    }
    conn.send_event(
        "game:reveal",
        {
            "song": song,
            "winners": winners or [],
        },
    )
