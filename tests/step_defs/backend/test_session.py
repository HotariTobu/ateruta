"""Step definitions for session.feature — session management and WebSocket error handling."""

import json

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from backend.helpers import create_room
from backend.schemas import SESSION_COOKIE


scenarios("../../features/backend/session.feature")


@when("a player connects via WebSocket", target_fixture="session_settings_event")
def player_connects(player, make_player):
    host, _, room_code = create_room(make_player, 0)
    player.join_room(room_code)
    return player.expect_event("room:settings")


@then('the player ID is read from the "ateruta-player-id" cookie')
def player_id_from_cookie(player, session_settings_event):
    active_ids = [p["id"] for p in session_settings_event["payload"]["activePlayers"]]
    assert player.player_id in active_ids, (
        "Server should resolve player ID from cookie and include it in activePlayers"
    )


@when(
    "a player connects via WebSocket without an ateruta-player-id cookie",
    target_fixture="ws_error",
)
def connect_without_cookie(backend_url, backend_ws_url):
    from websockets.sync.client import connect as ws_connect
    from websockets.exceptions import (
        ConnectionClosedError,
        ConnectionClosedOK,
        InvalidHandshake,
        InvalidStatus,
    )

    # Two acceptable rejection paths: (1) server rejects the WS handshake
    # (InvalidHandshake/InvalidStatus), (2) handshake succeeds but server
    # immediately closes the socket (recv → ConnectionClosed*).  Any other
    # outcome (e.g. server stays open and sends no events) is a spec violation.
    try:
        ws = ws_connect(backend_ws_url)
    except (InvalidHandshake, InvalidStatus):
        return {"closed": True, "via": "handshake_rejection"}

    try:
        ws.recv(timeout=3)
    except (ConnectionClosedError, ConnectionClosedOK):
        return {"closed": True, "via": "closed_after_open", "code": ws.close_code}
    except TimeoutError:
        return {
            "closed": False,
            "via": "no_close_within_timeout",
            "code": ws.close_code,
        }


@then("the connection is closed with an error")
@then("the connection is closed with close code 4401")
def connection_closed(ws_error):
    assert ws_error["closed"]
    assert ws_error.get("code") == 4401


@when(
    "a client calls an HTTP endpoint that requires player identification",
    target_fixture="http_response",
)
def client_calls_http_with_cookie(player):
    return player.http.post("/api/room")


@then("the player ID is read from the ateruta-player-id cookie")
def player_id_from_cookie_http(http_response):
    assert http_response.status_code == 201, (
        f"HTTP endpoint should succeed with cookie, got {http_response.status_code}"
    )


@when(
    "a client calls POST /api/room without an ateruta-player-id cookie",
    target_fixture="no_cookie_response",
)
def post_room_without_cookie(backend_url):
    client = httpx.Client(base_url=backend_url, timeout=10)
    try:
        resp = client.post("/api/room")
        return resp
    finally:
        client.close()


@when(
    "a client calls GET /api/room/{code} without an ateruta-player-id cookie",
    target_fixture="no_cookie_response",
)
def get_room_without_cookie(backend_url):
    client = httpx.Client(base_url=backend_url, timeout=10)
    try:
        resp = client.get("/api/room/1234")
        return resp
    finally:
        client.close()


@then(parsers.parse("the response status is {status:d}"))
def check_response_status(no_cookie_response, status):
    assert no_cookie_response.status_code == status


@when(
    "a client calls GET /api/token without an ateruta-player-id cookie",
    target_fixture="token_response",
)
def get_token_without_cookie(backend_url):
    client = httpx.Client(base_url=backend_url, timeout=10)
    try:
        return client.get("/api/token")
    finally:
        client.close()


@then("the response contains { token, expiresAt }")
def response_has_token_fields(token_response):
    data = token_response.json()
    assert "token" in data
    assert "expiresAt" in data


@pytest.fixture
def session_client(backend_url):
    client = httpx.Client(base_url=backend_url, timeout=10)
    yield client
    client.close()


@given("no ateruta-player-id cookie is present")
def no_cookie_present(session_client):
    assert SESSION_COOKIE not in session_client.cookies


@given("an ateruta-player-id cookie is already present")
def existing_cookie_present(session_client):
    first = session_client.get("/api/session")
    cookie_val = first.cookies.get(SESSION_COOKIE)
    assert cookie_val
    session_client.cookies.set(SESSION_COOKIE, cookie_val)


@when("a client calls GET /api/session", target_fixture="session_response")
def client_calls_session(session_client):
    return session_client.get("/api/session")


@then("a Set-Cookie header is returned with a new UUID")
def set_cookie_returned(session_response):
    set_cookie = session_response.headers.get("set-cookie", "")
    assert f"{SESSION_COOKIE}=" in set_cookie


@then(
    "the cookie attributes are HttpOnly, Secure, SameSite=Lax, Max-Age=31536000, Path=/"
)
def cookie_attributes(session_response):
    set_cookie = session_response.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=31536000" in set_cookie
    assert "path=/" in set_cookie


@then("the response body is { ready: true }")
def response_body_ready(session_response):
    data = session_response.json()
    assert data.get("ready") is True


@then("no Set-Cookie header is returned")
def no_set_cookie(session_response):
    set_cookie = session_response.headers.get("set-cookie", "")
    assert f"{SESSION_COOKIE}=" not in set_cookie


@given("Apple Music credentials are configured")
def apple_music_credentials():
    import os

    assert os.environ.get("APPLE_MUSIC_KEY_ID"), "APPLE_MUSIC_KEY_ID env var not set"


@when("a client calls GET /api/token", target_fixture="token_response")
def client_calls_token(player):
    resp = player.get_token()
    return resp


@then("the token is a JWT signed with ES256")
def token_is_jwt_es256(token_response):
    import base64

    data = token_response.json()
    token = data["token"]
    parts = token.split(".")
    assert len(parts) == 3
    header_padded = parts[0] + "=" * (4 - len(parts[0]) % 4)
    header = json.loads(base64.urlsafe_b64decode(header_padded))
    assert header.get("alg") == "ES256"


@then("the token is valid for 24 hours")
def token_valid_24h(token_response):
    from datetime import datetime, timedelta, timezone

    data = token_response.json()
    expires_at = datetime.fromisoformat(data["expiresAt"])
    now = datetime.now(timezone.utc)
    diff = expires_at - now
    assert timedelta(hours=23) < diff < timedelta(hours=25)


@given("the token generation fails for any reason", target_fixture="token_response")
def token_generation_fails():
    pytest.skip("Token generation failure cannot be triggered externally")


@then(
    "the server checks all WebSocket messages in the following order before event-specific checks:"
)
def ws_message_pre_checks(player, datatable):
    """Verify the pre-check order by sending messages that fail at each step.

    The player fixture is not in any room, so every send below also fails
    the row-4 ("Not in a room") check.  Receiving the row-1/2/3 error
    instead of row-4 implicitly proves rows 1, 2, 3 take priority over
    row 4 (i.e. 1<4, 2<4, 3<4 orderings).
    """
    # Row 1: invalid JSON. (1<2, 1<3 are vacuous — malformed input has
    # no parseable event or payload, so rows 2/3 cannot co-fail.)
    player.send_raw("not json")
    player.expect_error("Invalid message format")

    # Row 2: known event name check.
    player.send("unknown:event")
    player.expect_error("Unknown event")

    # Order 2<3: valid JSON + unknown event + unknown payload field — both
    # row 2 (event known) and row 3 (no unknown fields) would fail.  Row 2
    # must fire first.
    player.send("unknown:event", {"junk_field": 1})
    player.expect_error("Unknown event")

    # Row 3: unknown field in payload of a known event.
    player.send("room:join", {"code": "1234", "unknown_field": "value"})
    player.expect_error("Unknown fields in payload")

    # Row 4: in a room.  Sender is not in a room, so a valid event with a
    # valid payload reaches this check.
    player.send("room:settings", {"totalRounds": 5})
    player.expect_error("Not in a room")


@when(
    "the server receives a WebSocket message with an unknown event type",
    target_fixture="sender",
)
def send_unknown_event(player):
    player.send("unknown:event")
    return player


@then(parsers.parse('the sender receives an error event with "{message}"'))
def sender_receives_error(sender, message):
    sender.expect_error(message)


@when(
    "the server receives a WebSocket message that is not valid JSON",
    target_fixture="sender",
)
def send_malformed_message(player):
    player.send_raw("not valid json {{{")
    return player


@when(
    "the server receives a WebSocket message with unknown fields in the payload",
    target_fixture="sender",
)
def send_unknown_fields(player):
    player.send("room:join", {"code": "1234", "extra_field": "bad"})
    return player


@given("a player is not in any room")
def player_not_in_room(player):
    assert player.room_code is None


@when("the player sends any event other than room:join or room:leave")
def send_event_without_room(player):
    player.send("room:settings", {"totalRounds": 5})


@when("the player sends room:leave")
def send_room_leave(player):
    player.leave_room()
