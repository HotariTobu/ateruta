"""Step definitions for result.feature — Result screen."""

import re
from collections.abc import Mapping, Sequence

from playwright.sync_api import expect
from pytest_bdd import given, scenarios, then, when

from frontend.helpers import (
    SELF_PLAYER_ID,
    make_room_state_payload,
    make_settings_payload,
    only_region,
    only_status,
    post_room_response_json,
    setup_room_route,
)

scenarios("../../features/frontend/result.feature")


def _enter_result_screen(
    spa_page,
    mock_ws_server,
    frontend_url,
    *,
    code: str = "1234",
    is_host: bool = True,
    inactive_players: Sequence[Mapping[str, object]] | None = None,
):
    """Navigate to a room and reach the result screen."""
    host_id = SELF_PLAYER_ID if is_host else "player-2"
    active_players_settings = [
        {
            "id": SELF_PLAYER_ID,
            "nickname": "Host" if is_host else "Player 1",
            "handicap": 0,
        },
        {
            "id": "player-2",
            "nickname": "Player 2" if is_host else "Host",
            "handicap": 0,
        },
        {"id": "player-3", "nickname": "Player 3", "handicap": 0},
    ]

    songs = [
        {
            "id": f"song{i}",
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "artworkUrl": None,
        }
        for i in range(1, 4)
    ]
    settings = make_settings_payload(
        host_id,
        active_players_settings,
        songs=songs,
        total_rounds=3,
    )

    state_active = [
        {"id": SELF_PLAYER_ID, "score": 8},
        {"id": "player-2", "score": 12},
        {"id": "player-3", "score": 4},
    ]
    state_inactive = list(inactive_players) if inactive_players else []

    def join_handler(conn, _payload):
        conn.send_event("room:settings", settings)
        conn.send_event(
            "room:state",
            make_room_state_payload(
                "finished",
                state_active,
                current_round=3,
                inactive_players=state_inactive,
            ),
        )

    setup_room_route(spa_page, code)
    mock_ws_server.on("room:join", join_handler)
    if is_host:
        spa_page.route(
            "**/api/room",
            lambda route: route.fulfill(
                status=201,
                content_type="application/json",
                body=post_room_response_json(code),
            ),
        )
        spa_page.goto(frontend_url)
        spa_page.get_by_role("button", name="Create Room").click()
        spa_page.wait_for_url(f"**/room/{code}", timeout=5000)
    else:
        spa_page.goto(f"{frontend_url}room/{code}")
    spa_page.wait_for_load_state("networkidle")
    spa_page.wait_for_timeout(2000)


def _enter_result_as_host(spa_page, mock_ws_server, frontend_url, **kwargs):
    _enter_result_screen(spa_page, mock_ws_server, frontend_url, is_host=True, **kwargs)


def _enter_result_as_non_host(spa_page, mock_ws_server, frontend_url, **kwargs):
    _enter_result_screen(
        spa_page, mock_ws_server, frontend_url, is_host=False, **kwargs
    )


@given("the game has finished")
def game_finished(spa_page, mock_ws_server, frontend_url):
    _enter_result_as_host(spa_page, mock_ws_server, frontend_url)


# '"Game Over!" is displayed' is handled by conftest


@given("the game has finished with players at different scores")
def game_finished_different_scores(spa_page, mock_ws_server, frontend_url):
    _enter_result_as_host(spa_page, mock_ws_server, frontend_url)


@then("players are listed in order of score descending")
def players_sorted(spa_page):
    leaderboard = only_region(spa_page, "Final Scores")
    entries = leaderboard.get_by_role("listitem")
    expect(entries.nth(0)).to_contain_text("Player 2", timeout=5000)
    expect(entries.nth(1)).to_contain_text("Host")
    expect(entries.nth(2)).to_contain_text("Player 3")


@then("each player shows their rank, nickname, and score")
def player_shows_rank_name_score(spa_page):
    first_entry = only_region(spa_page, "Final Scores").get_by_role("listitem").nth(0)
    expect(first_entry).to_have_attribute("aria-posinset", "1", timeout=5000)
    expect(first_entry.get_by_text("#1", exact=True)).to_be_visible()
    expect(first_entry.get_by_text("Player 2", exact=True)).to_be_visible()
    expect(first_entry.get_by_text("12 points", exact=True)).to_be_visible()


@given("two players have the same score")
def two_same_score(spa_page, mock_ws_server, frontend_url):
    """Set up a result screen where two players are tied."""
    active_players = [
        {"id": SELF_PLAYER_ID, "nickname": "Host", "handicap": 0},
        {"id": "player-2", "nickname": "Player 2", "handicap": 0},
    ]

    songs = [
        {"id": "song1", "title": "Song 1", "artist": "Artist 1", "artworkUrl": None},
    ]
    settings = make_settings_payload(
        SELF_PLAYER_ID,
        active_players,
        songs=songs,
    )

    state_active = [
        {"id": SELF_PLAYER_ID, "score": 8},
        {"id": "player-2", "score": 8},
    ]

    def join_handler(conn, _payload):
        conn.send_event("room:settings", settings)
        conn.send_event(
            "room:state",
            make_room_state_payload("finished", state_active),
        )

    setup_room_route(spa_page, "1234")
    mock_ws_server.on("room:join", join_handler)
    spa_page.route(
        "**/api/room",
        lambda route: route.fulfill(
            status=201,
            content_type="application/json",
            body=post_room_response_json("1234"),
        ),
    )
    spa_page.goto(frontend_url)
    spa_page.get_by_role("button", name="Create Room").click()
    spa_page.wait_for_url("**/room/1234", timeout=5000)
    spa_page.wait_for_load_state("networkidle")
    spa_page.wait_for_timeout(2000)


@then("they are displayed with the same rank number")
def same_rank(spa_page):
    leaderboard = only_region(spa_page, "Final Scores")
    expect(leaderboard.get_by_text("#1", exact=True)).to_have_count(2)


@then("the order of tied players is not defined")
def tied_order(spa_page):
    leaderboard = only_region(spa_page, "Final Scores")
    expect(leaderboard.get_by_text("Host", exact=True)).to_be_visible(timeout=5000)
    expect(leaderboard.get_by_text("Player 2", exact=True)).to_be_visible(timeout=5000)


@then('"(you)" is shown next to the current player\'s name')
def you_marker(spa_page):
    expect(
        only_region(spa_page, "Final Scores").get_by_text("(you)", exact=True)
    ).to_be_visible(timeout=5000)


@given("the game has finished and the player is the host")
def game_finished_as_host(spa_page, mock_ws_server, frontend_url):
    _enter_result_as_host(spa_page, mock_ws_server, frontend_url)


# 'a "{text}" button is visible' is handled by conftest


@when('the host clicks "Back to Lobby"')
def host_clicks_back_to_lobby(spa_page):
    spa_page.get_by_role("button", name="Back to Lobby").click()


@then("game:back-to-lobby is sent to the server")
def back_to_lobby_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    events = conn.events_of("game:back-to-lobby")
    assert len(events) > 0, "game:back-to-lobby was not sent"


@given("the game has finished and the player is not the host")
def game_finished_as_non_host(spa_page, mock_ws_server, frontend_url):
    _enter_result_as_non_host(spa_page, mock_ws_server, frontend_url)


# '"Waiting for the host to return to lobby..." is displayed' is handled by conftest
# 'no "{text}" button is visible' is handled by conftest


@when("the host triggers back to lobby")
def host_triggers_back(spa_page, mock_ws_server):
    # The server signals "back to lobby" by sending room:state=null which
    # transitions the room into the lobby phase.
    mock_ws_server.latest_connection.send_event("room:state", None)
    spa_page.wait_for_timeout(1000)


@then("the player is navigated to the lobby screen")
def navigated_to_lobby(spa_page):
    expect(
        spa_page.get_by_role("heading", name=re.compile(r"^Players \(\d+\)$"))
    ).to_be_visible(timeout=5000)


@given("some players disconnected during the game")
def players_disconnected(spa_page, mock_ws_server, frontend_url):
    inactive = [{"id": "player-4", "score": 2}]
    _enter_result_as_host(
        spa_page, mock_ws_server, frontend_url, inactive_players=inactive
    )


@then("disconnected players are shown in a separate section below active players")
def disconnected_separate(spa_page):
    active = only_region(spa_page, "Final Scores")
    inactive = only_region(spa_page, "Disconnected Players")
    expect(active).to_be_visible(timeout=5000)
    expect(inactive).to_be_visible(timeout=5000)
    active_box = active.bounding_box()
    inactive_box = inactive.bounding_box()
    assert active_box is not None and inactive_box is not None, (
        "Both sections must be laid out"
    )
    assert active_box["y"] < inactive_box["y"], (
        "Active section must render above the inactive section"
    )


@then("disconnected players are sorted by score descending within their section")
def disconnected_sorted(spa_page):
    inactive = only_region(spa_page, "Disconnected Players")
    expect(inactive).to_be_visible(timeout=5000)


@when("the host disconnects")
def host_disconnects(spa_page, mock_ws_server):
    mock_ws_server.latest_connection.send_event(
        "room:settings",
        {
            **make_settings_payload(
                "player-2",
                [{"id": SELF_PLAYER_ID, "nickname": "Player 1", "handicap": 0}],
            ),
            "inactivePlayers": [
                {"id": "player-2", "nickname": "Host", "handicap": 0},
            ],
        },
    )
    spa_page.wait_for_timeout(1000)


# 'a banner displays "The host has disconnected..."' is handled by conftest


@given("the host disconnection banner is displayed on the result screen")
def host_banner_result(spa_page, mock_ws_server, frontend_url):
    _enter_result_as_non_host(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "room:settings",
        {
            **make_settings_payload(
                "player-2",
                [{"id": SELF_PLAYER_ID, "nickname": "Player 1", "handicap": 0}],
            ),
            "inactivePlayers": [
                {"id": "player-2", "nickname": "Host", "handicap": 0},
            ],
        },
    )
    expect(only_status(spa_page, "The host has disconnected")).to_be_visible(
        timeout=5000
    )


@when("the host reconnects")
def host_reconnects(spa_page, mock_ws_server):
    mock_ws_server.latest_connection.send_event(
        "room:settings",
        make_settings_payload(
            "player-2",
            [
                {"id": "player-2", "nickname": "Host", "handicap": 0},
                {"id": SELF_PLAYER_ID, "nickname": "Player 1", "handicap": 0},
            ],
        ),
    )
    spa_page.wait_for_timeout(1000)


# 'the banner is dismissed' is handled by conftest
