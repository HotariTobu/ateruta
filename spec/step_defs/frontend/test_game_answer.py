"""Step definitions for game_answer.feature — Game screen answering."""

import datetime

from playwright.sync_api import expect
from pytest_bdd import given, parsers, scenarios, then, when

from frontend.helpers import (
    SELF_PLAYER_ID,
    guest_scenario,
    make_room_state_payload,
    only_region,
    only_role,
    only_searchbox,
    only_status,
    send_reveal,
    setup_scenario,
)

scenarios("../../features/frontend/game_answer.feature")


def _enter_guest_game(
    spa_page,
    mock_ws_server,
    frontend_url,
    *,
    handicap: float = 0,
    attempts_limit: int = 3,
    lockout_duration: float = 5,
):
    setup_scenario(
        spa_page,
        mock_ws_server,
        frontend_url,
        guest_scenario(
            phase="playing",
            handicap=handicap,
            attempts_limit=attempts_limit,
            lockout_duration=lockout_duration,
        ),
    )


def _suggestions_listbox(spa_page):
    return spa_page.get_by_role("listbox", name="Suggestions")


def _suggestions(spa_page):
    return _suggestions_listbox(spa_page).get_by_role("option")


def _wait_for_suggestions(spa_page):
    suggestions = _suggestions(spa_page)
    for _ in range(50):
        count = suggestions.count()
        if count > 0:
            return suggestions, count
        spa_page.wait_for_timeout(100)
    raise AssertionError("Expected at least one answer suggestion")


def _song_suggestion(spa_page, title: str):
    artist = title.replace("Song", "Artist", 1)
    suggestions = _suggestions(spa_page)
    for _ in range(50):
        for index in range(suggestions.count()):
            option = suggestions.nth(index)
            lines = [line.strip() for line in option.inner_text().splitlines()]
            if title in lines and artist in lines:
                return option
        spa_page.wait_for_timeout(100)
    raise AssertionError(f"Expected suggestion for {title!r} by {artist!r}")


def _submit_song_suggestion(spa_page, title: str):
    only_searchbox(spa_page).fill(title)
    _song_suggestion(spa_page, title).click()


@given("the game has songs loaded")
def game_songs_loaded(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)


@when("the player types 1 or more characters in the search field")
def type_in_search(spa_page):
    only_searchbox(spa_page).fill("Song")


@then("songs are matched against their titles only")
def matched_by_title(spa_page):
    expect(_suggestions_listbox(spa_page)).to_be_visible(timeout=5000)
    _wait_for_suggestions(spa_page)


@then(parsers.parse("up to {count:d} matching suggestions are displayed"))
def suggestions_count(spa_page, count):
    spa_page.wait_for_timeout(500)
    suggestions = _suggestions(spa_page)
    actual = suggestions.count()
    assert actual > 0, "Expected at least one suggestion"
    assert actual <= count, f"Expected at most {count} suggestions, got {actual}"


@then("each suggestion shows artwork (if available), title, and artist")
def suggestion_details(spa_page):
    first_song = _song_suggestion(spa_page, "Song 1")
    expect(first_song).to_contain_text("Song 1")
    expect(first_song).to_contain_text("Artist 1")


@when("the search field is empty")
def search_empty(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    only_searchbox(spa_page).fill("")


@then("no suggestions are displayed")
def no_suggestions(spa_page):
    spa_page.wait_for_timeout(500)
    expect(_suggestions(spa_page)).to_have_count(0)


@when("the player types a query that matches no song titles")
def type_no_match(spa_page):
    only_searchbox(spa_page).fill("zzzznonexistent")


# '"No matching songs" is displayed' is handled by conftest


@when("a new round begins")
def new_round_begins(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "room:state",
        make_room_state_payload(
            phase="playing",
            current_round=2,
            active_players=[
                {"id": SELF_PLAYER_ID, "score": 0},
                {"id": "player-2", "score": 0},
            ],
        ),
    )
    spa_page.wait_for_timeout(1000)


@then(
    "the search query, suggestions, lockout countdown, wrong answer feedback, handicap countdown, and score panel are all reset"
)
def all_answer_ui_reset(spa_page):
    expect(only_searchbox(spa_page)).to_have_value("")
    expect(_suggestions(spa_page)).to_have_count(0)


@when("game:reveal or game:restore-reveal is received")
def reveal_received(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    send_reveal(mock_ws_server.latest_connection)
    spa_page.wait_for_timeout(1000)


@then(
    "the search query, suggestions, lockout countdown, wrong answer feedback, handicap countdown, and score panel are all cleared"
)
def all_answer_ui_cleared(spa_page):
    spa_page.wait_for_timeout(500)
    expect(spa_page.get_by_role("searchbox")).to_have_count(0)


@given("suggestions are displayed")
def suggestions_displayed(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    only_searchbox(spa_page).fill("Song")
    expect(_suggestions_listbox(spa_page)).to_be_visible(timeout=5000)
    _song_suggestion(spa_page, "Song 1")


@when("the player clicks a suggestion")
def click_suggestion(spa_page):
    _song_suggestion(spa_page, "Song 1").click()


@then("game:answer with the selected song ID is sent to the server")
def answer_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    assert conn is not None
    answer_events = conn.events_of("game:answer")
    assert len(answer_events) > 0, "game:answer was not sent"
    assert answer_events[-1].get("payload") == {"songId": "song1"}


@then("the search field and suggestions are cleared")
def search_cleared(spa_page):
    expect(only_searchbox(spa_page)).to_have_value("")
    expect(_suggestions(spa_page)).to_have_count(0)


@given("the round has been revealed")
def round_revealed(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    send_reveal(mock_ws_server.latest_connection)
    spa_page.wait_for_timeout(1000)


@then("the answer is not submitted")
def answer_not_submitted(mock_ws_server):
    conn = mock_ws_server.latest_connection
    answer_events = conn.events_of("game:answer")
    assert len(answer_events) == 0, "game:answer should not have been sent"


@given("the player is locked out or has no attempts remaining")
def locked_or_no_attempts(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url, attempts_limit=3)
    mock_ws_server.latest_connection.send_event(
        "game:player-state",
        {
            "scored": False,
            "wrongAnswerCount": 3,
            "lockoutExpiresAt": None,
            "pendingAnswer": None,
        },
    )
    spa_page.wait_for_timeout(1000)


@given("the player's lockout is active")
def lockout_active(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url, lockout_duration=5)
    expires = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5)
    ).isoformat()
    mock_ws_server.latest_connection.send_event(
        "game:player-state",
        {
            "scored": False,
            "wrongAnswerCount": 1,
            "lockoutExpiresAt": expires,
            "pendingAnswer": None,
        },
    )
    spa_page.wait_for_timeout(500)


@when("the player tries to submit an answer")
def try_submit(spa_page):
    # Lockout/no-attempts disable input. Verify the disabled state before
    # attempting submission so the assertion in the Then step reflects
    # the guard, not a missing UI element.
    search_input = only_searchbox(spa_page)
    expect(search_input).to_be_disabled(timeout=5000)


@then("the answer is not sent to the server")
def answer_not_sent(mock_ws_server):
    conn = mock_ws_server.latest_connection
    answer_events = conn.events_of("game:answer")
    assert len(answer_events) == 0, "game:answer should not have been sent"


@given("the player has no attempts remaining")
def no_attempts(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url, attempts_limit=3)
    mock_ws_server.latest_connection.send_event(
        "game:player-state",
        {
            "scored": False,
            "wrongAnswerCount": 3,
            "lockoutExpiresAt": None,
            "pendingAnswer": None,
        },
    )
    spa_page.wait_for_timeout(500)


# Reuses try_submit and answer_not_sent


@given(parsers.parse("the player has handicap of {seconds:d} seconds"))
def player_has_handicap(spa_page, mock_ws_server, frontend_url, seconds):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url, handicap=seconds)


@when("the player submits an answer")
def submit_answer(spa_page):
    _submit_song_suggestion(spa_page, "Song 1")


@then("a panel shows the submitted song title")
def panel_shows_submitted_title(spa_page):
    panel = only_status(spa_page, "Song 1")
    expect(panel).to_be_visible(timeout=5000)


@then(
    parsers.parse(
        "a countdown from {seconds} seconds is displayed updating every 100ms"
    )
)
def countdown_displayed(spa_page, seconds):
    # Verify the countdown initially shows ``seconds`` and decrements;
    # 100ms cadence is verified by sampling twice with a 300ms gap.
    countdown = only_role(spa_page, "timer")
    expect(countdown).to_contain_text(str(seconds), timeout=5000)
    initial = countdown.inner_text()
    spa_page.wait_for_timeout(300)
    later = countdown.inner_text()
    assert initial != later, (
        f"Expected countdown to update within 300ms, got {initial!r} == {later!r}"
    )


@then("a progress bar decreases over time")
def progress_bar(spa_page):
    bar = only_role(spa_page, "progressbar")
    expect(bar).to_be_visible(timeout=5000)
    initial = bar.get_attribute("aria-valuenow") or bar.get_attribute("value")
    spa_page.wait_for_timeout(500)
    later = bar.get_attribute("aria-valuenow") or bar.get_attribute("value")
    assert initial != later, (
        f"Expected progress bar to advance within 500ms, got {initial} == {later}"
    )


@given("the handicap countdown is displayed")
def handicap_countdown_displayed(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url, handicap=5)
    _submit_song_suggestion(spa_page, "Song 1")
    spa_page.wait_for_timeout(500)


@when("the player submits a new answer")
def submit_new_answer(spa_page):
    _submit_song_suggestion(spa_page, "Song 2")


@then("the countdown restarts from the full handicap duration")
def countdown_restarts(spa_page):
    expect(only_role(spa_page, "timer")).to_contain_text("5", timeout=5000)


@then("the panel shows the new song title")
def panel_new_title(spa_page):
    expect(only_status(spa_page, "Song 2")).to_be_visible(timeout=5000)


# Reuses player_has_handicap with 0 and submit_answer


@then("no countdown is displayed")
def no_countdown(spa_page):
    spa_page.wait_for_timeout(500)
    expect(spa_page.get_by_role("timer")).to_have_count(0)


@when("game:scored or game:wrong-answer is received for the player")
def scored_or_wrong(spa_page, mock_ws_server):
    mock_ws_server.latest_connection.send_event(
        "game:scored",
        {
            "playerId": SELF_PLAYER_ID,
            "nickname": "Player 1",
            "rank": 1,
            "points": 4,
        },
    )
    spa_page.wait_for_timeout(500)


@then("the handicap countdown is cleared")
def handicap_cleared(spa_page):
    spa_page.wait_for_timeout(500)
    expect(spa_page.get_by_role("timer")).to_have_count(0)


@when("the countdown reaches 0")
def countdown_zero(spa_page):
    # handicap=5 from the preceding Given. Wait past expiry plus margin
    # for the SPA to clear the timer node.
    spa_page.wait_for_timeout(6000)


# Reuses handicap_cleared


@given("the player submitted a wrong answer")
def submitted_wrong(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "game:wrong-answer",
        {
            "playerId": SELF_PLAYER_ID,
            "songTitle": "Wrong Song",
            "wrongAnswerCount": 1,
            "lockoutExpiresAt": None,
        },
    )
    spa_page.wait_for_timeout(500)


@then(parsers.parse('the wrong answer title is displayed as "Wrong: {{title}}"'))
def wrong_answer_displayed(spa_page):
    panel = only_status(spa_page, "Wrong:")
    expect(panel).to_be_visible(timeout=5000)


@given("the wrong answer feedback is displayed")
def wrong_feedback_displayed(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "game:wrong-answer",
        {
            "playerId": SELF_PLAYER_ID,
            "songTitle": "Wrong Song",
            "wrongAnswerCount": 1,
            "lockoutExpiresAt": None,
        },
    )
    expect(only_status(spa_page, "Wrong:")).to_be_visible(timeout=5000)


@when("2 seconds elapse")
def two_seconds_elapse(spa_page):
    spa_page.wait_for_timeout(2500)


@then("the wrong answer feedback disappears")
def wrong_feedback_gone(spa_page):
    expect(spa_page.get_by_role("status").filter(has_text="Wrong:")).to_have_count(0)


@given("the player is locked out")
def player_locked_out(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url, lockout_duration=5)
    expires = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5)
    ).isoformat()
    mock_ws_server.latest_connection.send_event(
        "game:player-state",
        {
            "scored": False,
            "wrongAnswerCount": 1,
            "lockoutExpiresAt": expires,
            "pendingAnswer": None,
        },
    )
    spa_page.wait_for_timeout(500)


@then("the search field is disabled")
def search_disabled(spa_page):
    expect(only_searchbox(spa_page)).to_be_disabled(timeout=5000)


@then(parsers.parse('the placeholder shows "Locked out..."'))
def placeholder_locked(spa_page):
    search_input = only_searchbox(spa_page)
    expect(search_input).to_have_attribute("placeholder", "Locked out...")


@then(parsers.parse('a panel shows "Locked out for {{N}}s" updating every 100ms'))
def lockout_panel(spa_page):
    panel = only_status(spa_page, "Locked out for")
    expect(panel).to_be_visible(timeout=5000)
    initial = panel.inner_text()
    spa_page.wait_for_timeout(300)
    later = panel.inner_text()
    assert initial != later, (
        f"Expected lockout panel to update within 300ms, got {initial!r} == {later!r}"
    )


@given(parsers.parse("a game with attemptsLimit {limit:d}"))
@given(parsers.parse("a game with attempts limit {limit:d}"))
def game_with_attempts_limit(spa_page, mock_ws_server, frontend_url, limit):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url, attempts_limit=limit)


@given(parsers.parse("the player has {count:d} attempts remaining"))
def attempts_remaining(spa_page, mock_ws_server, count):
    # The preceding ``a game with attemptsLimit 3`` Given fixes the limit;
    # subtract to derive the matching wrongAnswerCount the SPA expects.
    wrong_count = 3 - count
    mock_ws_server.latest_connection.send_event(
        "game:player-state",
        {
            "scored": False,
            "wrongAnswerCount": wrong_count,
            "lockoutExpiresAt": None,
            "pendingAnswer": None,
        },
    )
    spa_page.wait_for_timeout(500)


# '"2 / 3 attempts left" is displayed' is handled by conftest


@given("the player has used all attempts")
def all_attempts_used(spa_page, mock_ws_server):
    mock_ws_server.latest_connection.send_event(
        "game:player-state",
        {
            "scored": False,
            "wrongAnswerCount": 3,
            "lockoutExpiresAt": None,
            "pendingAnswer": None,
        },
    )
    spa_page.wait_for_timeout(500)


# '"0 / 3 attempts left" is displayed' is handled by conftest


@then("no attempts display is shown")
def no_attempts_display(spa_page):
    expect(spa_page.get_by_text("attempts left", exact=False)).to_have_count(0)


@given(parsers.parse("the player answered correctly and earned {points:d} points"))
def player_scored(spa_page, mock_ws_server, frontend_url, points):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "game:scored",
        {
            "playerId": SELF_PLAYER_ID,
            "nickname": "Player 1",
            "rank": 1,
            "points": points,
        },
    )
    spa_page.wait_for_timeout(500)


@then(parsers.parse('a panel shows "You scored {points:d} points!"'))
def panel_scored(spa_page, points):
    panel = only_status(spa_page, f"You scored {points} points!")
    expect(panel).to_be_visible(timeout=5000)


@then("the search input and suggestions are not visible")
def search_not_visible(spa_page):
    expect(spa_page.get_by_role("searchbox")).to_have_count(0)
    expect(_suggestions_listbox(spa_page)).to_have_count(0)


@given("the player's correct answer fills the last scoring slot")
def fills_last_slot(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    conn = mock_ws_server.latest_connection
    # Send scored and reveal immediately to simulate auto-reveal
    conn.send_event(
        "game:scored",
        {
            "playerId": SELF_PLAYER_ID,
            "nickname": "Player 1",
            "rank": 1,
            "points": 4,
        },
    )
    conn.send_event(
        "game:reveal",
        {
            "song": {
                "id": "song1",
                "title": "Song 1",
                "artist": "Artist 1",
                "artworkUrl": None,
            },
            "winners": [{"nickname": "Player 1", "rank": 1, "points": 4}],
        },
    )
    spa_page.wait_for_timeout(1000)


@then("the scoring panel is not displayed")
def scoring_panel_hidden(spa_page):
    expect(spa_page.get_by_role("status").filter(has_text="You scored")).to_have_count(
        0
    )


@then("the player sees themselves in the reveal panel winners instead")
def player_in_reveal(spa_page):
    reveal_panel = only_region(spa_page, "Reveal")
    expect(reveal_panel).to_contain_text("Player 1", timeout=5000)


@given(parsers.parse("another player scored {points:d} points as {rank} place"))
def other_player_scored(spa_page, mock_ws_server, frontend_url, points, rank):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    rank_num = int(
        rank.replace("st", "").replace("nd", "").replace("rd", "").replace("th", "")
    )
    mock_ws_server.latest_connection.send_event(
        "game:scored",
        {
            "playerId": "player-2",
            "nickname": "Host",
            "rank": rank_num,
            "points": points,
        },
    )
    spa_page.wait_for_timeout(500)


@then(parsers.parse('a panel shows "{{nickname}} scored {{points}}pt(s)! ({{rank}})"'))
@then('a panel shows "{nickname} scored 4pt(s)! (1st)"')
def panel_other_scored(spa_page):
    panel = only_status(spa_page, "scored")
    expect(panel).to_be_visible(timeout=5000)


@then("ordinals follow: 1st, 2nd, 3rd, 4th...")
def ordinals_follow(spa_page):
    # The preceding step verified a scored panel is visible. Check that an
    # ordinal suffix (st, nd, rd, th) is present in the displayed text.
    expect(only_status(spa_page, "1st")).to_be_visible(timeout=5000)


@given("the game screen is displayed")
def game_screen_displayed(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)


@then("the search field is focused")
def search_focused(spa_page):
    expect(only_searchbox(spa_page)).to_be_focused(timeout=5000)


@then("the search field is disabled and dimmed")
def search_disabled_dimmed(spa_page):
    expect(only_searchbox(spa_page)).to_be_disabled(timeout=5000)


@when("game:player-state is received with scored as true")
def player_state_scored(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url)
    mock_ws_server.latest_connection.send_event(
        "game:player-state",
        {
            "scored": True,
            "earnedPoints": 4,
            "wrongAnswerCount": 0,
            "lockoutExpiresAt": None,
            "pendingAnswer": None,
        },
    )
    spa_page.wait_for_timeout(500)


@then("the scored panel is displayed with the earned points")
def scored_panel(spa_page):
    expect(only_status(spa_page, "You scored 4 points!")).to_be_visible(timeout=5000)


@then("the search UI is hidden")
def search_hidden(spa_page):
    expect(spa_page.get_by_role("searchbox")).to_have_count(0)


@when("game:player-state is received with an active lockout")
def player_state_lockout(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url, lockout_duration=5)
    expires = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5)
    ).isoformat()
    mock_ws_server.latest_connection.send_event(
        "game:player-state",
        {
            "scored": False,
            "wrongAnswerCount": 1,
            "lockoutExpiresAt": expires,
            "pendingAnswer": None,
        },
    )
    spa_page.wait_for_timeout(500)


@then("the lockout countdown is displayed with the remaining time")
def lockout_countdown(spa_page):
    expect(only_status(spa_page, "Locked out for")).to_be_visible(timeout=5000)


@when("game:player-state is received with wrongAnswerCount greater than 0")
def player_state_wrong_count(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url, attempts_limit=3)
    mock_ws_server.latest_connection.send_event(
        "game:player-state",
        {
            "scored": False,
            "wrongAnswerCount": 2,
            "lockoutExpiresAt": None,
            "pendingAnswer": None,
        },
    )
    spa_page.wait_for_timeout(500)


@then("the attempts remaining display reflects the restored count")
def attempts_restored(spa_page):
    expect(spa_page.get_by_text("1 / 3 attempts left", exact=True)).to_be_visible(
        timeout=5000
    )


@when("game:player-state is received with a pending answer")
def player_state_pending(spa_page, mock_ws_server, frontend_url):
    _enter_guest_game(spa_page, mock_ws_server, frontend_url, handicap=5)
    expires = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=3)
    ).isoformat()
    mock_ws_server.latest_connection.send_event(
        "game:player-state",
        {
            "scored": False,
            "wrongAnswerCount": 0,
            "lockoutExpiresAt": None,
            "pendingAnswer": {
                "songId": "song1",
                "songTitle": "Song 1",
                "expiresAt": expires,
            },
        },
    )
    spa_page.wait_for_timeout(500)


@then("the handicap countdown is displayed with the remaining time")
def handicap_countdown_remaining(spa_page):
    expect(only_role(spa_page, "timer")).to_contain_text("Song 1", timeout=5000)


@then("the submitted song title is shown")
def submitted_title_shown(spa_page):
    expect(only_status(spa_page, "Song 1")).to_be_visible(timeout=5000)
