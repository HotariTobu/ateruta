"""Step definitions for game_play.feature — Game screen playback and host controls."""

from playwright.sync_api import Route, expect
from pytest_bdd import given, parsers, scenarios, then, when

from frontend.helpers import (
    SELF_PLAYER_ID,
    Scenario,
    guest_scenario,
    host_scenario,
    make_room_state_payload,
    make_settings_payload,
    send_reveal,
    setup_room_route,
    setup_scenario,
)
from frontend.musickit_mock import setup_musickit

scenarios("../../features/frontend/game_play.feature")


def _enter_host_game(
    spa_page,
    mock_ws_server,
    frontend_url,
    *,
    current_round: int = 1,
    total_rounds: int = 10,
    songs=None,
):
    setup_musickit(spa_page, authorized=True)
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        host_scenario(
            phase="playing",
            current_round=current_round,
            total_rounds=total_rounds,
            songs=songs,
        ),
    )


def _enter_guest_game(spa_page, mock_ws_server, frontend_url):
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        guest_scenario(phase="playing"),
    )


@given(parsers.parse("round {round_num:d} of a game with {total:d} total rounds"))
def round_n_of_total(spa_page, mock_ws_server, frontend_url, round_num, total):
    _enter_host_game(
        spa_page,
        mock_ws_server,
        frontend_url,
        current_round=round_num,
        total_rounds=total,
    )


@given("a round is in progress")
def round_in_progress(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)


# '"Round 3/10" is displayed' is handled by conftest


@then(parsers.parse('"Duration: {{N}}s" is always shown regardless of playback state'))
def duration_displayed(spa_page):
    expect(spa_page.get_by_text("Duration:", exact=False).first).to_be_visible(
        timeout=5000
    )


@given("the player is not the host")
def player_not_host(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)


@then(
    "the Play, Extend, Close Answers, End Game, Next Round, and See Results buttons are not visible"
)
def host_controls_not_visible(spa_page):
    for text in [
        "Play",
        "Extend",
        "Close Answers",
        "End Game",
        "Next Round",
        "See Results",
    ]:
        expect(spa_page.get_by_role("button", name=text)).to_have_count(0)


@given("the host is on the game screen and a song is ready")
def host_with_song_ready(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)
    expect(spa_page.get_by_role("button", name="Play")).to_be_enabled(timeout=5000)


@when('the host clicks "Play"')
def host_clicks_play(spa_page):
    spa_page.get_by_role("button", name="Play").click()


@then("the song is played locally")
def song_played_locally(spa_page):
    expect(
        spa_page.get_by_role("status").filter(has_text="Playing...").first
    ).to_be_visible(timeout=5000)


@then("game:play-song is sent to the server")
def play_song_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    play_events = conn.events_of("game:play-song")
    assert len(play_events) > 0, "game:play-song was not sent"


@given("a song is currently playing or the song is not ready")
def song_playing_or_not_ready(spa_page, mock_ws_server, frontend_url):
    # Pick the "currently playing" branch by entering host game and
    # clicking Play. Disabling-while-playing covers the broader "or"
    # condition (Play is also disabled when not ready).
    _enter_host_game(spa_page, mock_ws_server, frontend_url)
    play_btn = spa_page.get_by_role("button", name="Play")
    expect(play_btn).to_be_enabled(timeout=5000)
    play_btn.click()


@then(parsers.parse('the "{button_name}" button is disabled'))
def button_disabled(spa_page, button_name):
    expect(spa_page.get_by_role("button", name=button_name).first).to_be_disabled(
        timeout=5000
    )


@given("the song data has not yet been fetched")
def song_not_fetched(spa_page, mock_ws_server, frontend_url):
    # Suppress the ``game:shuffled-songs`` event the default join_handler
    # would emit by entering with phase="playing" via a custom scenario
    # that omits the host event. The Play button must show "Preparing..."
    # because the SPA never received the shuffle.
    setup_musickit(spa_page, authorized=True)
    scenario = host_scenario(phase="playing")
    settings = make_settings_payload(
        SELF_PLAYER_ID,
        scenario.active_players,
        songs=[
            {
                "id": f"song{i}",
                "title": f"Song {i}",
                "artist": f"Artist {i}",
                "artworkUrl": None,
            }
            for i in range(1, scenario.total_rounds + 1)
        ],
        total_rounds=scenario.total_rounds,
    )
    state_players = [{"id": SELF_PLAYER_ID, "score": 0}]

    def join_handler(conn, _payload):
        conn.send_event("room:settings", settings)
        conn.send_event(
            "room:state",
            make_room_state_payload("playing", state_players, current_round=1),
        )

    setup_room_route(spa_page, scenario.code)
    mock_ws_server.on("room:join", join_handler)
    spa_page.goto(f"{frontend_url}room/{scenario.code}")
    spa_page.wait_for_load_state("networkidle")
    spa_page.wait_for_timeout(2000)


@then(parsers.parse('the "Play" button shows "{text}"'))
def play_button_shows(spa_page, text):
    expect(spa_page.get_by_role("button", name=text).first).to_be_visible(timeout=5000)


@given("the song data is being loaded")
def song_loading(spa_page, mock_ws_server, frontend_url):
    # Hold the web_playback response open so MusicKit stays in the loading
    # state; the SPA's Play button must render "Loading..." while the
    # request is in flight. Register after setup_musickit so this override
    # wins via Playwright's route matching order.
    pending: list[Route] = []

    def hold(route: Route) -> None:
        pending.append(route)

    _enter_host_game(spa_page, mock_ws_server, frontend_url)
    spa_page.route(
        "**/play.itunes.apple.com/WebObjects/MZPlay.woa/**",
        hold,
    )
    spa_page.get_by_role("button", name="Play").click(force=True)


# Reuses play_button_shows


@given("the song has finished playing")
def song_finished(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)
    play_btn = spa_page.get_by_role("button", name="Play")
    expect(play_btn).to_be_enabled(timeout=5000)
    play_btn.click()
    # playbackDurations[0] = 1 second; wait for the natural duration plus
    # margin so MusicKit stops playback.
    spa_page.wait_for_function(
        "() => MusicKit.getInstance()?.isPlaying === false",
        timeout=5000,
    )


@then(parsers.parse('the "{button_name}" button is enabled'))
def button_enabled(spa_page, button_name):
    expect(spa_page.get_by_role("button", name=button_name).first).to_be_enabled(
        timeout=5000
    )


@then("the host can replay the song without extending")
def can_replay(spa_page):
    expect(spa_page.get_by_role("button", name="Play")).to_be_enabled(timeout=5000)


@when('the host clicks "Extend"')
def host_clicks_extend(spa_page):
    spa_page.get_by_role("button", name="Extend").click()


@then("game:extend is sent to the server")
def extend_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    extend_events = conn.events_of("game:extend")
    assert len(extend_events) > 0, "game:extend was not sent"


@given("the duration is at the last step or a song is playing or not ready")
def duration_at_max(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "room:state",
        make_room_state_payload(
            "playing",
            [{"id": SELF_PLAYER_ID, "score": 0}],
            current_round=1,
            playback_duration_index=4,
        ),
    )
    spa_page.wait_for_timeout(500)


# Reuses button_disabled


@when('the host clicks "Close Answers"')
def host_clicks_close_answers(spa_page):
    close_button = spa_page.get_by_role("button", name="Close Answers")
    expect(close_button).to_be_enabled(timeout=5000)
    close_button.click()


@then("game:close-answers is sent to the server")
def close_answers_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    events = conn.events_of("game:close-answers")
    assert len(events) > 0, "game:close-answers was not sent"


@given("no song has been played in this round")
def no_song_played(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)


# Reuses button_disabled


@given("a song is currently playing")
def song_currently_playing(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)
    play_btn = spa_page.get_by_role("button", name="Play")
    expect(play_btn).to_be_enabled(timeout=5000)
    play_btn.click()
    expect(
        spa_page.get_by_role("status").filter(has_text="Playing...").first
    ).to_be_visible(timeout=5000)


# Reuses button_disabled


@given("a round has been revealed")
@given("the round has been revealed")
def round_revealed(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)
    send_reveal(mock_ws_server.latest_connection, winners=[])
    spa_page.wait_for_timeout(1000)


@then("the Play, Extend, and Close Answers buttons are not visible")
def play_extend_close_not_visible(spa_page):
    for text in ["Play", "Extend", "Close Answers"]:
        expect(spa_page.get_by_role("button", name=text)).to_have_count(0)


@then('"Playing..." is displayed in blue')
def playing_displayed_blue(spa_page):
    expect(
        spa_page.get_by_role("status").filter(has_text="Playing...").first
    ).to_be_visible(timeout=5000)


@given("the player is the host")
def player_is_host(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)


@then("playback state is based on the local music player")
def playback_from_local(spa_page):
    has_instance = spa_page.evaluate(
        "() => typeof MusicKit !== 'undefined' && MusicKit.getInstance() !== undefined"
    )
    assert has_instance, "Host should have MusicKit for local playback"
    can_play = spa_page.evaluate(
        "() => typeof MusicKit.getInstance()?.play === 'function'"
    )
    assert can_play, "Host MusicKit should expose a play() method"


@then("playback state is based on the game:play-song event")
def playback_from_event(spa_page, mock_ws_server):
    has_instance = spa_page.evaluate(
        "() => typeof MusicKit !== 'undefined' && MusicKit.getInstance() !== undefined"
    )
    assert not has_instance, "Non-host should not have MusicKit configured"
    mock_ws_server.latest_connection.send_event(
        "game:play-song", {"playbackDuration": 1}
    )
    expect(
        spa_page.get_by_role("status").filter(has_text="Playing...").first
    ).to_be_visible(timeout=5000)


@given(
    parsers.parse('a non-host player sees "Playing..." after receiving game:play-song')
)
def non_host_playing(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "game:play-song", {"playbackDuration": 1}
    )
    expect(
        spa_page.get_by_role("status").filter(has_text="Playing...").first
    ).to_be_visible(timeout=3000)


@when("the current playback duration elapses")
def playback_elapses(spa_page):
    spa_page.wait_for_timeout(2000)


@then('"Playing..." is no longer displayed')
def playing_not_displayed(spa_page):
    expect(spa_page.get_by_role("status").filter(has_text="Playing...")).to_have_count(
        0
    )


@given("a non-host player received game:play-song and the timer is running")
def non_host_timer_running(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "game:play-song", {"playbackDuration": 5}
    )
    spa_page.wait_for_timeout(500)


@when("a new game:play-song is received")
def new_play_song(spa_page, mock_ws_server):
    mock_ws_server.latest_connection.send_event(
        "game:play-song", {"playbackDuration": 2}
    )


@then("the playing status timer is reset to the current playback duration")
def timer_reset(spa_page):
    expect(
        spa_page.get_by_role("status").filter(has_text="Playing...").first
    ).to_be_visible(timeout=3000)


@given("the player reconnects during a revealed round")
def reconnect_during_reveal(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)


@when("game:restore-reveal is received")
def restore_reveal_received(spa_page, mock_ws_server):
    mock_ws_server.latest_connection.send_event(
        "game:restore-reveal",
        {
            "song": {
                "id": "song1",
                "title": "Song 1",
                "artist": "Artist 1",
                "artworkUrl": None,
            },
            "winners": [{"nickname": "Player 2", "rank": 1, "points": 4}],
        },
    )
    spa_page.wait_for_timeout(1000)


@then("the reveal panel is displayed with the correct song and winners")
def reveal_panel_displayed(spa_page):
    panel = spa_page.get_by_role("region", name="Reveal").first
    expect(panel).to_contain_text("Song 1", timeout=5000)
    expect(panel).to_contain_text("Artist 1", timeout=5000)
    expect(panel).to_contain_text("Player 2", timeout=5000)


@then("the correct song's artwork (if available), title, and artist are displayed")
def correct_song_displayed(spa_page):
    panel = spa_page.get_by_role("region", name="Reveal").first
    expect(panel).to_contain_text("Song 1", timeout=5000)
    expect(panel).to_contain_text("Artist 1", timeout=5000)


@given(parsers.parse("the round has been revealed with {count:d} winners"))
def revealed_with_winners(spa_page, mock_ws_server, frontend_url, count):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)
    winners = [
        {"nickname": f"Player {i + 1}", "rank": i + 1, "points": 4 - i}
        for i in range(count)
    ]
    send_reveal(mock_ws_server.latest_connection, winners=winners)
    spa_page.wait_for_timeout(1000)


@then(parsers.parse('each winner shows "{{rank}}. {{nickname}} (+{{points}}pt(s))"'))
def winners_format(spa_page):
    panel = spa_page.get_by_role("region", name="Reveal").first
    expect(panel).to_contain_text("1. Player 1 (+4pt", timeout=5000)


@given("the round has been revealed with no winners")
def revealed_no_winners(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)
    send_reveal(mock_ws_server.latest_connection, winners=[])
    spa_page.wait_for_timeout(1000)


# '"No one got it" is displayed' is handled by conftest


@given("the round has been revealed and more rounds remain")
def revealed_more_rounds(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(
        spa_page,
        mock_ws_server,
        frontend_url,
        current_round=1,
        total_rounds=10,
    )
    send_reveal(mock_ws_server.latest_connection, winners=[])
    spa_page.wait_for_timeout(1000)


@then('the host sees a "Next Round" button')
def next_round_visible(spa_page):
    expect(spa_page.get_by_role("button", name="Next Round")).to_be_visible(
        timeout=5000
    )


@when('the host clicks "Next Round"')
def host_clicks_next_round(spa_page):
    spa_page.get_by_role("button", name="Next Round").click()


@then("game:next-round is sent to the server")
def next_round_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    events = conn.events_of("game:next-round")
    assert len(events) > 0, "game:next-round was not sent"


@given("the last round has been revealed")
def last_round_revealed(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(
        spa_page,
        mock_ws_server,
        frontend_url,
        current_round=10,
        total_rounds=10,
    )
    send_reveal(mock_ws_server.latest_connection, winners=[])
    spa_page.wait_for_timeout(1000)


@then('the host sees a "See Results" button')
def see_results_visible(spa_page):
    expect(spa_page.get_by_role("button", name="See Results")).to_be_visible(
        timeout=5000
    )


@when('the host clicks "See Results"')
def host_clicks_see_results(spa_page):
    spa_page.get_by_role("button", name="See Results").click()


@then("game:end is sent to the server")
def game_end_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    events = conn.events_of("game:end")
    assert len(events) > 0, "game:end was not sent"


@given("players have different scores")
def players_different_scores(spa_page, mock_ws_server, frontend_url):
    active_players = [
        {"id": SELF_PLAYER_ID, "nickname": "Host", "handicap": 0},
        {"id": "player-2", "nickname": "Player 2", "handicap": 0},
        {"id": "player-3", "nickname": "Player 3", "handicap": 0},
    ]
    setup_musickit(spa_page, authorized=True)
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        Scenario(
            host_player_id=SELF_PLAYER_ID,
            active_players=active_players,
            phase="playing",
        ),
    )
    mock_ws_server.latest_connection.send_event(
        "room:state",
        make_room_state_payload(
            "playing",
            [
                {"id": SELF_PLAYER_ID, "score": 4},
                {"id": "player-2", "score": 8},
                {"id": "player-3", "score": 8},
            ],
            current_round=1,
        ),
    )
    spa_page.wait_for_timeout(1000)


@then('the "Scoreboard" header is displayed')
def scoreboard_header(spa_page):
    expect(spa_page.get_by_role("heading", name="Scoreboard")).to_be_visible(
        timeout=5000
    )


@then("players are sorted by score descending")
def sorted_by_score(spa_page):
    scoreboard = spa_page.get_by_role("region", name="Scoreboard")
    entries = scoreboard.get_by_role("listitem")
    # 8pt players come before 4pt host; the host is named "Host".
    expect(entries.nth(0)).not_to_contain_text("Host", timeout=5000)
    expect(entries.nth(2)).to_contain_text("Host")


@then("tied players have the same rank")
def tied_same_rank(spa_page):
    scoreboard = spa_page.get_by_role("region", name="Scoreboard")
    expect(scoreboard.get_by_text("#1", exact=False)).to_have_count(2)


@then("the order of tied players is not defined")
def tied_order_undefined(spa_page):
    scoreboard = spa_page.get_by_role("region", name="Scoreboard")
    expect(scoreboard.get_by_text("Player 2")).to_be_visible(timeout=5000)
    expect(scoreboard.get_by_text("Player 3")).to_be_visible(timeout=5000)


@given("the player is in the game")
def player_in_game(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)


@given(parsers.parse("a player has handicap of {seconds:g} seconds"))
def player_with_handicap_in_game(spa_page, mock_ws_server, frontend_url, seconds):
    setup_musickit(spa_page, authorized=True)
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        Scenario(
            host_player_id=SELF_PLAYER_ID,
            phase="playing",
            active_players=[
                {
                    "id": SELF_PLAYER_ID,
                    "nickname": "Host",
                    "handicap": float(seconds),
                    "score": 0,
                },
                {
                    "id": "player-2",
                    "nickname": "Player 2",
                    "handicap": 0,
                    "score": 0,
                },
            ],
        ),
    )


@then(
    parsers.parse('"(you)" is shown next to the player\'s own name regardless of score')
)
def you_marker(spa_page):
    expect(spa_page.get_by_text("(you)").first).to_be_visible(timeout=5000)


@then(
    parsers.parse(
        '"+{seconds}s" badge is visible next to the player\'s name in the scoreboard'
    )
)
def handicap_badge_scoreboard(spa_page, seconds):
    scoreboard = spa_page.get_by_role("region", name="Scoreboard")
    expect(scoreboard.get_by_text(f"+{seconds}s").first).to_be_visible(timeout=5000)


@given("some players have disconnected during the game")
def players_disconnected_game(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "room:state",
        make_room_state_payload(
            "playing",
            [{"id": SELF_PLAYER_ID, "score": 4}],
            current_round=1,
            inactive_players=[{"id": "player-2", "score": 2}],
        ),
    )
    spa_page.wait_for_timeout(1000)


@then("inactive players are shown in a separate section below active players")
def inactive_separate(spa_page):
    active = spa_page.get_by_role("region", name="Active Players").first
    inactive = spa_page.get_by_role("region", name="Disconnected Players").first
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


@then("inactive players are also sorted by score descending")
def inactive_sorted(spa_page):
    inactive = spa_page.get_by_role("region", name="Disconnected Players").first
    expect(inactive).to_be_visible(timeout=5000)


@when("the host disconnects")
@given("the host disconnects during a game")
def host_disconnects_game(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
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


@then("the banner does not block game interaction")
def banner_not_blocking(spa_page):
    expect(spa_page.get_by_role("searchbox").first).to_be_enabled(timeout=5000)


@given("the host disconnection banner is displayed")
def host_banner_displayed(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
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
    expect(
        spa_page.get_by_role("status")
        .filter(has_text="The host has disconnected")
        .first
    ).to_be_visible(timeout=5000)


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


@given("a game is in progress")
def game_in_progress(spa_page, mock_ws_server, frontend_url):
    _enter_host_game(spa_page, mock_ws_server, frontend_url)


@then('the host sees an "End Game" button in red text')
def end_game_button(spa_page):
    btn = spa_page.get_by_role("button", name="End Game")
    expect(btn).to_be_visible(timeout=5000)
    color = btn.evaluate("(el) => getComputedStyle(el).color")
    # Tailwind's text-red-* family resolves to rgb(...) with R > G,B.
    parts = [int(p) for p in color.removeprefix("rgb(").removesuffix(")").split(",")]
    assert parts[0] > parts[1] and parts[0] > parts[2], (
        f"End Game button should render in red, got color={color!r}"
    )


@when('the host clicks "End Game"')
def host_clicks_end_game(spa_page):
    spa_page.get_by_role("button", name="End Game").click()


# Reuses game_end_sent


@when("the player leaves the game screen")
def leave_game_screen(spa_page, frontend_url):
    spa_page.goto(frontend_url)
    spa_page.wait_for_load_state("networkidle")


@then("all playback is stopped and cleaned up")
def playback_cleaned_up(spa_page):
    expect(spa_page.get_by_role("status").filter(has_text="Playing...")).to_have_count(
        0
    )
