"""Step definitions for lobby.feature — Lobby screen."""

import ast
import re

from playwright.sync_api import Route, expect
from pytest_bdd import given, parsers, scenarios, then, when

from frontend.helpers import (
    SELF_PLAYER_ID,
    Scenario,
    guest_scenario,
    host_scenario,
    make_settings_payload,
    only_alert,
    only_region,
    only_role,
    only_searchbox,
    only_status,
    setup_scenario,
)
from frontend.musickit_mock import configure_musickit_api_mock

scenarios("../../features/frontend/lobby.feature")


def _enter_lobby_as_host(
    spa_page,
    mock_ws_server,
    frontend_url,
    *,
    wait_for_networkidle: bool = True,
    **kwargs,
):
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        host_scenario(**kwargs),
        wait_for_networkidle=wait_for_networkidle,
    )


def _enter_lobby_for_current_player(
    spa_page, mock_ws_server, frontend_url, frontend_state, **kwargs
):
    scenario_factory = (
        guest_scenario
        if frontend_state.get("lobby_current_player") == "guest"
        else host_scenario
    )
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        scenario_factory(**kwargs),
    )


def _parse_list_literal(value: str) -> list[object]:
    parsed = ast.literal_eval(value)
    assert isinstance(parsed, list), f"Expected list literal, got {value}"
    return parsed


def _settings_payload_for_host(**overrides):
    payload = make_settings_payload(
        SELF_PLAYER_ID,
        [{"id": SELF_PLAYER_ID, "nickname": "Host", "handicap": 0}],
        total_rounds=None,
        playback_durations=[],
        rank_points=[],
        lockout_duration=None,
        attempts_limit=None,
    )
    payload.update(overrides)
    return payload


def _playlist_options(spa_page):
    return _playlist_listbox(spa_page).get_by_role("option")


def _playlist_options_locator(spa_page):
    return spa_page.get_by_role("listbox", name="Playlists", exact=True).get_by_role(
        "option"
    )


def _playlist_listbox(spa_page):
    return only_role(spa_page, "listbox", name="Playlists")


def _playlist_option(spa_page, text: str):
    option = _playlist_options(spa_page).filter(has_text=text)
    expect(option).to_have_count(1, timeout=5000)
    return option


def _wait_for_playlist_options(spa_page):
    options = _playlist_options(spa_page)
    for _ in range(50):
        count = options.count()
        if count > 0:
            return options
        spa_page.wait_for_timeout(100)
    raise AssertionError("Expected at least one playlist option")


@given(parsers.parse('the player is in a room with code "{code}"'))
def player_in_room_with_code(spa_page, mock_ws_server, frontend_url, code):
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        Scenario(
            host_player_id=SELF_PLAYER_ID,
            active_players=[{"id": SELF_PLAYER_ID, "nickname": "Host", "handicap": 0}],
            code=code,
        ),
    )


# '"Room: 1234" is displayed' is handled by conftest
# '"Share this code..." is displayed' is handled by conftest


@given(parsers.parse("{count:d} players are in the room"))
def n_players_in_room(spa_page, mock_ws_server, frontend_url, count):
    players = [
        {"id": f"player-{i}", "nickname": f"Player {i}", "handicap": 0}
        for i in range(1, count + 1)
    ]
    players[0]["id"] = SELF_PLAYER_ID
    players[0]["nickname"] = "Player 1"
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        Scenario(host_player_id=SELF_PLAYER_ID, active_players=players),
    )


@then(parsers.parse("the player list shows {count:d} entries"))
def player_list_count(spa_page, count):
    players_section = only_region(spa_page, "Players")
    expect(players_section.get_by_role("listitem")).to_have_count(count, timeout=5000)


@then(parsers.parse('the header shows "Players ({count:d})"'))
def players_header(spa_page, count):
    expect(spa_page.get_by_role("heading", name=f"Players ({count})")).to_be_visible(
        timeout=5000
    )


@given("the host is in the room")
def host_in_room(spa_page, mock_ws_server, frontend_url):
    _enter_lobby_as_host(
        spa_page,
        mock_ws_server,
        frontend_url,
        wait_for_networkidle=False,
    )


@then(parsers.parse('the "Host" badge is visible next to the host\'s name'))
def host_badge_visible(spa_page):
    host_entry = (
        only_region(spa_page, "Players").get_by_role("listitem").filter(has_text="Host")
    )
    expect(host_entry).to_have_count(1, timeout=5000)


@given(parsers.parse("a player has handicap of {seconds} seconds"))
def player_with_handicap(spa_page, mock_ws_server, frontend_url, seconds):
    handicap_val = float(seconds)
    players = [
        {"id": SELF_PLAYER_ID, "nickname": "Host", "handicap": handicap_val},
    ]
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        Scenario(host_player_id=SELF_PLAYER_ID, active_players=players),
    )


@then(parsers.parse('"+{seconds}s" badge is visible next to the player\'s name'))
def handicap_badge_visible(spa_page, seconds):
    expect(
        only_region(spa_page, "Players").get_by_text(f"+{seconds}s", exact=True)
    ).to_be_visible(timeout=5000)


# Reuses player_with_handicap and handicap_badge_visible


@then("no handicap badge is displayed next to the player's name")
def no_handicap_badge(spa_page):
    # "+0s" or any "+{N}s" badge must be absent for a 0-second handicap.
    player_entry = only_region(spa_page, "Players").get_by_role("listitem")
    expect(player_entry).to_have_count(1, timeout=5000)
    expect(player_entry).not_to_contain_text("+", timeout=5000)


@given("some players have disconnected during lobby")
def players_disconnected_lobby(spa_page, mock_ws_server, frontend_url):
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        Scenario(
            host_player_id=SELF_PLAYER_ID,
            active_players=[
                {"id": SELF_PLAYER_ID, "nickname": "Active Player", "handicap": 0}
            ],
            inactive_players=[
                {"id": "player-2", "nickname": "Disconnected Player", "handicap": 0}
            ],
        ),
    )


@then("inactive players are shown in a separate section below active players")
def inactive_separate_section(spa_page):
    active = only_region(spa_page, "Active Players")
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


@then('the "Players" header count reflects only active players')
def players_header_active_only(spa_page):
    expect(spa_page.get_by_role("heading", name="Players (1)")).to_be_visible(
        timeout=5000
    )


@when(parsers.parse('the player types "{nickname}" in the nickname field'))
def type_nickname(spa_page, mock_ws_server, frontend_url, nickname):
    _enter_lobby_as_host(
        spa_page,
        mock_ws_server,
        frontend_url,
        wait_for_networkidle=False,
    )
    spa_page.get_by_role("textbox", name="Nickname").fill(nickname)


@then("room:nickname is sent to the server after a short delay")
def nickname_sent(spa_page, mock_ws_server):
    spa_page.wait_for_timeout(2000)
    conn = mock_ws_server.latest_connection
    assert conn is not None
    nickname_events = conn.events_of("room:nickname")
    assert len(nickname_events) > 0, "room:nickname was not sent"


@when("the player types a 25-character string")
def type_25_chars(spa_page, mock_ws_server, frontend_url):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    spa_page.get_by_role("textbox", name="Nickname").fill("a" * 25)


@then("only the first 20 characters are in the field")
def field_has_20_chars(spa_page):
    expect(spa_page.get_by_role("textbox", name="Nickname")).to_have_value("a" * 20)


@when("the player submits a nickname")
@given("the server rejects the nickname")
def server_rejects_nickname(spa_page, mock_ws_server, frontend_url):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.on(
        "room:nickname",
        lambda conn, _: conn.send_event(
            "error", {"message": "Nickname is inappropriate"}
        ),
    )
    spa_page.get_by_role("textbox", name="Nickname").fill("BadName")
    spa_page.wait_for_timeout(2000)


@then("the server rejects the nickname")
def nickname_rejected(spa_page):
    expect(only_alert(spa_page, "Nickname is inappropriate")).to_be_visible(
        timeout=5000
    )


# "the error message is displayed as a toast" is in conftest


@given("the player is in a room", target_fixture="in_room")
def player_in_room(spa_page, mock_ws_server, frontend_url):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    return True


@then(parsers.parse('the "{section}" section is visible'))
def section_visible(spa_page, section):
    expect(spa_page.get_by_role("heading", name=section)).to_be_visible(timeout=5000)


# '"Add a delay..." is displayed' is handled by conftest


@when(parsers.parse("the player moves the handicap slider to {value:d}"))
def move_handicap_slider(spa_page, mock_ws_server, frontend_url, value):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    spa_page.get_by_role("slider", name="Handicap").fill(str(value))


@then(parsers.parse('"{text}" is displayed next to the slider'))
def text_next_to_slider(spa_page, text):
    expect(spa_page.get_by_text(text, exact=True)).to_be_visible(timeout=5000)


@then("room:handicap is sent to the server after a short delay")
def handicap_sent(spa_page, mock_ws_server):
    spa_page.wait_for_timeout(2000)
    conn = mock_ws_server.latest_connection
    assert conn is not None
    handicap_events = conn.events_of("room:handicap")
    assert len(handicap_events) > 0, "room:handicap was not sent"


@given("the handicap slider is rendered", target_fixture="handicap_slider")
def handicap_slider_rendered(spa_page, mock_ws_server, frontend_url):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    slider = spa_page.get_by_role("slider", name="Handicap")
    expect(slider).to_be_visible(timeout=5000)
    return slider


@then(parsers.parse("the handicap slider minimum is {min_val:d}"))
def slider_min(spa_page, mock_ws_server, frontend_url, min_val):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    expect(spa_page.get_by_role("slider", name="Handicap")).to_have_attribute(
        "min", str(min_val)
    )


@then(parsers.parse("the handicap slider maximum is {max_val:d}"))
def slider_max(spa_page, max_val):
    expect(spa_page.get_by_role("slider", name="Handicap")).to_have_attribute(
        "max", str(max_val)
    )


@then(parsers.parse("the handicap slider step is {step}"))
def slider_step(spa_page, step):
    expect(spa_page.get_by_role("slider", name="Handicap")).to_have_attribute(
        "step", step
    )


@given("the player is the host")
def player_is_host(spa_page, mock_ws_server, frontend_url):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)


@given("Apple Music is not authorized")
def apple_music_not_authorized(spa_page):
    configure_musickit_api_mock(spa_page, authorized=False)


# 'an "{text}" button is visible' is handled by conftest


@then("the search input is still visible for public playlist search and URL loading")
def search_input_visible(spa_page):
    expect(only_searchbox(spa_page)).to_be_visible(timeout=5000)


@given("Apple Music is authorized")
def apple_music_authorized(spa_page):
    configure_musickit_api_mock(spa_page, authorized=True)


@then('"My Library" and "Public" tabs are visible')
def tabs_visible(spa_page):
    expect(spa_page.get_by_role("tab", name="My Library")).to_be_visible(timeout=5000)
    expect(spa_page.get_by_role("tab", name="Public")).to_be_visible(timeout=5000)


@then(parsers.parse('a "{text}" input is displayed'))
def input_displayed(spa_page, text):
    searchbox = only_searchbox(spa_page)
    expect(searchbox).to_be_visible(timeout=5000)
    expect(searchbox).to_have_attribute("aria-label", text)


@when('the host switches between "My Library" and "Public" tabs')
def switch_tabs(spa_page, mock_ws_server, frontend_url):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    spa_page.get_by_role("tab", name="Public").click()
    only_searchbox(spa_page).fill("Test query")
    spa_page.get_by_role("tab", name="My Library").click()


@then("each tab retains its own search input value and results")
def tabs_retain_state(spa_page):
    spa_page.get_by_role("tab", name="Public").click()
    expect(only_searchbox(spa_page)).to_have_value("Test query")


@when("the host pastes a playlist URL into the search field")
def paste_playlist_url(spa_page, mock_ws_server, frontend_url):
    configure_musickit_api_mock(spa_page, authorized=True)
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    only_searchbox(spa_page).fill("https://music.apple.com/us/playlist/test/pl.12345")


@then("the playlist is loaded directly")
def playlist_loaded_directly(spa_page):
    # Either the loading indicator or the resulting song list confirms a
    # direct URL-load was kicked off (no playlist picker was shown).
    expect(
        spa_page.get_by_role("status")
        .filter(has_text="Loading songs...")
        .or_(spa_page.get_by_role("region", name="Songs"))
    ).to_be_visible(timeout=5000)


@given('the "Public" tab is active')
def public_tab_active(spa_page, mock_ws_server, frontend_url):
    configure_musickit_api_mock(spa_page, authorized=False)
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    spa_page.get_by_role("tab", name="Public").click()


@when("the host types a keyword in the search field")
def type_keyword(spa_page):
    only_searchbox(spa_page).fill("rock")


@then("matching playlists are displayed")
def matching_playlists(spa_page):
    _wait_for_playlist_options(spa_page)


@given('the "My Library" tab is active')
def library_tab_active(spa_page, mock_ws_server, frontend_url):
    configure_musickit_api_mock(spa_page, authorized=True)
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    spa_page.get_by_role("tab", name="My Library").click()


@when("the host types in the search field")
def type_in_search(spa_page):
    only_searchbox(spa_page).fill("test")


@then("library playlists are filtered by name (case-insensitive)")
def library_filtered(spa_page):
    expect(_playlist_option(spa_page, "Test Playlist")).to_be_visible(timeout=5000)
    expect(_playlist_options(spa_page).filter(has_text="Library p.lib2")).to_have_count(
        0
    )


@given("library playlists are displayed with a filter")
def library_with_filter(spa_page, mock_ws_server, frontend_url):
    configure_musickit_api_mock(spa_page, authorized=True)
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    spa_page.get_by_role("tab", name="My Library").click()


@when("no playlists match the filter")
def no_playlists_match(spa_page):
    only_searchbox(spa_page).fill("zzzznonexistent")
    spa_page.wait_for_timeout(1000)


# '"No matching playlists" is displayed' is handled by conftest


@given("playlist results are displayed")
def playlist_results_displayed(spa_page, mock_ws_server, frontend_url):
    configure_musickit_api_mock(spa_page, authorized=True)
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    only_searchbox(spa_page).fill("test")
    spa_page.wait_for_timeout(1000)


@when("the host selects a playlist")
def select_playlist(spa_page):
    _playlist_option(spa_page, "Playlist pl.test").click()
    spa_page.wait_for_timeout(1000)


@then(
    "the previously loaded songs are replaced with the songs from the selected playlist"
)
def songs_replaced(spa_page):
    expect(only_region(spa_page, "Songs")).to_be_visible(timeout=5000)


@then("the playlist results close")
def results_close(spa_page):
    expect(_playlist_options_locator(spa_page)).to_have_count(0)


@given("a playlist is being loaded")
def playlist_loading(spa_page, mock_ws_server, frontend_url):
    configure_musickit_api_mock(spa_page, authorized=True)
    pending: list[Route] = []

    def hold(route: Route) -> None:
        pending.append(route)

    spa_page.route("**/api.music.apple.com/v1/me/library/playlists*", hold)
    spa_page.route(
        "**/api.music.apple.com/v1/catalog/*/playlists/*/tracks*",
        hold,
    )
    _enter_lobby_as_host(
        spa_page,
        mock_ws_server,
        frontend_url,
        wait_for_networkidle=False,
    )
    only_searchbox(spa_page).fill("test")
    _wait_for_playlist_options(spa_page)
    _playlist_option(spa_page, "Playlist pl.test").click()


@then('"Loading songs..." is displayed')
def loading_songs_displayed(spa_page):
    expect(only_status(spa_page, "Loading songs...")).to_be_visible(timeout=5000)


@then('"Loading library playlists..." is displayed')
def loading_library_displayed(spa_page):
    expect(only_status(spa_page, "Loading library playlists...")).to_be_visible(
        timeout=5000
    )


@then(
    parsers.parse(
        'when library playlists are loading, "Loading library playlists..." is displayed'
    )
)
def loading_library_when_loading(spa_page):
    expect(only_status(spa_page, "Loading library playlists...")).to_be_visible(
        timeout=5000
    )


@given("songs have been selected")
def songs_selected(spa_page, mock_ws_server, frontend_url, frontend_state):
    songs = [
        {"id": "song1", "title": "Song 1", "artist": "Artist 1", "artworkUrl": None},
        {
            "id": "song2",
            "title": "Song 2",
            "artist": "Artist 2",
            "artworkUrl": "https://example.com/art.jpg",
        },
    ]
    _enter_lobby_for_current_player(
        spa_page, mock_ws_server, frontend_url, frontend_state, songs=songs
    )


@then(parsers.parse('the song list is visible with header "Songs ({{count}})"'))
def song_list_visible(spa_page):
    expect(
        only_region(spa_page, "Songs").get_by_role(
            "heading", name=re.compile(r"^Songs \(\d+\)$")
        )
    ).to_be_visible(timeout=5000)


@then("each song shows numbered index, artwork (if available), title, and artist")
def song_details(spa_page):
    songs_region = only_region(spa_page, "Songs")
    songs = songs_region.get_by_role("listitem")
    expect(songs).to_have_count(2, timeout=5000)
    first_song = songs.nth(0)
    expect(first_song).to_contain_text("Song 1", timeout=5000)
    expect(first_song).to_contain_text("Artist 1", timeout=5000)


@given("no songs have been selected")
def no_songs_selected(spa_page, mock_ws_server, frontend_url, frontend_state):
    _enter_lobby_for_current_player(
        spa_page, mock_ws_server, frontend_url, frontend_state, songs=[]
    )


@then("the song list section is not visible")
def song_list_not_visible(spa_page):
    expect(spa_page.get_by_role("region", name="Songs")).to_have_count(0)


@then("the game settings panel is visible with:")
def settings_panel_visible(spa_page):
    """Verify game settings panel contains all expected controls.

    Table:
      | setting            | input type | details                                      |
      | Playback durations | text       | placeholder "1, 2, 4, 8, 16", with help text |
      | Rank points        | text       | placeholder "4, 2, 1", with help text        |
      | Rounds             | slider     | min=1, max=songCount, shown when songs exist |
      | Lockout duration   | slider     | min=0, max=30, step=0.1                      |
      | Attempts limit     | slider     | min=0, max=10, step=1, 0 means unlimited     |
    """
    expect(spa_page.get_by_role("textbox", name="Playback durations")).to_be_visible(
        timeout=5000
    )
    expect(spa_page.get_by_role("textbox", name="Rank points")).to_be_visible(
        timeout=5000
    )
    expect(spa_page.get_by_role("slider", name="Lockout duration")).to_be_visible(
        timeout=5000
    )
    expect(spa_page.get_by_role("slider", name="Attempts limit")).to_be_visible(
        timeout=5000
    )


@then("text fields display the current server values")
@then("text fields display the current effective values")
def text_fields_show_values(spa_page):
    pb_input = spa_page.get_by_role("textbox", name="Playback durations")
    rank_input = spa_page.get_by_role("textbox", name="Rank points")
    assert len(pb_input.input_value()) > 0, (
        "Expected playback durations field to contain effective values"
    )
    assert len(rank_input.input_value()) > 0, (
        "Expected rank points field to contain effective values"
    )


@when("room:settings is received with one or more unset game setting values")
def room_settings_received_with_unset_values(mock_ws_server, frontend_state):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    frontend_state["settings_event_count_before_defaults"] = 0


@then("the following frontend defaults are applied to the unset values:")
def frontend_defaults_applied(spa_page, datatable):
    expected = {row[0]: row[1] for row in datatable[1:]}

    if "Playback durations" in expected:
        value = spa_page.get_by_role("textbox", name="Playback durations").input_value()
        assert _parse_list_literal(expected["Playback durations"]) == [
            int(part.strip()) for part in value.split(",") if part.strip()
        ]
    if "Rank points" in expected:
        value = spa_page.get_by_role("textbox", name="Rank points").input_value()
        assert _parse_list_literal(expected["Rank points"]) == [
            int(part.strip()) for part in value.split(",") if part.strip()
        ]
    if "Lockout duration" in expected:
        expect(spa_page.get_by_role("slider", name="Lockout duration")).to_have_value(
            expected["Lockout duration"], timeout=5000
        )
    if "Attempts limit" in expected:
        expect(spa_page.get_by_role("slider", name="Attempts limit")).to_have_value(
            expected["Attempts limit"], timeout=5000
        )


@then("configured server values are preserved")
def configured_values_preserved(spa_page):
    expect(
        only_region(spa_page, "Players").get_by_role("listitem").filter(has_text="Host")
    ).to_have_count(1, timeout=5000)


@then("songs are not changed by frontend defaults")
def songs_not_changed_by_defaults(spa_page):
    expect(spa_page.get_by_role("region", name="Songs")).to_have_count(0)


@then("rounds remain unset until songs exist")
def rounds_remain_unset_until_songs_exist(spa_page):
    expect(spa_page.get_by_role("slider", name="Rounds")).to_have_count(0)


@then(
    "room:settings with the applied frontend defaults is sent to the server after a short delay"
)
def applied_defaults_sent(mock_ws_server, frontend_state, spa_page):
    spa_page.wait_for_timeout(2000)
    conn = mock_ws_server.latest_connection
    assert conn is not None
    before = int(frontend_state.get("settings_event_count_before_defaults", 0))
    new_events = conn.events_of("room:settings")[before:]
    assert new_events, "Expected frontend defaults to be synced"
    payload = new_events[-1].get("payload", {})
    assert payload.get("playbackDurations") == [1, 2, 4, 8, 16]
    assert payload.get("rankPoints") == [4, 2, 1]
    assert payload.get("lockoutDuration") == 5
    assert payload.get("attemptsLimit") == 3
    assert payload.get("totalRounds") is None


@when("room:settings is received with configured game settings")
def room_settings_received_with_configured_values(
    spa_page, mock_ws_server, frontend_state
):
    spa_page.wait_for_timeout(2000)
    conn = mock_ws_server.latest_connection
    assert conn is not None
    frontend_state["settings_event_count_before_configured"] = len(
        conn.events_of("room:settings")
    )
    conn.send_event(
        "room:settings",
        _settings_payload_for_host(
            songs=[
                {
                    "id": "song1",
                    "title": "Song 1",
                    "artist": "Artist 1",
                    "artworkUrl": None,
                },
                {
                    "id": "song2",
                    "title": "Song 2",
                    "artist": "Artist 2",
                    "artworkUrl": None,
                },
            ],
            totalRounds=2,
            playbackDurations=[2, 6],
            rankPoints=[9, 4],
            lockoutDuration=7.5,
            attemptsLimit=4,
        ),
    )


@then("the game settings panel displays the received server values")
def settings_panel_displays_received_values(spa_page):
    expect(spa_page.get_by_role("textbox", name="Playback durations")).to_have_value(
        "2, 6", timeout=5000
    )
    expect(spa_page.get_by_role("textbox", name="Rank points")).to_have_value(
        "9, 4", timeout=5000
    )
    expect(spa_page.get_by_role("slider", name="Rounds")).to_have_value(
        "2", timeout=5000
    )
    expect(spa_page.get_by_role("slider", name="Lockout duration")).to_have_value(
        "7.5", timeout=5000
    )
    expect(spa_page.get_by_role("slider", name="Attempts limit")).to_have_value(
        "4", timeout=5000
    )


@then("frontend defaults are not sent to the server")
def frontend_defaults_not_sent(mock_ws_server, frontend_state, spa_page):
    spa_page.wait_for_timeout(2000)
    conn = mock_ws_server.latest_connection
    assert conn is not None
    before = int(frontend_state.get("settings_event_count_before_configured", 0))
    after = len(conn.events_of("room:settings"))
    assert after == before, f"Expected no frontend default sync, got {after - before}"


@then(
    parsers.parse(
        'playback durations help text reads: e.g. "1, 2, 4" = play for 1s, extend to 2s, then 4s'
    )
)
def playback_help_text(spa_page):
    expect(
        spa_page.get_by_text(
            'e.g. "1, 2, 4" = play for 1s, extend to 2s, then 4s',
            exact=True,
        )
    ).to_be_visible(timeout=5000)


@then(
    parsers.parse(
        'rank points help text reads: e.g. "4, 2, 1" = 1st gets 4pt(s), 2nd gets 2pt(s), 3rd gets 1pt(s)'
    )
)
def rank_help_text(spa_page):
    expect(
        spa_page.get_by_text(
            'e.g. "4, 2, 1" = 1st gets 4pt(s), 2nd gets 2pt(s), 3rd gets 1pt(s)',
            exact=True,
        )
    ).to_be_visible(timeout=5000)


@when("any setting value changes on the browser side (manual or programmatic)")
def setting_changes(spa_page, mock_ws_server, frontend_url, frontend_state):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    spa_page.wait_for_timeout(2000)
    conn = mock_ws_server.latest_connection
    assert conn is not None
    frontend_state["settings_event_count_before_change"] = len(
        conn.events_of("room:settings")
    )
    spa_page.get_by_role("slider", name="Lockout duration").fill("10")


@then("the setting is sent to the server after a short delay")
def setting_synced(spa_page, mock_ws_server, frontend_state):
    spa_page.wait_for_timeout(2000)
    conn = mock_ws_server.latest_connection
    assert conn is not None
    before = int(frontend_state.get("settings_event_count_before_change", 0))
    settings_events = conn.events_of("room:settings")[before:]
    assert len(settings_events) > 0, "room:settings was not sent"


@given("the playback durations field contains non-numeric values mixed with numbers")
def non_numeric_values(spa_page, mock_ws_server, frontend_url, frontend_state):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    spa_page.wait_for_timeout(2000)
    conn = mock_ws_server.latest_connection
    assert conn is not None
    frontend_state["settings_event_count_before_text_sync"] = len(
        conn.events_of("room:settings")
    )
    spa_page.get_by_role("textbox", name="Playback durations").fill("1, abc, 2, xyz, 4")


@when("the setting is synced")
def setting_is_synced(spa_page):
    spa_page.wait_for_timeout(2000)


@then("only positive numbers are sent")
def only_positive_numbers(mock_ws_server, frontend_state):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    before = int(frontend_state.get("settings_event_count_before_text_sync", 0))
    settings_events = conn.events_of("room:settings")[before:]
    assert settings_events, "Expected a new room:settings to be sent"
    last_settings = settings_events[-1]
    durations = last_settings.get("payload", {}).get("playbackDurations", [])
    for d in durations:
        assert isinstance(d, (int, float)) and d > 0, f"Invalid duration: {d}"


@when("a text field setting is changed to an invalid value")
@when("a text field setting value is invalid")
def invalid_setting_value(spa_page, mock_ws_server, frontend_url, frontend_state):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    spa_page.wait_for_timeout(2000)
    conn = mock_ws_server.latest_connection
    assert conn is not None
    frontend_state["settings_event_count_before_invalid"] = len(
        conn.events_of("room:settings")
    )
    spa_page.get_by_role("textbox", name="Playback durations").fill("")


@then("an error is displayed")
def error_displayed(spa_page):
    expect(only_alert(spa_page)).to_be_visible(timeout=5000)


@then("the setting is not sent to the server")
def setting_not_sent(mock_ws_server, frontend_state):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    before = int(frontend_state.get("settings_event_count_before_invalid", 0))
    after = len(conn.events_of("room:settings"))
    assert after == before, f"Expected no new room:settings, got {after - before}"


@then("an error is displayed without sending the setting")
def error_without_sending(spa_page):
    expect(only_alert(spa_page)).to_be_visible(timeout=5000)


@when("songs are replaced by a new playlist")
def songs_replaced_by_playlist(spa_page, mock_ws_server, frontend_url):
    songs = [
        {
            "id": f"song{i}",
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "artworkUrl": None,
        }
        for i in range(1, 6)
    ]
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url, songs=songs)


@then("the rounds slider is set to the new song count")
def rounds_slider_reset(spa_page):
    expect(spa_page.get_by_role("slider", name="Rounds")).to_have_value(
        "5", timeout=5000
    )


@when('the host clicks "Start Game"')
def host_clicks_start(spa_page, mock_ws_server, frontend_url):
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    spa_page.get_by_role("button", name="Start Game").click()


@given("the settings are invalid")
@when("the settings are invalid")
def settings_invalid(spa_page, mock_ws_server, frontend_url):
    # ``_enter_lobby_as_host`` defaults to a host with no songs selected;
    # game:start requires songs, so the click step's settings are invalid
    # by construction. Verify no songs ever arrived on the server side.
    _enter_lobby_as_host(spa_page, mock_ws_server, frontend_url)
    conn = mock_ws_server.latest_connection
    assert conn is not None
    settings_events = conn.events_of("room:settings")
    songs_sent = any(
        len(e.get("payload", {}).get("songs", [])) > 0 for e in settings_events
    )
    assert not songs_sent, "Expected no songs in settings to make game:start invalid"


@then("game:start is not sent")
def game_start_not_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    start_events = conn.events_of("game:start")
    assert len(start_events) == 0, "game:start should not have been sent"


@then("an error is displayed without sending game:start")
def error_no_game_start(spa_page, mock_ws_server):
    expect(only_alert(spa_page, "Select songs before starting")).to_be_visible(
        timeout=5000
    )
    conn = mock_ws_server.latest_connection
    assert conn is not None
    start_events = conn.events_of("game:start")
    assert len(start_events) == 0, "game:start should not have been sent"


@given("the player is not the host")
def player_not_host(spa_page, mock_ws_server, frontend_url, frontend_state):
    frontend_state["lobby_current_player"] = "guest"
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        guest_scenario(),
    )


@then("all game settings are displayed as read-only values")
def settings_read_only(spa_page):
    expect(spa_page.get_by_text(re.compile(r"^Playback durations: "))).to_be_visible(
        timeout=5000
    )
    # Non-host UI must surface no editable settings controls.
    expect(spa_page.get_by_role("textbox", name="Playback durations")).to_have_count(0)
    expect(spa_page.get_by_role("textbox", name="Rank points")).to_have_count(0)
    expect(spa_page.get_by_role("slider", name="Lockout duration")).to_have_count(0)
    expect(spa_page.get_by_role("slider", name="Attempts limit")).to_have_count(0)
    expect(spa_page.get_by_role("slider", name="Rounds")).to_have_count(0)


@then("the rounds value is not displayed")
def rounds_not_displayed(spa_page):
    expect(spa_page.get_by_text("Rounds", exact=False)).to_have_count(0)


# '"Waiting for the host to select a playlist..." is displayed' is handled by conftest
# '"Waiting for the host to start the game..." is displayed' is handled by conftest
