"""Step definitions for answer.feature — answer submission, scoring, and penalties.

Many scenarios share the same When/Then text with different Given preconditions.
Each Given populates the unified ``ctx`` (ScenarioContext) fixture consumed by
shared steps.
"""

import time
from pytest_bdd import given, parsers, scenarios, then, when

from backend.helpers import create_room, drain_all, setup_valid_game

scenarios("../../features/backend/answer.feature")


def _setup_game_and_play(
    host,
    players,
    room_code,
    rank_points=None,
    lockout_duration=None,
    attempts_limit=None,
):
    """Configure, start, play song. Return shuffled song IDs."""
    shuffled = setup_valid_game(
        host,
        players,
        room_code,
        n_songs=5,
        rank_points=rank_points,
        lockout_duration=lockout_duration,
        attempts_limit=attempts_limit,
    )
    host.send("game:play-song")
    drain_all(host, players)
    return shuffled


def _wrong_id(shuffled, correct=None):
    """Return a song ID from *shuffled* that is not *correct*.

    When *correct* is ``None``, the first element is assumed to be the
    current round's answer (round 1).
    """
    if correct is None and shuffled:
        correct = shuffled[0]
    if shuffled and len(shuffled) > 1:
        return next(s for s in shuffled if s != correct)
    return "wrong"


@when("a player sends game:answer")
def player_sends_answer(ctx, make_player):
    if ctx.host is None:
        host, players, room_code = create_room(make_player, 2)
        shuffled = _setup_game_and_play(host, players, room_code)
        ctx.host = host
        ctx.players = players
        ctx.room_code = room_code
        ctx.shuffled = shuffled
        if shuffled:
            players[0].send("game:answer", {"songId": shuffled[0]})
    else:
        ctx.players[0].send("game:answer", {"songId": "song1"})
    ctx.error_target = ctx.players[0]


@then("the payload contains { songId }")
def payload_has_song_id(ctx):
    # Verify the server consumed the songId field by observing a downstream
    # answer-outcome event (game:scored or game:wrong-answer).  No such event
    # arrives if the server failed to parse the songId.
    player = ctx.players[0]
    events = player.drain_events(wait=1.0)
    outcome = [e for e in events if e["event"] in ("game:scored", "game:wrong-answer")]
    assert outcome, "Server should produce an answer outcome event for game:answer"


@when("a player sends game:answer with an empty songId")
def player_sends_empty_song_id(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    _setup_game_and_play(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.error_target = players[0]
    players[0].send("game:answer", {"songId": ""})


@when("a player sends game:answer with a songId that is not in the game songs")
def player_sends_invalid_song_id(ctx):
    ctx.error_target = ctx.players[0]
    ctx.players[0].send("game:answer", {"songId": "nonexistent_song"})


@given(parsers.parse("a game with rank points [{values}]"))
@given(parsers.parse("a game with rankPoints [{values}]"))
def game_with_rank_points(ctx, make_player, values):
    host, players, room_code = create_room(make_player, 2)
    rank_points = [int(v.strip()) for v in values.split(",")]
    shuffled = _setup_game_and_play(host, players, room_code, rank_points=rank_points)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled
    ctx.rank_points = rank_points


@when("a player sends game:answer with the correct song ID")
def player_answers_correct(ctx):
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})


@then(parsers.parse("the player earns {points:d} points"))
def player_earns_points(ctx, points):
    if points == 0:
        ctx.host.assert_no_event("game:scored", timeout=1.0)
        return
    event = ctx.host.expect_event("game:scored")
    winner = event["payload"]["winner"]
    assert winner["playerId"] == ctx.players[ctx.next_answerer_idx].player_id
    assert ctx.rank_points is not None, "Given step must set ctx.rank_points"
    rank_points = ctx.rank_points
    actual_points = rank_points[winner["rankIndex"]]
    assert actual_points == points, (
        f"Expected {points} points but got {actual_points} "
        f"(rankIndex={winner['rankIndex']}, rankPoints={rank_points})"
    )


@then("the player is recorded as a winner")
def player_recorded_winner(ctx):
    idx = ctx.next_answerer_idx
    player = ctx.players[idx]
    events = player.drain_events(wait=1.0)
    scored = [event for event in events if event["event"] == "game:scored"]
    if scored:
        assert scored[0]["payload"]["winner"]["playerId"] == player.player_id
        return
    reveal = [event for event in events if event["event"] == "game:reveal"]
    assert reveal, "Expected game:scored or game:reveal for the winner"
    winner_ids = [w["playerId"] for w in reveal[0]["payload"]["winners"]]
    assert player.player_id in winner_ids


@then("game:scored { winner } is broadcast to the room")
def scored_broadcast(ctx):
    # Verify that another player in the room (not the answerer) also received
    # the game:scored broadcast containing a winner object.
    other = ctx.players[1]
    event = other.expect_event("game:scored")
    assert "winner" in event["payload"]


@given("one player has already scored")
def one_player_scored(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    shuffled = _setup_game_and_play(host, players, room_code, rank_points=[4, 2, 1])
    players[0].send("game:answer", {"songId": shuffled[0]})
    drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled
    ctx.rank_points = [4, 2, 1]
    ctx.next_answerer_idx = 1


@given("two players have already scored")
def two_players_scored(ctx, make_player):
    host, players, room_code = create_room(make_player, 3)
    shuffled = _setup_game_and_play(host, players, room_code, rank_points=[4, 2, 1])
    for i in range(2):
        players[i].send("game:answer", {"songId": shuffled[0]})
        drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled
    ctx.rank_points = [4, 2, 1]
    ctx.next_answerer_idx = 2


@when("another player sends game:answer with the correct song ID")
def another_player_answers_correct(ctx):
    idx = ctx.next_answerer_idx
    ctx.error_target = ctx.players[idx]
    ctx.players[idx].send("game:answer", {"songId": ctx.shuffled[0]})


@then(parsers.parse("the player earns {points:d} point"))
def player_earns_single_point(ctx, points):
    host = ctx.host
    events = host.drain_events(wait=1.0)
    scored = [e for e in events if e["event"] == "game:scored"]
    reveal = [e for e in events if e["event"] == "game:reveal"]
    rank_points = ctx.rank_points
    if scored:
        rank_index = scored[0]["payload"]["winner"]["rankIndex"]
        assert rank_points[rank_index] == points
    else:
        assert reveal, "No game:scored or game:reveal event received"
        idx = ctx.next_answerer_idx
        player_id = ctx.players[idx].player_id
        winners = reveal[0]["payload"]["winners"]
        player_winner = next(w for w in winners if w["playerId"] == player_id)
        assert rank_points[player_winner["rankIndex"]] == points


@given(parsers.parse("a player with score {score:d}"))
def player_with_score(ctx, make_player, score):
    # Establish cumulative score `score` from round 1 in a 2-round game.
    # Round 2's rank slot 2 yields exactly 2 additional points (matching the
    # Feature scenario "earns 2 points in the current round" → total `score + 2`).
    host, players, room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(
        host, players, room_code, n_songs=2, rank_points=[score, 2]
    )
    host.send("game:play-song")
    drain_all(host, players)
    # Round 1: players[0] scores first → +score.
    players[0].send("game:answer", {"songId": shuffled[0]})
    drain_all(host, players)
    # Close round 1 if not yet revealed, then advance to round 2.
    if host.find_last_event("game:reveal") is None:
        host.send("game:close-answers")
        drain_all(host, players)
    host.send("game:next-round")
    drain_all(host, players)
    host.send("game:play-song")
    drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled
    ctx.rank_points = [score, 2]


@when(parsers.parse("the player earns {points:d} points in the current round"))
def player_earns_in_round(ctx, points):
    # In round 2 with rank_points=[score, 2], players[1] scores first
    # (rankIndex 0 → score points) and players[0] scores second
    # (rankIndex 1 → 2 points, which equals `points` per the Feature).
    assert ctx.rank_points is not None
    assert ctx.rank_points[1] == points, (
        f"Setup mismatch: rank_points[1]={ctx.rank_points[1]} but Feature wants {points}"
    )
    ctx.players[1].send("game:answer", {"songId": ctx.shuffled[1]})
    ctx.host.expect_event("game:scored")
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[1]})
    events = ctx.host.drain_events(wait=1.0)
    outcomes = [
        event for event in events if event["event"] in ("game:scored", "game:reveal")
    ]
    assert outcomes, "Expected scoring or reveal after the second correct answer"


@then(parsers.parse("the player's total score is {total:d}"))
def player_total_score(ctx, total):
    # Use full event history (find_last_event) rather than drain_events: the
    # Given/When steps already drained events, so a fresh drain would return
    # empty and produce a flaky failure.
    state_event = ctx.host.find_last_event("room:state")
    assert state_event is not None, "Expected room:state event in history"
    payload = state_event["payload"]
    all_players = payload["activePlayers"] + payload.get("inactivePlayers", [])
    player = next(pl for pl in all_players if pl["id"] == ctx.players[0].player_id)
    assert player["score"] == total


@when("a player sends game:answer (correct or incorrect)")
def player_sends_any_answer(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    shuffled = _setup_game_and_play(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    players[0].send("game:answer", {"songId": shuffled[0]})


@then("the answer is recorded for that player")
def answer_recorded(ctx):
    events = ctx.players[0].drain_events(wait=1.0)
    recorded = [e for e in events if e["event"] in ("game:scored", "game:wrong-answer")]
    assert len(recorded) > 0, "No answer outcome event received"


@when("a player sends game:answer with an incorrect song ID")
def player_answers_wrong(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    shuffled = _setup_game_and_play(host, players, room_code)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    players[0].send("game:answer", {"songId": _wrong_id(shuffled)})


def player_earns_zero(ctx):
    ctx.host.assert_no_event("game:scored", timeout=1.0)


@then("the player receives game:wrong-answer with { lockoutExpiresAt }")
def player_receives_wrong_answer(ctx):
    event = ctx.players[0].expect_event("game:wrong-answer")
    assert "lockoutExpiresAt" in event["payload"]


def finished_phase_for_answer(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    host.send("game:end")
    drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code


@given("the round has been revealed")
def round_revealed_for_answer(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    shuffled = _setup_game_and_play(host, players, room_code)
    host.send("game:close-answers")
    drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled


@given("a player has already scored in this round")
def player_already_scored(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    shuffled = _setup_game_and_play(host, players, room_code)
    players[0].send("game:answer", {"songId": shuffled[0]})
    drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled


@when("the same player sends game:answer again")
def same_player_answers_again(ctx):
    ctx.error_target = ctx.players[0]
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})


@given(
    parsers.parse("a game with rank points [{values}] and {count:d} or more players")
)
@given(parsers.parse("a game with rankPoints [{values}] and {count:d} or more players"))
def game_with_rank_and_players(ctx, make_player, values, count):
    rank_points = [int(v.strip()) for v in values.split(",")]
    host, players, room_code = create_room(make_player, max(count, 4))
    shuffled = _setup_game_and_play(host, players, room_code, rank_points=rank_points)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled


@given(parsers.parse("{count:d} players have already scored"))
def n_players_scored(ctx, count):
    for i in range(count):
        ctx.players[i].send("game:answer", {"songId": ctx.shuffled[0]})
        drain_all(ctx.host, ctx.players)
    ctx.next_answerer_idx = count


# "another player sends game:answer with the correct song ID" — reuses step above


@then("the server checks game:answer in the following order:")
def answer_check_order(make_player, datatable):
    # Verify each row's error fires in a minimal state.  After each row,
    # also verify the order against the *previous* row by constructing a
    # state where both checks would fail, expecting the earlier row's error.
    rows = [(row[0].strip(), row[1].strip().strip('"')) for row in datatable[1:]]

    # Row 1: Room phase is "playing" — finished phase, valid songId.
    host, players, room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(host, players, room_code)
    host.send("game:end")
    drain_all(host, players)
    players[0].send("game:answer", {"songId": shuffled[0]})
    players[0].expect_error("Game is not in playing phase")
    # Order 1 < 3: finished phase + empty songId → row 1 wins (not row 3).
    players[0].send("game:answer", {"songId": ""})
    players[0].expect_error("Game is not in playing phase")

    # Row 2: Round is not revealed — close answers, then send valid songId.
    host, players, room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(host, players, room_code)
    host.send("game:play-song")
    drain_all(host, players)
    host.send("game:close-answers")
    drain_all(host, players)
    players[0].send("game:answer", {"songId": shuffled[0]})
    players[0].expect_error("Round has been revealed")
    # Order 2 < 3: revealed + empty songId → row 2 wins.
    players[0].send("game:answer", {"songId": ""})
    players[0].expect_error("Round has been revealed")

    # Row 3: Song ID is not empty — playing phase, not revealed, empty songId.
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    players[0].send("game:answer", {"songId": ""})
    players[0].expect_error("Song ID is required")

    # Row 4: Song ID exists in game songs — non-existent songId.
    host, players, room_code = create_room(make_player, 2)
    setup_valid_game(host, players, room_code)
    players[0].send("game:answer", {"songId": "nonexistent"})
    players[0].expect_error("Song not found")

    # Row 5: All scoring slots not full. Fill the current active cap by scoring
    # two players, then disconnect unscored players so disconnection (not answer
    # processing) makes the cap full without auto-revealing.
    host, players, room_code = create_room(make_player, 3)
    shuffled = setup_valid_game(host, players, room_code, rank_points=[4, 2, 1])
    host.send("game:play-song")
    drain_all(host, players)
    players[0].send("game:answer", {"songId": shuffled[0]})
    drain_all(host, players)
    players[1].send("game:answer", {"songId": shuffled[0]})
    drain_all(host, players)
    players[2].disconnect()
    host.disconnect()
    players[0].send("game:answer", {"songId": shuffled[0]})
    players[0].expect_error("All scoring slots are filled")
    # Order 5 < 6: the player has already scored too, so row 5 must still win.

    # Row 6: Player has not scored — slots not full, player already scored.
    host, players, room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(host, players, room_code)
    host.send("game:play-song")
    drain_all(host, players)
    players[0].send("game:answer", {"songId": shuffled[0]})
    drain_all(host, players)
    players[0].send("game:answer", {"songId": shuffled[0]})
    players[0].expect_error("Already scored this round")

    # Row 7: Player has attempts remaining — exhaust attempts.
    host, players, room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(
        host, players, room_code, attempts_limit=2, lockout_duration=0
    )
    host.send("game:play-song")
    drain_all(host, players)
    wrong = next(s for s in shuffled if s != shuffled[0])
    for _ in range(2):
        players[0].send("game:answer", {"songId": wrong})
        players[0].drain_events(wait=0.3)
        host.drain_events(wait=0.2)
    players[0].send("game:answer", {"songId": shuffled[0]})
    players[0].expect_error("No attempts remaining")

    # Row 8: Player is not locked out — lockout active, attempts remaining.
    host, players, room_code = create_room(make_player, 2)
    shuffled = setup_valid_game(
        host, players, room_code, attempts_limit=10, lockout_duration=30
    )
    host.send("game:play-song")
    drain_all(host, players)
    wrong = next(s for s in shuffled if s != shuffled[0])
    players[0].send("game:answer", {"songId": wrong})
    players[0].expect_event("game:wrong-answer")
    players[0].send("game:answer", {"songId": shuffled[0]})
    players[0].expect_error("Locked out")

    assert [r[1] for r in rows] == [
        "Game is not in playing phase",
        "Round has been revealed",
        "Song ID is required",
        "Song not found",
        "All scoring slots are filled",
        "Already scored this round",
        "No attempts remaining",
        "Locked out",
    ], "Feature datatable order changed — update this test accordingly"


@given(parsers.parse("a game with rank points [{values}] and {count:d} players"))
@given(parsers.parse("a game with rankPoints [{values}] and {count:d} players"))
def game_for_auto_reveal(ctx, make_player, values, count):
    rank_points = [int(v.strip()) for v in values.split(",")]
    host, players, room_code = create_room(make_player, count)
    shuffled = _setup_game_and_play(host, players, room_code, rank_points=rank_points)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled
    ctx.answerers = players
    ctx.rank_points = rank_points


@when("the 3rd player sends game:answer with the correct song ID")
def third_player_auto_reveal(ctx):
    ctx.players[2].send("game:answer", {"songId": ctx.shuffled[0]})


@then("the player earns points and is recorded as a winner")
def player_earns_and_recorded(ctx):
    # In the auto-reveal scenario, game:scored is NOT broadcast for the last
    # answer.  Verify via the answering player's game:reveal (not the host's,
    # which is consumed by the later 'game:reveal is broadcast' step).
    player = ctx.players[2]
    event = player.expect_event("game:reveal")
    winners = event["payload"]["winners"]
    player_id = player.player_id
    winner_ids = [w["playerId"] for w in winners]
    assert player_id in winner_ids


@then("game:scored is not broadcast for this answer")
def scored_not_broadcast(ctx):
    # After the auto-reveal trigger, game:scored should NOT be broadcast for the
    # final answer.  Check on players[0] (whose events were drained in the Given
    # step) to avoid consuming the host's game:reveal needed by the next step.
    events = ctx.players[0].drain_events(wait=1.0)
    scored = [e for e in events if e["event"] == "game:scored"]
    assert len(scored) == 0, "Unexpected game:scored broadcast for auto-reveal answer"


@then("all pending answers are cancelled")
def all_pending_answers_cancelled(ctx):
    events = ctx.host.drain_events(wait=0.5)
    scored = [event for event in events if event["event"] == "game:scored"]
    assert not scored, f"Pending answers should not score, got: {scored}"
    reveal = next((event for event in events if event["event"] == "game:reveal"), None)
    if reveal is not None:
        ctx.last_reveal = reveal
    state = next((event for event in events if event["event"] == "room:state"), None)
    if state is not None:
        ctx.last_state = state


@then("game:reveal is broadcast to the room")
def reveal_broadcast_auto(ctx):
    event = getattr(ctx, "last_reveal", None)
    if event is None:
        event = ctx.host.expect_event("game:reveal")
    ctx.last_reveal = None
    assert "songId" in event["payload"]
    assert "winners" in event["payload"]


def _setup_active_answerer_game(ctx, make_player, values, count):
    rank_points = [int(v.strip()) for v in values.split(",")]
    host, players, room_code = create_room(make_player, max(count - 1, 0))
    shuffled = _setup_game_and_play(host, players, room_code, rank_points=rank_points)
    ctx.host = host
    ctx.players = players
    ctx.answerers = [host] + players
    ctx.room_code = room_code
    ctx.shuffled = shuffled
    ctx.rank_points = rank_points
    ctx.scored_player_ids = set()


@given(parsers.parse("a game with rank points [{values}] and {count:d} active players"))
def game_with_rank_and_active_players(ctx, make_player, values, count):
    _setup_active_answerer_game(ctx, make_player, values, count)


@when("both players send game:answer with the correct song ID")
def both_active_players_answer(ctx):
    for answerer in ctx.answerers[:2]:
        answerer.send("game:answer", {"songId": ctx.shuffled[0]})


def _score_answerer(ctx, index):
    answerer = ctx.answerers[index]
    answerer.send("game:answer", {"songId": ctx.shuffled[0]})
    drain_all(ctx.host, ctx.players)
    ctx.scored_player_ids.add(answerer.player_id)


@given(parsers.parse("{count:d} player has scored"))
@given(parsers.parse("{count:d} active player has scored"))
def one_player_has_scored(ctx, count):
    assert count == 1
    _score_answerer(ctx, 0)


@given(parsers.parse("{count:d} players have scored"))
def players_have_scored(ctx, count):
    for index in range(count):
        _score_answerer(ctx, index)


@when(parsers.parse("{count:d} other player disconnects"))
def other_players_disconnect(ctx, count):
    candidates = [
        p
        for p in ctx.answerers
        if p is not ctx.host and p.player_id not in ctx.scored_player_ids
    ]
    for player in candidates[:count]:
        player.disconnect()
        if player in ctx.players:
            ctx.players.remove(player)


@when("the remaining active player sends game:answer with the correct song ID")
def remaining_active_player_answers(ctx):
    remaining = [
        p
        for p in ctx.answerers
        if p.ws is not None and p.player_id not in ctx.scored_player_ids
    ]
    assert remaining, "No remaining unscored active player found"
    remaining[0].send("game:answer", {"songId": ctx.shuffled[0]})


@given(parsers.parse("{count:d} player is in inactivePlayers"))
def player_is_inactive(ctx, count):
    assert count == 1
    player = ctx.answerers[-1]
    player.disconnect()
    if player in ctx.players:
        ctx.players.remove(player)
    ctx.inactive_answerer = player


@when("the inactive player rejoins")
def inactive_player_rejoins(ctx):
    player = ctx.inactive_answerer
    player.reconnect()
    player.join_room(ctx.room_code)
    if player not in ctx.players and player is not ctx.host:
        ctx.players.append(player)
    player.drain_events(wait=0.5)
    ctx.host.drain_events(wait=0.3)


@when("one of the unscored active players sends game:answer with the correct song ID")
def unscored_active_player_answers(ctx):
    for answerer in ctx.answerers:
        if answerer.player_id not in ctx.scored_player_ids:
            answerer.send("game:answer", {"songId": ctx.shuffled[0]})
            return
    raise AssertionError("No unscored active player found")


@when("the remaining active player disconnects")
def remaining_active_player_disconnects(ctx):
    for answerer in ctx.answerers:
        if answerer.player_id not in ctx.scored_player_ids and answerer is not ctx.host:
            answerer.disconnect()
            if answerer in ctx.players:
                ctx.players.remove(answerer)
            return
    raise AssertionError("No remaining active non-host player found")


@given("player A has scored")
def player_a_has_scored(ctx):
    index = 1 if len(ctx.answerers) > 1 else 0
    ctx.player_a = ctx.answerers[index]
    _score_answerer(ctx, index)


@when("player A disconnects")
def player_a_disconnects(ctx):
    ctx.player_a.disconnect()
    if ctx.player_a in ctx.players:
        ctx.players.remove(ctx.player_a)


@then("game:reveal is not broadcast")
def reveal_not_broadcast(ctx):
    ctx.host.assert_no_event("game:reveal", timeout=0.5)


@then(
    parsers.parse(
        "the maximum number of scorers is min(len(rankPoints), activePlayerCount)"
    )
)
def max_scorers(ctx):
    # Given: rankPoints [4, 2, 1] (len=3), host + 2 players = 3 active.
    # Disconnect one player so activePlayerCount (2) < len(rankPoints) (3).
    # Then min(3, 2) = 2: only 2 can score, not 3.
    assert ctx.rank_points is not None
    ctx.players[1].disconnect()
    drain_all(ctx.host, ctx.players[:1])
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})
    ctx.host.expect_event("game:scored")
    ctx.host.send("game:answer", {"songId": ctx.shuffled[0]})
    # With 2 active and min(3,2)=2, this fills all slots → auto-reveal.
    ctx.host.expect_event("game:reveal")


@then("this is recalculated each time an answer is processed")
def recalculated_each_time(ctx):
    # The previous step's auto-reveal payload must list exactly 2 winners
    # (matching the post-disconnect activePlayerCount), not the original 3
    # (matching len(rankPoints)).  This proves the max was recomputed at
    # answer-processing time using the current count, not cached at game start.
    reveal = ctx.host.find_last_event("game:reveal")
    assert reveal is not None, "Expected game:reveal from prior step"
    winners = reveal["payload"]["winners"]
    assert len(winners) == 2, (
        f"Auto-reveal must fire at min(3, 2)=2 winners after disconnect, got {len(winners)}"
    )
    # And no additional game:scored should arrive after the reveal.
    ctx.host.assert_no_event("game:scored", timeout=0.5)


def _make_handicap_game(make_player, handicap_seconds):
    """Create a 3-player game where player has the specified handicap."""
    host, players, room_code = create_room(make_player, 2)
    player, player2 = players
    player.send("room:handicap", {"handicap": handicap_seconds})
    drain_all(host, players)
    shuffled = _setup_game_and_play(host, players, room_code)
    return {
        "host": host,
        "player": player,
        "player2": player2,
        "room_code": room_code,
        "shuffled": shuffled,
    }


@given(
    parsers.parse("a player with handicap {seconds:d} seconds"),
)
def player_with_handicap_seconds(ctx, make_player, seconds):
    result = _make_handicap_game(make_player, seconds)
    ctx.host = result["host"]
    ctx.players = [result["player"], result["player2"]]
    ctx.room_code = result["room_code"]
    ctx.shuffled = result["shuffled"]
    ctx.handicap = seconds


@when("the player sends game:answer")
def handicap_player_answers(ctx):
    ctx.error_target = ctx.players[0]
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})


@then(parsers.parse("the answer is processed after a {ms:d}ms delay"))
def answer_processed_with_delay(ctx, ms):
    # Verify the delay actually happens: no outcome should arrive within
    # the first half of the handicap window.  Without this, a 0-delay
    # (immediate) implementation would also satisfy the post-delay check.
    half_window = max(ms / 1000.0 / 2, 0.1)
    ctx.host.assert_no_event("game:scored", timeout=half_window)
    time.sleep(ms / 1000.0 - half_window + 0.5)
    events = ctx.host.drain_events(wait=1.0)
    scored = [e for e in events if e["event"] == "game:scored"]
    reveal = [e for e in events if e["event"] == "game:reveal"]
    assert len(scored) > 0 or len(reveal) > 0


@given(
    parsers.parse(
        "player A with handicap {ha:d} seconds and player B with handicap {hb:d} seconds"
    ),
)
def two_players_with_handicaps(ctx, make_player, ha, hb):
    host, players, room_code = create_room(make_player, 2)
    player_a, player_b = players
    player_a.send("room:handicap", {"handicap": ha})
    drain_all(host, players)
    player_b.send("room:handicap", {"handicap": hb})
    drain_all(host, players)
    shuffled = _setup_game_and_play(host, players, room_code)
    ctx.host = host
    ctx.players = [player_a, player_b]
    ctx.room_code = room_code
    ctx.shuffled = shuffled


@when("both players send game:answer with the correct song ID at the same time")
def both_players_answer(ctx):
    song_id = ctx.shuffled[0]
    ctx.players[0].send("game:answer", {"songId": song_id})
    ctx.players[1].send("game:answer", {"songId": song_id})


@when("player A sends game:answer with the correct song ID")
def player_a_answers_correct(ctx):
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})


@when("player B sends game:answer with the correct song ID at the same time")
def player_b_answers_correct(ctx):
    ctx.players[1].send("game:answer", {"songId": ctx.shuffled[0]})


@then("player A's answer is processed immediately")
def player_a_processed(ctx):
    # Player A has handicap 0, so game:scored should arrive promptly.
    event = ctx.host.expect_event("game:scored", timeout=2.0)
    assert event["payload"]["winner"]["playerId"] == ctx.players[0].player_id


@then(parsers.parse("player B's answer is processed after {ms:d}ms"))
def player_b_delayed(ctx, ms):
    time.sleep(ms / 1000.0 + 0.5)
    ctx.host.drain_events(wait=1.0)


@then("player A earns a higher scoring slot than player B")
def player_a_higher_slot(ctx):
    scored = ctx.host.find_all_events("game:scored")
    assert len(scored) >= 2, (
        f"Both players answered correctly; expected at least 2 game:scored "
        f"events, got {len(scored)}"
    )
    assert (
        scored[0]["payload"]["winner"]["rankIndex"]
        < scored[1]["payload"]["winner"]["rankIndex"]
    )


@given(
    "a player has a pending answer due to handicap delay",
)
def player_has_pending(ctx, make_player):
    result = _make_handicap_game(make_player, 30)
    ctx.host = result["host"]
    ctx.players = [result["player"], result["player2"]]
    ctx.room_code = result["room_code"]
    ctx.shuffled = result["shuffled"]
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})


@when("the same player sends a new game:answer")
def player_sends_new_answer(ctx):
    ctx.players[0].send("game:answer", {"songId": _wrong_id(ctx.shuffled)})


@then("the previous pending answer is cancelled")
def previous_cancelled(ctx):
    # With a 30s handicap, neither the old nor the new answer should have been
    # processed yet.  Verify no game:scored has arrived (the old answer was not
    # processed before being replaced).
    ctx.host.assert_no_event("game:scored", timeout=1.0)


@then("the new answer starts its own delay")
def new_answer_delayed(ctx):
    # The new answer also has a 30s handicap delay, so no scored/wrong-answer
    # event should have arrived yet — it is still pending.
    ctx.players[0].assert_no_event("game:scored", timeout=1.0)
    ctx.players[0].assert_no_event("game:wrong-answer", timeout=0.5)


@given(
    "a player's answer is pending due to handicap",
)
def answer_pending_handicap(ctx, make_player):
    result = _make_handicap_game(make_player, 30)
    ctx.host = result["host"]
    ctx.players = [result["player"], result["player2"]]
    ctx.room_code = result["room_code"]
    ctx.shuffled = result["shuffled"]
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})


@when("the handicap delay expires but the round number has changed")
def delay_expires_round_changed(ctx):
    host = ctx.host
    players = ctx.players
    host.send("game:close-answers")
    drain_all(host, players)
    host.send("game:next-round")
    drain_all(host, players)


@then("the pending answer is discarded")
def pending_discarded(ctx):
    # The round changed while the answer was pending, so it should have been
    # silently discarded — no game:scored for the old answer.
    ctx.host.assert_no_event("game:scored", timeout=1.0)


@when("the host sends game:close-answers")
def host_closes_with_pending(ctx):
    ctx.host.send("game:close-answers")


@then("the pending answer is cancelled")
def pending_cancelled(ctx):
    # The host closed answers, so the pending handicap answer should be
    # cancelled.  Verify the player does not receive game:scored.
    ctx.players[0].assert_no_event("game:scored", timeout=1.0)


@given(parsers.parse("a game with lockout duration {duration:d}"))
@given(parsers.parse("a game with lockoutDuration {duration:d}"))
def game_with_lockout(ctx, make_player, duration):
    host, players, room_code = create_room(make_player, 2)
    shuffled = _setup_game_and_play(host, players, room_code, lockout_duration=duration)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled


@when("a player sends game:answer with a wrong answer")
def player_answers_wrong_lockout(ctx):
    ctx.players[0].send("game:answer", {"songId": _wrong_id(ctx.shuffled)})


@then(parsers.parse("the player is locked out for {seconds:d} seconds"))
def player_locked_out(ctx, seconds):
    event = ctx.players[0].expect_event("game:wrong-answer")
    assert event["payload"]["lockoutExpiresAt"] is not None


@then("game:wrong-answer includes { lockoutExpiresAt }")
def wrong_answer_has_lockout(ctx):
    # The game:wrong-answer event was already consumed by the prior step.
    # Re-examine it from the full event history.
    event = ctx.players[0].find_last_event("game:wrong-answer")
    assert event is not None, "game:wrong-answer not found in event history"
    assert "lockoutExpiresAt" in event["payload"]


@given("a player is locked out")
def player_is_locked_out(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    shuffled = _setup_game_and_play(host, players, room_code, lockout_duration=5)
    players[0].send("game:answer", {"songId": _wrong_id(shuffled)})
    players[0].expect_event("game:wrong-answer")
    host.drain_events(wait=0.3)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled


# "the player sends game:answer" — reuses handicap_player_answers


@given(
    parsers.parse("a player was locked out for {seconds:d} seconds"),
)
def player_was_locked_out(ctx, make_player, seconds):
    host, players, room_code = create_room(make_player, 2)
    shuffled = _setup_game_and_play(host, players, room_code, lockout_duration=seconds)
    players[0].send("game:answer", {"songId": _wrong_id(shuffled)})
    players[0].expect_event("game:wrong-answer")
    drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled


@when(parsers.parse("{seconds:d} seconds have elapsed"))
def wait_seconds(seconds):
    time.sleep(seconds + 0.5)


@then("the player can submit an answer")
def player_can_answer(ctx):
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})
    events = ctx.players[0].drain_events(wait=1.0)
    lockout_errors = [
        e
        for e in events
        if e["event"] == "error" and e["payload"]["message"] == "Locked out"
    ]
    assert len(lockout_errors) == 0


@given(parsers.parse("a game with attempts limit {limit:d}"))
@given(parsers.parse("a game with attemptsLimit {limit:d}"))
def game_with_attempts_limit(ctx, make_player, limit):
    host, players, room_code = create_room(make_player, 2)
    shuffled = _setup_game_and_play(
        host, players, room_code, attempts_limit=limit, lockout_duration=0
    )
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled


@when(parsers.parse("a player sends game:answer with {count:d} wrong answers"))
def player_sends_wrong_answers(ctx, count):
    wid = _wrong_id(ctx.shuffled)
    for _ in range(count):
        ctx.players[0].send("game:answer", {"songId": wid})
        ctx.players[0].drain_events(wait=0.5)


@then("the player receives game:wrong-answer")
def player_gets_wrong(ctx):
    events = ctx.players[0].find_all_events("game:wrong-answer")
    assert len(events) > 0, "Player did not receive game:wrong-answer"


@given(parsers.parse("a player has submitted {count:d} wrong answers"))
def player_submitted_wrong(ctx, count):
    wid = _wrong_id(ctx.shuffled)
    for _ in range(count):
        ctx.players[0].send("game:answer", {"songId": wid})
        ctx.players[0].drain_events(wait=0.5)
        ctx.host.drain_events(wait=0.3)


# "the player sends game:answer" — reuses handicap_player_answers via ctx


@given("a player has exceeded the attempts limit and is also locked out")
@given("a player has exceeded attemptsLimit and is also locked out")
def player_exhausted_and_locked(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    player, player2 = players
    shuffled = _setup_game_and_play(
        host, players, room_code, attempts_limit=1, lockout_duration=30
    )
    wid = _wrong_id(shuffled)
    player.send("game:answer", {"songId": wid})
    player.drain_events(wait=0.5)
    drain_all(host, [player2])
    ctx.host = host
    ctx.players = [player, player2]
    ctx.room_code = room_code
    ctx.shuffled = shuffled


@then('the error is "No attempts remaining" not "Locked out"')
def error_is_no_attempts(ctx):
    ctx.players[0].expect_error("No attempts remaining")


@given("a player used all attempts in the previous round")
def player_used_all_attempts(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    player, player2 = players
    shuffled = _setup_game_and_play(
        host, players, room_code, attempts_limit=3, lockout_duration=0
    )
    wid = _wrong_id(shuffled)
    for _ in range(3):
        player.send("game:answer", {"songId": wid})
        player.drain_events(wait=0.5)
        drain_all(host, [player2])
    # Close and advance to next round
    host.send("game:close-answers")
    drain_all(host, players)
    host.send("game:next-round")
    drain_all(host, players)
    host.send("game:play-song")
    drain_all(host, players)
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled
    ctx.current_round = 2


@when("a new round begins")
def new_round_for_penalty(ctx):
    assert ctx.current_round == 2


@then("the player can answer again with full attempts")
def player_can_answer_again(ctx):
    shuffled = ctx.shuffled
    player = ctx.players[0]
    if shuffled and len(shuffled) > 1:
        wid = _wrong_id(shuffled, correct=shuffled[ctx.current_round - 1])
        player.send("game:answer", {"songId": wid})
        events = player.drain_events(wait=1.0)
        no_attempts = [
            e
            for e in events
            if e["event"] == "error"
            and e["payload"]["message"] == "No attempts remaining"
        ]
        assert len(no_attempts) == 0


@then("the player is not locked out")
def player_not_locked_out(ctx):
    event = ctx.players[0].expect_event("game:wrong-answer")
    assert event["payload"]["lockoutExpiresAt"] is None


@then("game:wrong-answer includes lockoutExpiresAt: null")
def wrong_answer_null_lockout(ctx):
    # The prior step already consumed the event.  Re-examine from event history.
    event = ctx.players[0].find_last_event("game:wrong-answer")
    assert event is not None, "game:wrong-answer not found in event history"
    assert event["payload"]["lockoutExpiresAt"] is None


@then("the player can immediately submit another answer")
def player_can_answer_immediately(ctx):
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})
    events = ctx.players[0].drain_events(wait=1.0)
    lockout_errors = [
        e
        for e in events
        if e["event"] == "error" and e["payload"]["message"] == "Locked out"
    ]
    assert len(lockout_errors) == 0


@when(parsers.parse("a player sends game:answer {count:d} times with wrong answers"))
def player_sends_many_wrong(ctx, count):
    wid = _wrong_id(ctx.shuffled)
    for _ in range(count):
        ctx.players[0].send("game:answer", {"songId": wid})
        ctx.players[0].drain_events(wait=0.5)
        ctx.host.drain_events(wait=0.3)


@then("the player can still submit another answer")
def player_can_still_answer(ctx):
    wid = _wrong_id(ctx.shuffled)
    ctx.players[0].send("game:answer", {"songId": wid})
    events = ctx.players[0].drain_events(wait=1.0)
    no_attempts = [
        e
        for e in events
        if e["event"] == "error" and e["payload"]["message"] == "No attempts remaining"
    ]
    assert len(no_attempts) == 0


@given(
    "a round is in progress and no song has been played yet",
)
def round_no_play(ctx, make_player):
    host, players, room_code = create_room(make_player, 2)
    songs = [
        {
            "id": f"song{i}",
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "artworkUrl": None,
        }
        for i in range(1, 4)
    ]
    host.send(
        "room:settings",
        {
            "songs": songs,
            "totalRounds": 3,
            "playbackDurations": [1, 2, 4, 8, 16],
            "rankPoints": [4, 2, 1],
            "lockoutDuration": 5,
            "attemptsLimit": 3,
        },
    )
    drain_all(host, players)
    host.send("game:start")
    drain_all(host, players)
    from backend.schemas import ShuffledSongsPayload

    shuffled = None
    event = host.find_event("game:shuffled-songs")
    if event is not None:
        parsed = ShuffledSongsPayload.model_validate(event["payload"])
        shuffled = parsed.shuffledSongIds
    # Do NOT play song
    ctx.host = host
    ctx.players = players
    ctx.room_code = room_code
    ctx.shuffled = shuffled


# "a player sends game:answer" reuses handicap_player_answers


@then("the answer is processed normally")
def answer_processed_normally(ctx):
    player = ctx.players[0]
    events = player.drain_events(wait=1.0)
    play_errors = [
        e
        for e in events
        if e["event"] == "error"
        and "not been played" in e.get("payload", {}).get("message", "")
    ]
    assert len(play_errors) == 0


@given(
    parsers.parse("a player with handicap {seconds:d} seconds sends game:answer"),
)
def handicap_player_sends_answer(ctx, make_player, seconds):
    result = _make_handicap_game(make_player, seconds)
    ctx.host = result["host"]
    ctx.players = [result["player"], result["player2"]]
    ctx.room_code = result["room_code"]
    ctx.shuffled = result["shuffled"]
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})
    # Host closes answers while the handicap delay is pending, revealing
    # the round. When the delay expires, "round is not revealed" re-check
    # fails and the answer is silently discarded.
    ctx.host.send("game:close-answers")
    ctx.host.expect_event("game:reveal")


@when("the handicap delay expires")
def handicap_delay_expires(ctx):
    time.sleep(11)


@then("the server re-checks the answer rejection checks before processing")
def server_rechecks(ctx):
    # The round was revealed during the handicap delay (host closed answers).
    # Verify the round IS revealed, which means the re-check will fail.
    reveal_events = ctx.host.find_all_events("game:reveal")
    assert len(reveal_events) > 0, "Round should have been revealed during delay"


@then(
    "if any rejection check would fail under the current state, the answer "
    "is silently discarded with no notification to the player"
)
@then(
    "if any check fails, the answer is silently discarded with no "
    "notification to the player"
)
def answer_silently_discarded(ctx):
    # No game:scored or game:wrong-answer should arrive for the discarded answer.
    ctx.players[0].assert_no_event("game:scored", timeout=2.0)
    ctx.players[0].assert_no_event("game:wrong-answer", timeout=0.5)


@given(
    "a player with handicap has a pending answer with the correct song ID",
)
@given(
    "a player with handicap sends game:answer with the correct song ID",
)
def handicap_player_correct_answer(ctx, make_player):
    result = _make_handicap_game(make_player, 3)
    ctx.host = result["host"]
    ctx.players = [result["player"], result["player2"]]
    ctx.room_code = result["room_code"]
    ctx.shuffled = result["shuffled"]
    ctx.players[0].send("game:answer", {"songId": ctx.shuffled[0]})


@when("the player disconnects before the handicap delay expires")
def player_disconnects_before_delay(ctx):
    ctx.players[0].disconnect()


@when("the delay expires")
def delay_expires():
    time.sleep(4)


@then("the answer is processed and the player earns points")
def disconn_player_earns(ctx):
    events = ctx.host.drain_events(wait=1.0)
    scored = [e for e in events if e["event"] == "game:scored"]
    reveal = [e for e in events if e["event"] == "game:reveal"]
    assert len(scored) > 0 or len(reveal) > 0
