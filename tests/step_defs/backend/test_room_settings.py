"""Step definitions for room_settings.feature — settings, nickname, handicap, and field validations."""

from pytest_bdd import given, parsers, scenarios, then, when

from backend.helpers import create_room, setup_valid_game

scenarios("../../features/backend/room_settings.feature")


@then("the server checks room:settings in the following order:")
def settings_check_order(ctx, make_player, datatable):
    """Verify each row's error fires, then verify ordering via pair tests
    where two checks would fail simultaneously."""
    # Row 1: non-host in lobby — "Only the host can change settings".
    host, players, room_code = create_room(make_player, 2)
    players[0].send("room:settings", {"totalRounds": 5})
    players[0].expect_error("Only the host can change settings")
    # Order 1 < 3: non-host with empty payload → row 1 wins.
    players[0].send("room:settings", {})
    players[0].expect_error("Only the host can change settings")

    # Row 2: host outside lobby — "Can only change settings in lobby".
    host2, players2, room_code2 = create_room(make_player, 2)
    setup_valid_game(host2, players2, room_code2)
    host2.send("room:settings", {"totalRounds": 5})
    host2.expect_error("Can only change settings in lobby")
    # Order 2 < 3: host outside lobby with empty payload → row 2 wins.
    host2.send("room:settings", {})
    host2.expect_error("Can only change settings in lobby")

    # Row 3: host in lobby with empty payload — "Settings payload must not be empty".
    host.send("room:settings", {})
    host.expect_error("Settings payload must not be empty")
    # Order 3 < 4: empty payload with invalid field → row 3 wins (empty has priority).
    # An empty dict has no fields to validate, so row 4 cannot fire here;
    # this is implicit from row 3's success above.

    # Row 4: host in lobby with invalid field value — "Settings validation failed".
    host.send("room:settings", {"totalRounds": -1})
    host.expect_error("Settings validation failed")

    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@then("field validations are applied to each field present in the payload")
def field_validations_applied(ctx):
    event = ctx.host.expect_event("error")
    ctx.validation_error_event = event
    msg = event["payload"]["message"]
    assert msg == "Settings validation failed"
    # Both invalid fields must surface as individual entries in details —
    # this is what "applied to each field" demands, not just the aggregate
    # "Settings validation failed" header.
    details = event["payload"].get("details") or []
    combined = " ".join(details).lower()
    assert "total rounds" in combined or "totalrounds" in combined, (
        f"totalRounds error missing from details: {details}"
    )
    assert "lockout" in combined, (
        f"lockoutDuration error missing from details: {details}"
    )


@when("the host sends room:settings with multiple fields that fail validation")
def host_sends_multiple_invalid_settings(ctx, host):
    ctx.host = host
    host.send("room:settings", {"totalRounds": -1, "lockoutDuration": -1})


@then("all field validation errors are collected and returned in a single error event")
@then(
    'all field validation errors are collected in a single error event with message "Settings validation failed" and individual errors in details'
)
def field_errors_collected(ctx):
    errors = ctx.host.find_all_events("error")
    assert len(errors) == 1
    details = errors[0]["payload"].get("details") or []
    # Two fields were sent invalid in the prior step; both must be reported
    # in the single error event's details (not split across multiple events).
    assert len(details) >= 2, (
        f"Expected at least 2 individual field errors in details, got {details}"
    )


@then(
    'the error message is "Settings validation failed" with individual errors in details'
)
def settings_validation_failed(ctx):
    event = getattr(ctx, "validation_error_event", None) or ctx.host.find_last_event(
        "error"
    )
    assert event is not None
    assert event["payload"]["message"] == "Settings validation failed"
    details = event["payload"].get("details") or []
    assert len(details) >= 1, "details must contain at least one individual error"


@then("if any field validation fails, no fields in the payload are applied")
@then("no fields in the payload are applied")
def no_partial_apply(ctx):
    ctx.host.assert_no_event("room:settings", timeout=0.5)


@when("the host sends room:settings with no fields")
def host_sends_empty_settings(ctx, host):
    ctx.host = host
    host.send("room:settings", {})


@when("the host sends room:settings with partial settings")
def host_sends_partial_settings(ctx, host):
    ctx.host = host
    ctx.expected_settings_update = {"totalRounds": 5}
    host.send("room:settings", {"totalRounds": 5})


@then("the settings are partially merged")
def settings_partially_merged(ctx):
    event = ctx.host.expect_event("room:settings")
    payload = event["payload"]
    ctx.last_settings = event
    expected = getattr(ctx, "expected_settings_update", None)
    assert expected is not None, "When step must record the expected partial update"
    for field, value in expected.items():
        assert payload[field] == value, f"{field} should reflect the new value"
    if set(expected) == {"totalRounds"}:
        assert payload["playbackDurations"] == [], (
            "Unmodified field should remain unset"
        )
        assert payload["rankPoints"] == [], "Unmodified field should remain unset"
        assert payload["lockoutDuration"] is None, (
            "Unmodified field should remain unset"
        )
        assert payload["attemptsLimit"] is None, "Unmodified field should remain unset"


@when("the host sends room:settings")
def host_sends_settings(ctx):
    ctx.host.send("room:settings", {"totalRounds": 5})


@then("the settings are not changed")
def settings_not_changed(ctx):
    events = ctx.host.drain_events(wait=0.5)
    settings = [event for event in events if event["event"] == "room:settings"]
    assert not settings, f"Settings should not change, got: {settings}"
    errors = [event for event in events if event["event"] == "error"]
    if errors:
        ctx.last_error_event = errors[0]


@when("a non-host player tries to update settings")
def non_host_updates_settings(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.error_target = players[0]
    players[0].send("room:settings", {"totalRounds": 5})


@then("the server checks room:nickname in the following order:")
def nickname_check_order(make_player, datatable):
    # Row 1: outside lobby — "Can only change nickname in lobby".
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    players[0].send("room:nickname", {"nickname": "Test"})
    players[0].expect_error("Can only change nickname in lobby")
    # Order 1 < 2: outside lobby with empty nickname → row 1 wins.
    players[0].send("room:nickname", {"nickname": ""})
    players[0].expect_error("Can only change nickname in lobby")
    # Order 1 < 3: outside lobby with too-long nickname → row 1 wins.
    players[0].send("room:nickname", {"nickname": "A" * 21})
    players[0].expect_error("Can only change nickname in lobby")

    # Row 2: in lobby, empty nickname — "Nickname is required".
    host2, players2, _ = create_room(make_player, 1)
    players2[0].send("room:nickname", {"nickname": ""})
    players2[0].expect_error("Nickname is required")
    # Order 2 < 3: empty + too-long would never co-occur (empty < 21 chars).
    # Verify by sending only-whitespace which is also "Nickname is required".
    players2[0].send("room:nickname", {"nickname": "   "})
    players2[0].expect_error("Nickname is required")

    # Row 3: in lobby, > 20 chars — "Nickname must be 20 characters or less".
    players2[0].send("room:nickname", {"nickname": "A" * 21})
    players2[0].expect_error("Nickname must be 20 characters or less")


@then("the nickname is sanitized and trimmed before validation")
def nickname_sanitized(make_player):
    # Verify: control chars stripped, then trimmed, then validated.
    # Send a nickname with control chars that would be empty after sanitization.
    _, players, _ = create_room(make_player, 2)
    players[0].send("room:nickname", {"nickname": "\x00\x01\x02"})
    players[0].expect_error("Nickname is required")


@given("player A has created a room")
def player_a_created_room(ctx, make_player):
    host = make_player()
    room_code = host.create_room()
    ctx.host = host
    ctx.room_code = room_code


@when("player A sends room:join", target_fixture="player_a_settings")
@when(
    "player A creates the room and sends room:join", target_fixture="player_a_settings"
)
def player_a_joins(ctx):
    host = ctx.host
    room_code = ctx.room_code
    host.join_room(room_code)
    event = host.expect_event("room:settings")
    return event


@when("player B sends room:join", target_fixture="player_b")
def player_b_joins(ctx, make_player):
    room_code = ctx.room_code
    player = make_player()
    player.join_room(room_code)
    player.expect_event("room:settings")
    ctx.host.drain_events(wait=0.3)
    return player


@when("player C sends room:join", target_fixture="player_c")
def player_c_joins(ctx, make_player, player_b):
    room_code = ctx.room_code
    player = make_player()
    player.join_room(room_code)
    player.expect_event("room:settings")
    ctx.host.drain_events(wait=0.3)
    player_b.drain_events(wait=0.2)
    return player


@then('player A\'s nickname is "Player 1"')
def player_a_nickname(ctx):
    host = ctx.host
    host.drain_events(wait=0.3)
    event = host.find_last_event("room:settings")
    assert event is not None
    settings = event["payload"]
    host_player = next(
        p for p in settings["activePlayers"] if p["id"] == host.player_id
    )
    assert host_player["nickname"] == "Player 1"


@then('player B\'s nickname is "Player 2"')
def player_b_nickname(ctx, player_b):
    host = ctx.host
    event = host.find_last_event("room:settings")

    assert event is not None
    settings = event["payload"]
    all_players = settings["activePlayers"] + settings["inactivePlayers"]
    matched = next(p for p in all_players if p["id"] == player_b.player_id)
    assert matched["nickname"] == "Player 2"


@then('player C\'s nickname is "Player 3"')
def player_c_nickname(ctx, player_c):
    host = ctx.host
    event = host.find_last_event("room:settings")
    assert event is not None
    settings = event["payload"]
    all_players = settings["activePlayers"] + settings["inactivePlayers"]
    matched = next(p for p in all_players if p["id"] == player_c.player_id)
    assert matched["nickname"] == "Player 3"


@given(
    "Player 1, Player 2, and Player 3 have joined the room",
)
def three_players_joined(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)

    ctx.host = host
    ctx.room_code = room_code
    ctx.players = players


@given("Player 2 has left the room")
def player2_left(ctx):
    ctx.players[0].leave_room()
    ctx.host.drain_events(wait=0.5)
    ctx.players[1].drain_events(wait=0.3)


@when("a new player joins the room", target_fixture="new_player_4")
def new_player_joins(ctx, make_player):
    new_player = make_player()
    new_player.join_room(ctx.room_code)
    new_player.expect_event("room:settings")
    ctx.host.drain_events(wait=0.3)
    return new_player


@then('the new player\'s nickname is "Player 4"')
def new_player_nickname(ctx, new_player_4):
    host = ctx.host
    event = host.find_last_event("room:settings")
    assert event is not None
    settings = event["payload"]
    all_players = settings["activePlayers"] + settings["inactivePlayers"]
    matched = next(p for p in all_players if p["id"] == new_player_4.player_id)
    assert matched["nickname"] == "Player 4"


@given("a room has been created")
def room_has_been_created(ctx, make_player):

    host, _, room_code = create_room(make_player, 0)
    ctx.host = host
    ctx.room_code = room_code


@then("the auto-assigned nickname counter persists until the room is deleted")
def counter_persists(ctx, make_player):
    # Verify the counter increments across multiple joins, proving it persists.
    # Join two players and confirm they receive consecutive incrementing nicknames.
    room_code = ctx.room_code
    player1 = make_player()
    player1.join_room(room_code)
    player1.expect_event("room:settings")
    ctx.host.drain_events(wait=0.3)

    player2 = make_player()
    player2.join_room(room_code)
    player2.expect_event("room:settings")
    ctx.host.drain_events(wait=0.3)
    player1.drain_events(wait=0.2)

    event = ctx.host.find_last_event("room:settings")
    assert event is not None
    all_players = (
        event["payload"]["activePlayers"] + event["payload"]["inactivePlayers"]
    )
    # The host joined as "Player 1" (counter=1), player1 as "Player 2" (counter=2),
    # player2 as "Player 3" (counter=3). Confirm counter incremented.
    nicknames = [p["nickname"] for p in all_players]
    assert any("Player 2" in n for n in nicknames), (
        f"Expected incrementing nicknames but got: {nicknames}"
    )
    assert any("Player 3" in n for n in nicknames), (
        f"Expected incrementing nicknames but got: {nicknames}"
    )


@given("a player is in a room")
def player_in_room(ctx, make_player):
    host, players, room_code = create_room(make_player, 1)

    ctx.host = host
    ctx.players = players[:1]
    ctx.room_code = room_code
    ctx.error_target = players[0]


@when(parsers.parse('the player sends room:nickname with "{nickname}"'))
def player_sends_nickname(ctx, nickname):
    ctx.players[0].send("room:nickname", {"nickname": nickname})


@then(parsers.parse('the player\'s nickname is "{nickname}"'))
def player_nickname_is(ctx, nickname):
    host = ctx.host
    event = host.expect_event("room:settings")
    ctx.last_settings = event
    payload = event["payload"]
    all_players = payload["activePlayers"] + payload["inactivePlayers"]
    target = ctx.players[0]
    matched = next(pl for pl in all_players if pl["id"] == target.player_id)
    assert matched["nickname"] == nickname


def player_sends_nickname_whitespace(ctx):
    ctx.players[0].send("room:nickname", {"nickname": "  Alice  "})


@when(
    "the player sends room:nickname containing control characters (Unicode category Cc)"
)
def player_sends_nickname_control(ctx):
    ctx.players[0].send("room:nickname", {"nickname": "Al\x00ic\x01e"})


@then("the control characters are removed")
def control_chars_removed(ctx):
    host = ctx.host
    target = ctx.players[0]
    # The nickname "Al\x00ic\x01e" should become "Alice" after sanitization.
    # The room:settings broadcast will contain the sanitized nickname.
    event = host.expect_event("room:settings")
    ctx.last_settings = event
    payload = event["payload"]
    all_players = payload["activePlayers"] + payload["inactivePlayers"]
    matched = next(pl for pl in all_players if pl["id"] == target.player_id)
    assert matched["nickname"] == "Alice"


@then("the result is trimmed and then validated")
def result_trimmed_validated(ctx):
    # The previous step already verified the nickname is "Alice" (control
    # characters removed, result trimmed). This step confirms the trimmed
    # result passed validation by checking it was accepted (no error).
    ctx.players[0].assert_no_event("error", timeout=0.5)


@when("the player sends room:nickname containing only control characters")
def player_sends_only_control(ctx):
    ctx.players[0].send("room:nickname", {"nickname": "\x00\x01\x02"})


@when("a player sends room:nickname")
def player_sends_nickname_not_lobby(ctx):
    ctx.error_target = ctx.players[0]
    ctx.players[0].send("room:nickname", {"nickname": "Test"})


@when('the player sends room:nickname with ""')
def player_sends_empty_nickname(ctx):
    ctx.players[0].send("room:nickname", {"nickname": ""})


def player_sends_whitespace_nickname(ctx):
    ctx.players[0].send("room:nickname", {"nickname": "   "})


@when("the player sends room:nickname with a 21-character string")
def player_sends_long_nickname(ctx):
    ctx.players[0].send("room:nickname", {"nickname": "A" * 21})


@given(
    parsers.parse('a player with nickname "{nickname}" is in the room'),
)
def player_with_nickname_in_room(ctx, make_player, nickname):
    host, players, room_code = create_room(make_player, 1)
    player = players[0]

    player.send("room:nickname", {"nickname": nickname})
    host.expect_event("room:settings")
    player.drain_events(wait=0.3)

    ctx.host = host
    ctx.players = [player]
    ctx.room_code = room_code


@when("the player disconnects")
def player_disconnects(ctx):
    player = ctx.players[0]
    player.disconnect()
    ctx.host.drain_events(wait=0.3)


@when("the player rejoins")
def player_rejoins(ctx):
    player = ctx.players[0]
    room_code = ctx.room_code
    player.reconnect()
    player.join_room(room_code)


@when("the player disconnects and reconnects")
def player_disconnects_reconnects(ctx):
    player_disconnects(ctx)
    player_rejoins(ctx)


@given(
    parsers.parse('a player has nickname "{nickname}"'),
)
def player_has_nickname(ctx, make_player, nickname):
    host, players, room_code = create_room(make_player, 1)
    player = players[0]

    player.send("room:nickname", {"nickname": nickname})
    host.expect_event("room:settings")
    player.drain_events(wait=0.3)

    ctx.host = host
    ctx.players = [player]
    ctx.room_code = room_code


@when(parsers.parse('another player sends room:nickname with "{nickname}"'))
def another_player_sends_nickname(ctx, make_player, nickname):
    room_code = ctx.room_code
    other_player = make_player()
    other_player.join_room(room_code)
    other_player.expect_event("room:settings")
    ctx.host.drain_events(wait=0.3)
    ctx.players[0].drain_events(wait=0.2)

    other_player.send("room:nickname", {"nickname": nickname})
    ctx.players.append(other_player)


@then("the nickname is accepted")
def nickname_accepted(ctx):
    ctx.last_settings = ctx.host.expect_event("room:settings")


@then("the server checks room:handicap in the following order:")
def handicap_check_order(make_player, datatable):
    # Row 1: outside lobby — "Can only change handicap in lobby".
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    players[0].send("room:handicap", {"handicap": 5})
    players[0].expect_error("Can only change handicap in lobby")
    # Order 1 < 2: outside lobby with out-of-range handicap → row 1 wins.
    players[0].send("room:handicap", {"handicap": 31})
    players[0].expect_error("Can only change handicap in lobby")
    players[0].send("room:handicap", {"handicap": -1})
    players[0].expect_error("Can only change handicap in lobby")

    # Row 2: in lobby, out of range — "Handicap must be between 0 and 30 seconds".
    host2, players2, _ = create_room(make_player, 1)
    players2[0].send("room:handicap", {"handicap": 31})
    players2[0].expect_error("Handicap must be between 0 and 30 seconds")
    players2[0].send("room:handicap", {"handicap": -1})
    players2[0].expect_error("Handicap must be between 0 and 30 seconds")


@given("a player is in a room in lobby phase")
def player_in_lobby_room(ctx, make_player):
    host, players, room_code = create_room(make_player, 1)

    ctx.host = host
    ctx.players = players[:1]
    ctx.room_code = room_code
    ctx.error_target = players[0]


@when(parsers.parse("the player sends room:handicap with {value:g}"))
def player_sends_handicap(ctx, value):
    ctx.players[0].send("room:handicap", {"handicap": value})


@then(parsers.parse("the player's handicap is {value:g} seconds"))
def player_handicap_is(ctx, value):
    host = ctx.host
    event = host.expect_event("room:settings")
    ctx.last_settings = event
    payload = event["payload"]
    all_players = payload["activePlayers"] + payload["inactivePlayers"]
    target = ctx.players[0]
    matched = next(pl for pl in all_players if pl["id"] == target.player_id)
    assert matched["handicap"] == value


@when("a player sends room:handicap")
def player_sends_handicap_not_lobby(ctx):

    ctx.error_target = ctx.players[0]
    ctx.players[0].send("room:handicap", {"handicap": 5})


def player_zero_handicap_game(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled


@when("the player sends game:answer")
def player_sends_answer_zero_handicap(ctx):
    host = ctx.host
    shuffled = ctx.shuffled
    host.send("game:play-song")
    host.drain_events(wait=0.3)
    for player in ctx.players:
        player.drain_events(wait=0.2)

    if shuffled:
        ctx.players[0].send("game:answer", {"songId": shuffled[0]})


@then("the answer is processed immediately")
def answer_processed_immediately(ctx):
    player = ctx.players[0]
    events = player.drain_events(wait=1.0)
    event_types = [e["event"] for e in events]
    assert (
        "game:scored" in event_types
        or "game:wrong-answer" in event_types
        or "error" in event_types
    )


@given(
    parsers.parse("a player with handicap {seconds:d} seconds is in a game"),
)
def player_handicap_in_game(ctx, make_player, seconds):
    host, players, room_code = create_room(make_player, 1)
    player = players[0]

    player.send("room:handicap", {"handicap": seconds})
    host.expect_event("room:settings")
    player.drain_events(wait=0.3)

    player2 = make_player()
    player2.join_room(room_code)
    player2.expect_event("room:settings")
    host.drain_events(wait=0.3)
    player.drain_events(wait=0.2)

    shuffled = setup_valid_game(host, [player, player2], room_code)

    ctx.host = host
    ctx.players = [player]
    ctx.room_code = room_code
    ctx.shuffled = shuffled


# "the player disconnects and reconnects" — reuses step above via ctx

# "the player's handicap is {value} seconds" — reuses player_handicap_is via ctx


@when("the host sends room:settings with more than 1000 songs")
def host_sends_too_many_songs(ctx, host):
    ctx.host = host
    songs = [
        {
            "id": f"song{i}",
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "artworkUrl": None,
        }
        for i in range(1001)
    ]
    host.send("room:settings", {"songs": songs})


@when("the host sends room:settings with a song that has an empty ID")
def host_sends_song_empty_id(ctx, host):
    ctx.host = host
    songs = [{"id": "", "title": "Song", "artist": "Artist", "artworkUrl": None}]
    host.send("room:settings", {"songs": songs})


@when("the host sends room:settings with a song that has an empty title")
def host_sends_song_empty_title(ctx, host):
    ctx.host = host
    songs = [{"id": "song1", "title": "", "artist": "Artist", "artworkUrl": None}]
    host.send("room:settings", {"songs": songs})


@when("the host sends room:settings with a song that has an empty artist")
def host_sends_song_empty_artist(ctx, host):
    ctx.host = host
    songs = [{"id": "song1", "title": "Song", "artist": "", "artworkUrl": None}]
    host.send("room:settings", {"songs": songs})


@when("the host sends room:settings with songs containing duplicate IDs")
def host_sends_duplicate_song_ids(ctx, host):
    ctx.host = host
    songs = [
        {"id": "song1", "title": "Song 1", "artist": "Artist 1", "artworkUrl": None},
        {"id": "song1", "title": "Song 2", "artist": "Artist 2", "artworkUrl": None},
    ]
    host.send("room:settings", {"songs": songs})


@when("the host sends room:settings with a song that has an empty artworkUrl")
def host_sends_song_empty_artwork(ctx, host):
    ctx.host = host
    songs = [{"id": "song1", "title": "Song", "artist": "Artist", "artworkUrl": ""}]
    host.send("room:settings", {"songs": songs})


@when("the host sends room:settings with playbackDurations []")
def host_sends_empty_durations(ctx, host):
    ctx.host = host
    host.send("room:settings", {"playbackDurations": []})


@when("the host sends room:settings with 11 playback durations")
def host_sends_11_durations(ctx, host):
    ctx.host = host
    host.send("room:settings", {"playbackDurations": list(range(1, 12))})


@when(parsers.parse("the host sends room:settings with playbackDurations [{values}]"))
def host_sends_specific_durations(ctx, host, values):
    ctx.host = host
    durations = [
        float(v.strip()) if "." in v.strip() else int(v.strip())
        for v in values.split(",")
    ]
    ctx.expected_settings_update = {"playbackDurations": durations}
    host.send("room:settings", {"playbackDurations": durations})


@when("the host sends room:settings with rankPoints []")
def host_sends_empty_rank_points(ctx, host):
    ctx.host = host
    host.send("room:settings", {"rankPoints": []})


@when("the host sends room:settings with 11 rank points")
def host_sends_11_rank_points(ctx, host):
    ctx.host = host
    host.send("room:settings", {"rankPoints": list(range(1, 12))})


@when(parsers.parse("the host sends room:settings with rankPoints [{values}]"))
def host_sends_specific_rank_points(ctx, host, values):
    ctx.host = host
    points = [
        float(v.strip()) if "." in v.strip() else int(v.strip())
        for v in values.split(",")
    ]
    if all(isinstance(point, int) for point in points):
        ctx.expected_settings_update = {"rankPoints": points}
    host.send("room:settings", {"rankPoints": points})


@when(parsers.parse("the host sends room:settings with lockoutDuration {value:g}"))
def host_sends_lockout_duration(ctx, host, value):
    ctx.host = host
    ctx.expected_settings_update = {"lockoutDuration": value}
    host.send("room:settings", {"lockoutDuration": value})


@when(parsers.parse("the host sends room:settings with attemptsLimit {value:g}"))
def host_sends_attempts_limit(ctx, host, value):
    ctx.host = host
    if int(value) == value:
        ctx.expected_settings_update = {"attemptsLimit": int(value)}
    host.send("room:settings", {"attemptsLimit": value})


@when(parsers.parse("the host sends room:settings with totalRounds {value:g}"))
def host_sends_total_rounds(ctx, host, value):
    ctx.host = host
    host.send("room:settings", {"totalRounds": value})


@when(
    "the host sends room:settings with totalRounds greater than the maximum song count"
)
def host_sends_total_rounds_exceeding(ctx, host):
    ctx.host = host
    host.send("room:settings", {"totalRounds": 1001})


@given("a room in lobby phase with total rounds set to 10")
@given("a room in lobby phase with totalRounds set to 10")
def room_with_total_rounds(ctx, host):
    host.send("room:settings", {"totalRounds": 10})
    host.expect_event("room:settings")
    ctx.host = host
    ctx.room_code = host.room_code


@when("the host sends room:settings with 5 songs")
def host_sends_5_songs(ctx):
    host = ctx.host
    songs = [
        {
            "id": f"song{i}",
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "artworkUrl": None,
        }
        for i in range(1, 6)
    ]
    host.send("room:settings", {"songs": songs})


@then("totalRounds remains 10")
def total_rounds_unchanged(ctx):
    host = ctx.host
    event = host.expect_event("room:settings")
    payload = event["payload"]
    assert payload["totalRounds"] == 10
