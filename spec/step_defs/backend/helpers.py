"""Shared test helpers for backend tests.

PlayerClient wraps HTTP and WebSocket interactions for a single player.
setup_valid_game configures and starts a game with valid settings.
"""

import json
import threading
import time
import httpx
from pydantic import ValidationError

from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as ws_connect

from backend.schemas import (
    SC_EVENT_SCHEMAS,
    SESSION_COOKIE,
    ErrorResponse,
    GetRoomResponse200,
    GetTokenResponse200,
    PostRoomResponse201,
)


def close_code_from_exception(
    exc: ConnectionClosedOK | ConnectionClosedError,
    ws: ClientConnection | None,
) -> int | None:
    if ws is not None and ws.close_code is not None:
        return ws.close_code
    if exc.rcvd is not None:
        return exc.rcvd.code
    if exc.sent is not None:
        return exc.sent.code
    return None


class PlayerClient:
    """Test helper wrapping HTTP and WebSocket interactions for one player."""

    def __init__(self, server_url: str, ws_url: str):
        self.server_url = server_url
        self.ws_url = ws_url
        self.http = httpx.Client(base_url=server_url, timeout=10)
        self.ws: ClientConnection | None = None
        self.player_id: str | None = None
        self.room_code: str | None = None
        self._events: list[dict[str, object]] = []
        self._read_index: int = 0
        self._lock = threading.Lock()
        self._new_event = threading.Event()
        self._recv_thread: threading.Thread | None = None
        self._running = False
        self.close_code: int | None = None
        self.last_error: Exception | None = None

    def init_session(self) -> str:
        resp = self.http.get("/api/session")
        assert resp.status_code == 200
        self.player_id = resp.cookies.get(SESSION_COOKIE)
        assert self.player_id, "Session cookie not returned"
        self.http.cookies.set(SESSION_COOKIE, self.player_id)
        return self.player_id

    def connect(self):
        assert self.player_id, "Call init_session() first"
        self.ws = ws_connect(
            self.ws_url,
            additional_headers={"Cookie": f"{SESSION_COOKIE}={self.player_id}"},
        )
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def _recv_loop(self):
        assert self.ws is not None
        try:
            while self._running:
                try:
                    raw = self.ws.recv(timeout=0.5)
                    data = json.loads(raw)
                    self._validate_schema(data)
                    with self._lock:
                        self._events.append(data)
                    self._new_event.set()
                except TimeoutError:
                    continue
        except (ConnectionClosedOK, ConnectionClosedError) as exc:
            self.close_code = close_code_from_exception(exc, self.ws)
        except Exception as exc:
            self.last_error = exc

    @staticmethod
    def _validate_schema(data: dict[str, object]) -> None:
        event_name = data.get("event")
        if not isinstance(event_name, str):
            return
        model = SC_EVENT_SCHEMAS.get(event_name)
        if model is None:
            return
        payload = data.get("payload", {})
        if payload is None:
            return
        try:
            model.model_validate(payload)
        except ValidationError as exc:
            raise AssertionError(
                f"Schema validation failed for {event_name}: {exc}"
            ) from exc

    def send(self, event: str, payload: dict[str, object] | None = None):
        assert self.ws is not None
        msg = json.dumps({"event": event, "payload": payload or {}})
        self.ws.send(msg)

    def send_raw(self, raw: str):
        assert self.ws is not None
        self.ws.send(raw)

    def recv_event(self, timeout: float = 5.0) -> dict[str, object]:
        """Return the next unread event in arrival order."""
        # Surface recv-loop errors (schema violation etc.) immediately rather
        # than waiting for teardown — otherwise the test fails with a generic
        # TimeoutError and the real cause is hidden until close().
        if self.last_error is not None:
            raise AssertionError(
                f"PlayerClient recv loop errored: {self.last_error!r}"
            ) from self.last_error
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._read_index < len(self._events):
                    event = self._events[self._read_index]
                    self._read_index += 1
                    return event
                self._new_event.clear()
            remaining = max(0.01, deadline - time.time())
            self._new_event.wait(timeout=remaining)
            if self.last_error is not None:
                raise AssertionError(
                    f"PlayerClient recv loop errored: {self.last_error!r}"
                ) from self.last_error
        raise TimeoutError(f"No event received within {timeout}s")

    def expect_event(self, event_name: str, timeout: float = 5.0) -> dict[str, object]:
        """Wait for the next event with the given name, consuming others."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.01, deadline - time.time())
            try:
                event = self.recv_event(timeout=remaining)
            except TimeoutError:
                break
            if event["event"] == event_name:
                return event
        raise TimeoutError(f"Event '{event_name}' not received within {timeout}s")

    def expect_error(self, message: str, timeout: float = 5.0) -> dict[str, object]:
        from .schemas import ErrorPayload

        event = self.expect_event("error", timeout=timeout)
        error = ErrorPayload.model_validate(event["payload"])
        assert error.message == message, (
            f"Expected error '{message}', got '{error.message}'"
        )
        return event

    def expect_settings_validation_error(
        self, detail: str, timeout: float = 5.0
    ) -> dict[str, object]:
        from .schemas import ErrorPayload

        event = self.expect_event("error", timeout=timeout)
        error = ErrorPayload.model_validate(event["payload"])
        assert error.message == "Settings validation failed", (
            "Expected settings validation header "
            f"'Settings validation failed', got '{error.message}'"
        )
        assert error.details is not None, "Settings validation details are required"
        assert detail in error.details, (
            f"Expected settings validation detail '{detail}', got {error.details}"
        )
        return event

    def collect_events(
        self, count: int, timeout: float = 5.0
    ) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        deadline = time.time() + timeout
        while len(events) < count and time.time() < deadline:
            remaining = max(0.01, deadline - time.time())
            try:
                events.append(self.recv_event(timeout=remaining))
            except TimeoutError:
                break
        return events

    def drain_events(self, wait: float = 0.5) -> list[dict[str, object]]:
        """Collect events, waiting up to *wait* seconds for events to settle."""
        deadline = time.time() + wait
        events: list[dict[str, object]] = []
        while True:
            with self._lock:
                while self._read_index < len(self._events):
                    events.append(self._events[self._read_index])
                    self._read_index += 1
                self._new_event.clear()
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            if not self._new_event.wait(timeout=remaining):
                break
        return events

    def assert_no_event(self, event_name: str, timeout: float = 1.0):
        """Assert that a specific event does NOT arrive within timeout."""
        events = self.drain_events(wait=timeout)
        matching = [e for e in events if e["event"] == event_name]
        assert not matching, f"Unexpected event '{event_name}' received"

    def find_event(self, event_name: str) -> dict[str, object] | None:
        """Find the first event with the given name in all received events."""
        with self._lock:
            for e in self._events:
                if e["event"] == event_name:
                    return e
        return None

    def find_last_event(self, event_name: str) -> dict[str, object] | None:
        """Find the last event with the given name in all received events."""
        with self._lock:
            for e in reversed(self._events):
                if e["event"] == event_name:
                    return e
        return None

    def find_all_events(self, event_name: str) -> list[dict[str, object]]:
        """Find all events with the given name in all received events."""
        with self._lock:
            return [e for e in self._events if e["event"] == event_name]

    def reset_read_index(self):
        with self._lock:
            self._read_index = len(self._events)

    def create_room(self) -> str:
        resp = self.http.post("/api/room")
        assert resp.status_code == 201, (
            f"Room creation failed: {resp.status_code} {resp.text}"
        )
        body = resp.json()
        PostRoomResponse201.model_validate(body)
        return body["code"]

    def check_room(self, code: str) -> httpx.Response:
        resp = self.http.get(f"/api/room/{code}")
        if resp.status_code == 200:
            GetRoomResponse200.model_validate(resp.json())
        elif resp.status_code >= 400:
            ErrorResponse.model_validate(resp.json())
        return resp

    def get_token(self) -> httpx.Response:
        resp = self.http.get("/api/token")
        if resp.status_code == 200:
            GetTokenResponse200.model_validate(resp.json())
        elif resp.status_code >= 400:
            ErrorResponse.model_validate(resp.json())
        return resp

    def join_room(self, code: str):
        self.send("room:join", {"code": code})

    def leave_room(self):
        self.send("room:leave")

    def close(self):
        self._running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception as exc:
                self.last_error = exc
        if self._recv_thread:
            self._recv_thread.join(timeout=3)
        self.http.close()
        # Surface any background recv-loop error (e.g. schema validation
        # failure) that would otherwise be silently swallowed.
        if self.last_error is not None:
            raise AssertionError(
                f"PlayerClient recv loop raised: {self.last_error!r}"
            ) from self.last_error

    def disconnect(self, settle: float = 0.5):
        """Close WebSocket only (keep HTTP client alive for reconnection).

        *settle* seconds are waited after closing so that the server has
        time to process the disconnection before the test continues.
        """
        self._running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception as exc:
                self.last_error = exc
        if self._recv_thread:
            self._recv_thread.join(timeout=3)
        self.ws = None
        self._recv_thread = None
        self.close_code = None
        if settle > 0:
            time.sleep(settle)

    def reconnect(self):
        """Re-establish WebSocket connection with the same session."""
        self.disconnect(settle=0)
        with self._lock:
            self._events = []
            self._read_index = 0
        self._new_event.clear()
        self.connect()


def create_room(
    make_player, n_players: int = 2
) -> tuple[PlayerClient, list[PlayerClient], str]:
    """Create a room with a host and *n_players* additional players."""
    host = make_player()
    code = host.create_room()
    host.join_room(code)
    host.expect_event("room:settings")

    players: list[PlayerClient] = []
    for _ in range(n_players):
        player = make_player()
        player.join_room(code)
        player.expect_event("room:settings")
        players.append(player)
        host.drain_events(wait=0.2)
        for prev in players[:-1]:
            prev.drain_events(wait=0.1)

    host.room_code = code
    return host, players, code


def drain_all(host: PlayerClient, players: list[PlayerClient]) -> None:
    """Drain events from host and all players."""
    host.drain_events(wait=0.3)
    for player in players:
        player.drain_events(wait=0.2)


def setup_valid_game(
    host: PlayerClient,
    players: list[PlayerClient],
    code: str,
    *,
    n_songs: int = 3,
    rank_points: list[int] | None = None,
    lockout_duration: float | None = None,
    attempts_limit: int | None = None,
) -> list[str]:
    """Configure valid settings and start a game. Returns shuffled song IDs."""
    songs = [
        {
            "id": f"song{i}",
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "artworkUrl": None,
        }
        for i in range(1, n_songs + 1)
    ]
    host.send(
        "room:settings",
        {
            "songs": songs,
            "totalRounds": n_songs,
            "playbackDurations": [1, 2, 4, 8, 16],
            "rankPoints": rank_points or [4, 2, 1],
            "lockoutDuration": lockout_duration if lockout_duration is not None else 5,
            "attemptsLimit": attempts_limit if attempts_limit is not None else 3,
        },
    )
    drain_all(host, players)

    host.send("game:start")
    drain_all(host, players)

    from .schemas import ShuffledSongsPayload

    event = host.find_event("game:shuffled-songs")
    assert event is not None, "Expected game:shuffled-songs event but none received"
    shuffled = ShuffledSongsPayload.model_validate(event["payload"])
    return shuffled.shuffledSongIds
