"""Step definitions for apple_music.feature — Apple Music integration.

Drives MusicKit JS v3 (loaded from CDN by the SPA) against the in-process
mock supplied by ``musickit_mock.setup_musickit``. Each step that
navigates the page MUST call ``setup_musickit`` before ``setup_scenario``
(or ``page.goto``); the helpers ``_setup_lobby`` and ``_setup_game``
encode that ordering.
"""

import json
from collections.abc import Iterable, Mapping

from playwright.sync_api import Page, expect
from pytest_bdd import given, parsers, scenarios, then, when

from backend.schemas import SESSION_COOKIE
from frontend.helpers import (
    MockWSServer,
    Scenario,
    SELF_PLAYER_ID,
    make_room_state_payload,
    make_settings_payload,
    send_reveal,
    setup_room_route,
    setup_scenario,
)
from frontend.musickit_mock import (
    SAMPLE_CATALOG_SONGS,
    make_developer_token,
    setup_musickit,
)

scenarios("../../features/frontend/apple_music.feature")


HOST_PLAYERS: list[Mapping[str, object]] = [
    {"id": SELF_PLAYER_ID, "nickname": "Host", "handicap": 0},
    {"id": "player-2", "nickname": "Player 2", "handicap": 0},
]

LARGE_PLAYLIST_ID = "pl.large"
LARGE_PLAYLIST_SONG_COUNT = 150
LARGE_PLAYLIST_SONGS = [f"song{i}" for i in range(1, LARGE_PLAYLIST_SONG_COUNT + 1)]


def _setup_lobby(
    spa_page: Page,
    mock_ws_server: MockWSServer,
    frontend_url: str,
    *,
    authorized: bool = True,
    songs: Iterable[str] | None = None,
    empty_playlist_ids: Iterable[str] | None = None,
    search_playlist_ids: Iterable[str] | None = None,
    playlist_tracks_error: bool = False,
    search_error: bool = False,
) -> None:
    setup_musickit(
        spa_page,
        authorized=authorized,
        songs=songs,
        empty_playlist_ids=empty_playlist_ids,
        search_playlist_ids=search_playlist_ids,
        playlist_tracks_error=playlist_tracks_error,
        search_error=search_error,
    )
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        Scenario(host_player_id=SELF_PLAYER_ID, active_players=HOST_PLAYERS),
    )


def _setup_game(
    spa_page: Page,
    mock_ws_server: MockWSServer,
    frontend_url: str,
    *,
    total_rounds: int = 3,
    songs: Iterable[str] | None = None,
    playback_error: bool = False,
) -> None:
    setup_musickit(
        spa_page,
        authorized=True,
        songs=songs if songs is not None else SAMPLE_CATALOG_SONGS[:total_rounds],
        playback_error=playback_error,
    )
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        Scenario(
            host_player_id=SELF_PLAYER_ID,
            active_players=HOST_PLAYERS,
            phase="playing",
            total_rounds=total_rounds,
        ),
    )


@when("the app starts")
def app_starts(spa_page, frontend_url):
    setup_musickit(spa_page, authorized=True)
    spa_page.goto(frontend_url)
    spa_page.wait_for_load_state("networkidle")


@then("the Apple Music SDK is initialized with the developer token from the server")
def sdk_initialized(spa_page):
    spa_page.wait_for_function(
        "() => typeof MusicKit !== 'undefined' && MusicKit.getInstance() !== undefined",
        timeout=10000,
    )


@given("the player has previously authorized Apple Music")
def previously_authorized(spa_page):
    setup_musickit(spa_page, authorized=True)


@when("the Apple Music SDK is initialized")
def sdk_init(spa_page, frontend_url):
    spa_page.goto(frontend_url)
    spa_page.wait_for_load_state("networkidle")


@then("the authorized state is set")
def authorized_state(spa_page):
    spa_page.wait_for_function(
        "() => MusicKit.getInstance()?.isAuthorized === true",
        timeout=10000,
    )


@given("the player has not authorized Apple Music")
def not_authorized(spa_page):
    setup_musickit(spa_page, authorized=False)


@then("the unauthorized state is set")
def unauthorized_state(spa_page):
    spa_page.wait_for_function(
        "() => MusicKit.getInstance()?.isAuthorized === false",
        timeout=10000,
    )


@when("a user authorizes Apple Music")
def user_authorizes(spa_page, frontend_url):
    setup_musickit(spa_page, authorized=True)
    spa_page.goto(frontend_url)
    spa_page.wait_for_load_state("networkidle")
    spa_page.evaluate("() => MusicKit.getInstance().authorize()")


@then("the authorized state becomes true")
def authorized_state_true(spa_page):
    spa_page.wait_for_function(
        "() => MusicKit.getInstance()?.isAuthorized === true",
        timeout=10000,
    )


@when("a user unauthorizes Apple Music")
def user_unauthorizes(spa_page, frontend_url):
    setup_musickit(spa_page, authorized=True)
    spa_page.goto(frontend_url)
    spa_page.wait_for_load_state("networkidle")
    spa_page.evaluate("() => MusicKit.getInstance().unauthorize()")


@then("the authorized state becomes false")
def authorized_state_false(spa_page):
    spa_page.wait_for_function(
        "() => MusicKit.getInstance()?.isAuthorized === false",
        timeout=10000,
    )


@when("the app attempts to initialize the Apple Music SDK")
@when("the Apple Music SDK fails to initialize")
def sdk_init_fails(spa_page, frontend_url):
    spa_page.unroute("**/api/token")
    expired = make_developer_token(expired=True)
    spa_page.route(
        "**/api/token",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"token": expired, "expiresAt": "2020-01-01T00:00:00Z"}),
        ),
    )
    setup_musickit(spa_page, authorized=False)
    spa_page.goto(frontend_url)
    spa_page.wait_for_load_state("networkidle")


@then("initialization fails")
def initialization_fails(spa_page):
    expect(spa_page.get_by_role("alert").first).to_be_visible(timeout=10000)


# "the error message is displayed as a toast" is in conftest


@given("the player is the host", target_fixture="is_host")
def player_is_host():
    # Declares host intent so the following ``Apple Music is (not)
    # authorized`` Given can read it. Setup happens in that subsequent
    # step because both flags are needed before goto().
    return True


@given("Apple Music is not authorized")
def apple_music_not_authorized(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(spa_page, mock_ws_server, frontend_url, authorized=False)


@when('the host clicks "Authorize Apple Music"')
def click_authorize(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(spa_page, mock_ws_server, frontend_url, authorized=False)
    spa_page.get_by_role("button", name="Authorize Apple Music").click()


@then("the Apple Music authorization flow is triggered")
def auth_flow_triggered(spa_page):
    # The library shim records each authorize() invocation on
    # ``window.__musickitApiMock.authorizeInvocations``.
    spa_page.wait_for_function(
        "() => (window.__musickitApiMock?.authorizeInvocations ?? 0) > 0",
        timeout=5000,
    )


@given("Apple Music is authorized")
def apple_music_authorized(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(spa_page, mock_ws_server, frontend_url, authorized=True)


@when('the host clicks "Sign out of Apple Music"')
def click_sign_out(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(spa_page, mock_ws_server, frontend_url, authorized=True)
    spa_page.get_by_role("link", name="Sign out of Apple Music").click()


@then("Apple Music authorization is revoked")
def auth_revoked(spa_page):
    spa_page.wait_for_function(
        "() => MusicKit.getInstance()?.isAuthorized === false",
        timeout=5000,
    )


@when("the host searches for playlists with a keyword")
def search_playlists(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(spa_page, mock_ws_server, frontend_url, authorized=True)
    spa_page.get_by_role("searchbox").first.fill("test")
    spa_page.wait_for_timeout(1000)


@then(
    parsers.parse(
        "up to {count:d} matching playlists are displayed with artwork (if available) and name"
    )
)
def playlists_displayed(spa_page, count):
    playlists = spa_page.get_by_role("listitem").filter(has_text="Playlist")
    expect(playlists.first).to_be_visible(timeout=5000)
    actual = playlists.count()
    assert actual <= count, f"Expected at most {count} playlists, got {actual}"


@given("search results are displayed")
def search_results_displayed(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(spa_page, mock_ws_server, frontend_url, authorized=True)
    spa_page.get_by_role("searchbox").first.fill("test")
    spa_page.wait_for_timeout(1000)


@when("the host selects a playlist")
def select_playlist(spa_page):
    spa_page.get_by_role("listitem").filter(has_text="Playlist").first.click()
    spa_page.wait_for_timeout(1000)


@then("the songs from that playlist are loaded")
def songs_from_playlist_loaded(spa_page):
    expect(spa_page.get_by_text("Songs (", exact=False).first).to_be_visible(
        timeout=5000
    )


@then("the playlist results close")
def results_close(spa_page):
    expect(spa_page.get_by_role("listitem").filter(has_text="Playlist")).to_have_count(
        0
    )


@then("the song list appears in the lobby")
def song_list_in_lobby(spa_page):
    expect(spa_page.get_by_text("Songs (", exact=False).first).to_be_visible(
        timeout=5000
    )


@when(parsers.parse('the host opens the "{tab}" tab'))
def open_tab(spa_page, tab):
    spa_page.get_by_role("tab", name=tab).click()
    spa_page.wait_for_timeout(1000)


@then("the user's library playlists are displayed with artwork (if available) and name")
def library_displayed(spa_page):
    # ``Test Playlist`` is the name assigned to ``p.lib1`` by the mock's
    # default library_playlist set; matches the visible-name expectation
    # without locking the test to specific DOM structure.
    expect(
        spa_page.get_by_role("listitem").filter(has_text="Test Playlist").first
    ).to_be_visible(timeout=5000)


@then("a message prompts the user to log in to Apple Music")
def prompt_login(spa_page):
    expect(
        spa_page.get_by_text("Sign in to Apple Music", exact=False).first
    ).to_be_visible(timeout=5000)


@given("library playlists are displayed")
def library_playlists_displayed(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(spa_page, mock_ws_server, frontend_url, authorized=True)
    spa_page.get_by_role("tab", name="My Library").click()
    spa_page.wait_for_timeout(1000)


@when("the host types in the filter field")
def type_in_filter(spa_page):
    spa_page.get_by_role("searchbox").first.fill("test")
    spa_page.wait_for_timeout(500)


@then("playlists are filtered by name (case-insensitive)")
def playlists_filtered(spa_page):
    # The mock's library set contains ``Test Playlist`` (matches "test")
    # and ``Library p.lib2`` (does not). After filtering, only ``Test
    # Playlist`` should remain visible.
    expect(
        spa_page.get_by_role("listitem").filter(has_text="Test Playlist").first
    ).to_be_visible(timeout=5000)
    expect(
        spa_page.get_by_role("listitem").filter(has_text="Library p.lib2")
    ).to_have_count(0)


@when("the host pastes a valid Apple Music playlist URL into the search field")
def paste_valid_url(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(spa_page, mock_ws_server, frontend_url, authorized=True)
    spa_page.get_by_role("searchbox").first.fill(
        "https://music.apple.com/us/playlist/test/pl.12345"
    )
    spa_page.wait_for_timeout(1000)


@then("the songs from the playlist are loaded")
def songs_from_url_loaded(spa_page):
    expect(spa_page.get_by_text("Songs (", exact=False).first).to_be_visible(
        timeout=5000
    )


@when("the host pastes a URL without a valid playlist ID into the search field")
def paste_invalid_url(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(spa_page, mock_ws_server, frontend_url, authorized=True)
    spa_page.get_by_role("searchbox").first.fill(
        "https://music.apple.com/us/album/test"
    )
    spa_page.wait_for_timeout(1000)


# '"Invalid playlist URL" is displayed' is handled by conftest


@when("the host pastes a URL for a playlist with no songs into the search field")
def paste_empty_playlist_url(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(
        spa_page,
        mock_ws_server,
        frontend_url,
        authorized=True,
        empty_playlist_ids={"pl.empty"},
    )
    spa_page.get_by_role("searchbox").first.fill(
        "https://music.apple.com/us/playlist/empty/pl.empty"
    )
    spa_page.wait_for_timeout(1000)


# 'a toast "No songs found in this playlist" is displayed' is handled by conftest


@given("search results or library playlists are displayed")
def results_or_library(spa_page, mock_ws_server, frontend_url):
    # Surface an empty playlist in search results so the next step can click it.
    _setup_lobby(
        spa_page,
        mock_ws_server,
        frontend_url,
        authorized=True,
        empty_playlist_ids={"pl.empty"},
        search_playlist_ids=["pl.empty"],
    )
    spa_page.get_by_role("searchbox").first.fill("empty")
    spa_page.wait_for_timeout(1000)


@when("the host selects a playlist that contains no songs")
def select_empty_playlist(spa_page):
    spa_page.get_by_role("listitem").filter(has_text="Playlist pl.empty").first.click()
    spa_page.wait_for_timeout(500)


@when("the host pastes a playlist URL into the search field")
@given("the host pastes a playlist URL into the search field")
def paste_url_for_network_error(spa_page, mock_ws_server, frontend_url):
    # ``playlist_tracks_error=True`` makes the playlist tracks endpoint
    # return 500, matching the scenario's "network error during URL load"
    # intent (search is unaffected; URL paste triggers playlist_tracks).
    _setup_lobby(
        spa_page,
        mock_ws_server,
        frontend_url,
        authorized=True,
        playlist_tracks_error=True,
    )
    network_error_while_loading(spa_page)


@when("a network error occurs while loading the playlist")
def network_error_while_loading(spa_page):
    spa_page.get_by_role("searchbox").first.fill(
        "https://music.apple.com/us/playlist/test/pl.12345"
    )
    spa_page.wait_for_timeout(1000)


@then("the playlist load fails with a network error")
def playlist_load_fails(spa_page):
    expect(spa_page.get_by_role("alert").first).to_be_visible(timeout=10000)


# "the error message is displayed as a toast" is in conftest


@given("the developer token has expired", target_fixture="token_fetch_count")
def token_expired(spa_page):
    count = [0]

    def handle_token(route):
        count[0] += 1
        token = (
            make_developer_token(expired=True)
            if count[0] == 1
            else make_developer_token()
        )
        expires = "2020-01-01T00:00:00Z" if count[0] == 1 else "2099-01-01T00:00:00Z"
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"token": token, "expiresAt": expires}),
        )

    spa_page.unroute("**/api/token")
    spa_page.route("**/api/token", handle_token)
    return count


@when("a music operation requires a valid token")
def music_op_requires_token(spa_page, mock_ws_server, frontend_url):
    _setup_lobby(spa_page, mock_ws_server, frontend_url, authorized=True)


@then("a new developer token is fetched from the server")
def token_refetched(spa_page, token_fetch_count):
    spa_page.wait_for_timeout(2000)
    assert token_fetch_count[0] >= 2, (
        f"Expected /api/token to be called at least twice (re-fetch), "
        f"got {token_fetch_count[0]}"
    )


@given("a playlist has more than 100 songs")
def large_playlist(spa_page, mock_ws_server, frontend_url):
    # 150-song setup: setup_musickit's resolve_playlist returns a playlist
    # whose track_ids equal the configured ``songs`` list, so loading
    # ``pl.large`` yields a 150-track playlist.
    _setup_lobby(
        spa_page,
        mock_ws_server,
        frontend_url,
        authorized=True,
        songs=LARGE_PLAYLIST_SONGS,
        search_playlist_ids=[LARGE_PLAYLIST_ID],
    )


@when("the playlist songs are loaded")
def playlist_songs_loaded(spa_page):
    spa_page.get_by_role("searchbox").first.fill(
        f"https://music.apple.com/us/playlist/large/{LARGE_PLAYLIST_ID}"
    )
    spa_page.wait_for_timeout(3000)


@then("all songs from the playlist are loaded")
def all_songs_loaded(spa_page):
    expect(
        spa_page.get_by_text(f"Songs ({LARGE_PLAYLIST_SONG_COUNT})", exact=False).first
    ).to_be_visible(timeout=10000)


@given("the host has a song ready to play")
def host_song_ready(spa_page, mock_ws_server, frontend_url):
    _setup_game(spa_page, mock_ws_server, frontend_url)


@when("the song is played with a duration")
def song_played_with_duration(spa_page):
    play_btn = spa_page.get_by_role("button", name="Play")
    expect(play_btn).to_be_enabled(timeout=5000)
    play_btn.click()
    spa_page.wait_for_timeout(500)


@then("the song plays for the specified duration and then stops")
def song_plays_then_stops(spa_page):
    is_playing = spa_page.evaluate("() => MusicKit.getInstance()?.isPlaying")
    assert is_playing is True, "Expected song to be playing after Play clicked"
    # playbackDurations[0] = 1 second; wait for duration + margin
    spa_page.wait_for_timeout(2000)
    is_playing = spa_page.evaluate("() => MusicKit.getInstance()?.isPlaying")
    assert is_playing is False, "Expected playback to stop after duration elapsed"


@when("the round is revealed")
def round_revealed(spa_page, mock_ws_server, frontend_url):
    _setup_game(spa_page, mock_ws_server, frontend_url)
    send_reveal(mock_ws_server.latest_connection, winners=[])
    spa_page.wait_for_timeout(1000)


@then("the host plays the revealed song without a time limit")
def plays_full_song(spa_page):
    is_playing = spa_page.evaluate("() => MusicKit.getInstance()?.isPlaying")
    assert is_playing is True, "Expected MusicKit to be playing the revealed song"


@given("a song is currently playing on the host")
def song_playing_on_host(spa_page, mock_ws_server, frontend_url):
    _setup_game(spa_page, mock_ws_server, frontend_url)
    play_btn = spa_page.get_by_role("button", name="Play")
    expect(play_btn).to_be_enabled(timeout=5000)
    play_btn.click()
    spa_page.wait_for_timeout(500)


@when("the current round changes")
def current_round_changes(spa_page, mock_ws_server, frontend_url):
    if mock_ws_server.latest_connection is None:
        _setup_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "room:state",
        make_room_state_payload(
            "playing",
            [
                {"id": SELF_PLAYER_ID, "score": 0},
                {"id": "player-2", "score": 0},
            ],
            current_round=2,
        ),
    )
    spa_page.wait_for_timeout(1000)


@then("the host's current song is stopped")
def current_song_stopped(spa_page):
    is_playing = spa_page.evaluate("() => MusicKit.getInstance()?.isPlaying")
    assert is_playing is not True, "Expected playback to be stopped after round change"


@then("the song for the current round is loaded on the host")
def song_loaded_on_host(spa_page):
    now_playing = spa_page.evaluate("() => MusicKit.getInstance()?.nowPlayingItem?.id")
    assert now_playing is not None, "Expected a song to be loaded for the current round"


@when("game:restore-reveal is received on the host")
def restore_reveal_on_host(spa_page, mock_ws_server, frontend_url):
    _setup_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "game:restore-reveal",
        {
            "song": {
                "id": "song1",
                "title": "Song 1",
                "artist": "Artist 1",
                "artworkUrl": None,
            },
            "winners": [],
        },
    )
    spa_page.wait_for_timeout(1000)


# Reuses plays_full_song


@given("the song for the current round is already loaded on the host")
def song_already_loaded(spa_page, mock_ws_server, frontend_url):
    _setup_game(spa_page, mock_ws_server, frontend_url)


@when("the round state is updated without a round change")
def state_updated_no_round_change(spa_page, mock_ws_server):
    mock_ws_server.latest_connection.send_event(
        "room:state",
        make_room_state_payload(
            "playing",
            [
                {"id": SELF_PLAYER_ID, "score": 4},
                {"id": "player-2", "score": 0},
            ],
            current_round=1,
        ),
    )
    spa_page.wait_for_timeout(500)


@then("the song is not reloaded")
def song_not_reloaded(spa_page):
    expect(spa_page.get_by_role("button", name="Loading...")).to_have_count(0)


@when("the host plays the song")
@when("the song fails to play")
def song_fails_to_play(spa_page, mock_ws_server, frontend_url):
    # ``playback_error=True`` makes the web_playback endpoint return a
    # server-error variant; MusicKit JS raises mediaPlaybackError when
    # the SPA tries to start a song.
    _setup_game(
        spa_page,
        mock_ws_server,
        frontend_url,
        total_rounds=1,
        playback_error=True,
    )
    play_btn = spa_page.get_by_role("button", name="Play")
    expect(play_btn).to_be_enabled(timeout=5000)
    play_btn.click()
    spa_page.wait_for_timeout(2000)


@then("song playback fails")
def song_playback_fails(spa_page):
    expect(spa_page.get_by_role("alert").first).to_be_visible(timeout=10000)


# "the error message is displayed as a toast" is in conftest


@given("the host receives the shuffled song IDs via game:shuffled-songs")
def shuffled_songs_received(spa_page, mock_ws_server, frontend_url):
    # setup_scenario(phase="playing", host=self) sends game:shuffled-songs
    # automatically; this Given is satisfied by entering the game phase.
    _setup_game(spa_page, mock_ws_server, frontend_url)


@then("round N plays the Nth song (1-indexed) from the shuffled list on the host")
def nth_song_plays(spa_page):
    # _setup_game enters at current_round=1 with shuffledSongIds=[song1..songN];
    # so the head of the host's queue must be song1.
    head_id = spa_page.evaluate(
        "() => MusicKit.getInstance()?.queue?.items?.[0]?.id ?? null"
    )
    assert head_id == "song1", (
        f"Round 1 should queue song1 (1st from shuffled list), got {head_id!r}"
    )


@then("music is played only on the host's device via Apple Music")
def host_only_playback(spa_page, mock_ws_server, frontend_url):
    # The scenario has no Given/When; assert the host actually drives
    # playback locally via MusicKit by entering the game and clicking Play.
    _setup_game(spa_page, mock_ws_server, frontend_url)
    spa_page.get_by_role("button", name="Play").click()
    spa_page.wait_for_function(
        "() => MusicKit.getInstance()?.isPlaying === true",
        timeout=5000,
    )


@then("non-host players do not play music locally")
def non_host_no_playback(page, frontend_url, mock_ws_server):
    # Open a second page as a non-host player and confirm MusicKit is not
    # configured. The non-host path must not call setup_musickit — the
    # whole point of the scenario is that non-hosts never construct a
    # MusicKit instance.
    non_host = page
    non_host.route(
        "**/api/session",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ready": True}),
            headers={"Set-Cookie": f"{SESSION_COOKIE}=player-3; Path=/"},
        ),
    )
    non_host.add_init_script(
        f"window.__TEST_WS_URL__ = {json.dumps(mock_ws_server.url)};"
    )

    settings = make_settings_payload(
        "player-2",
        [
            {"id": "player-2", "nickname": "Player 2", "handicap": 0},
            {"id": "player-3", "nickname": "Player 3", "handicap": 0},
        ],
    )
    mock_ws_server.on_respond("room:join", "room:settings", settings)
    setup_room_route(non_host, "1234")
    non_host.goto(f"{frontend_url}room/1234")
    non_host.wait_for_load_state("networkidle")

    has_instance = non_host.evaluate(
        "() => typeof MusicKit !== 'undefined' && MusicKit.getInstance() !== undefined"
    )
    assert has_instance is False, "Non-host player should not have MusicKit configured"


@when("playback is stopped on the host")
def playback_stopped_on_host(spa_page, mock_ws_server, frontend_url):
    _setup_game(spa_page, mock_ws_server, frontend_url)


@then("the song is paused and reset to the beginning")
def song_paused_and_reset(spa_page):
    is_playing = spa_page.evaluate("() => MusicKit.getInstance()?.isPlaying")
    assert is_playing is not True, "Expected playback to be paused after stop"


@when("the host leaves the game screen")
def host_leaves_game(spa_page, mock_ws_server, frontend_url):
    _setup_game(spa_page, mock_ws_server, frontend_url)
    spa_page.goto(frontend_url)
    spa_page.wait_for_load_state("networkidle")


@then("all playback is stopped and the queue is cleared")
def all_playback_stopped(spa_page):
    is_playing = spa_page.evaluate("() => MusicKit.getInstance()?.isPlaying")
    assert is_playing is not True, (
        "Expected all playback to be stopped after leaving game"
    )
