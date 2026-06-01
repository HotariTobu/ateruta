"""Step definitions for api.feature — API type and payload structure verification.

These tests verify that the Feature file datatables match the Pydantic models
in schemas.py. Runtime payload validation happens in PlayerClient.
"""

from __future__ import annotations

import re
import types
from dataclasses import dataclass, field
from typing import Annotated, Literal, get_args, get_origin

import pytest
from pydantic import AwareDatetime, BaseModel, ValidationError
from pydantic.fields import FieldInfo
from pytest_bdd import parsers, scenarios, then

from backend.schemas import (
    SC_EVENT_SCHEMAS,
    SESSION_COOKIE,
    WS_ENDPOINT,
    ErrorPayload,
    ErrorResponse,
    GameAnswerPayload,
    GetRoomResponse200,
    GetSessionResponse200,
    GetTokenResponse200,
    PlayerStatePayload,
    PostRoomResponse201,
    RestoreRevealPayload,
    RevealPayload,
    RoomClosedPayload,
    RoomHandicapPayload,
    RoomJoinPayload,
    RoomNicknamePayload,
    RoomSettingsCSPayload,
    RoomSettingsSCPayload,
    RoomState,
    ScoredPayload,
    ShuffledSongsPayload,
    Song,
    WrongAnswerPayload,
    WSEnvelope,
    Winner,
)

scenarios("../../features/backend/api.feature")


@dataclass
class FeatureType:
    """Parsed representation of a Feature file type notation."""

    base: str  # "string", "number", "boolean", "true", "object", or model name
    nullable: bool = False
    optional: bool = False  # | undefined → field may be absent (has default)
    array: bool = False
    annotation: str | None = None  # "(seconds)", "(0-indexed)", "(ISO 8601 with TZ)"
    literals: list[str] = field(default_factory=list)  # ["playing", "finished"]
    inline_fields: dict[str, str] = field(
        default_factory=dict
    )  # {field_name: type_str}


def _parse_feature_type(type_str: str) -> FeatureType:
    """Parse a Feature file type notation into a structured descriptor."""
    s = type_str.strip()

    if s.startswith('"'):
        literals = re.findall(r'"([^"]+)"', s)
        return FeatureType(base="literal", literals=literals)

    if s.startswith("{"):
        match = re.match(r"\{([^}]+)\}(\[\])?", s)
        assert match, f"Invalid inline object type: {s}"
        fields_str = match.group(1)
        is_array = match.group(2) == "[]"
        inline_fields: dict[str, str] = {}
        for pair in fields_str.split(","):
            pair = pair.strip()
            key, _, val = pair.partition(":")
            inline_fields[key.strip()] = val.strip()
        return FeatureType(
            base="inline_object", array=is_array, inline_fields=inline_fields
        )

    nullable = False
    optional = False
    if " | null" in s:
        nullable = True
        s = s.replace(" | null", "")
    elif " | undefined" in s:
        nullable = True
        optional = True
        s = s.replace(" | undefined", "")

    array = False
    if "[]" in s:
        array = True
        s = s.replace("[]", "")

    annotation = None
    ann_match = re.search(r"\(([^)]+)\)", s)
    if ann_match:
        annotation = ann_match.group(1)
        s = s[: ann_match.start()].strip()

    return FeatureType(
        base=s.strip(),
        nullable=nullable,
        optional=optional,
        array=array,
        annotation=annotation,
    )


_NAMED_MODELS: dict[str, type[BaseModel]] = {
    "Song": Song,
    "Winner": Winner,
}


def _unwrap_annotated(tp: type) -> tuple[type, list[object]]:
    """Unwrap Annotated[X, ...] → (X, [metadata...]).  Returns (tp, []) if not Annotated."""
    if get_origin(tp) is Annotated:
        args = get_args(tp)
        return args[0], list(args[1:])
    return tp, []


def _flatten_metadata(metadata: list[object]) -> list[object]:
    flattened: list[object] = []
    for item in metadata:
        flattened.append(item)
        if isinstance(item, FieldInfo):
            flattened.extend(item.metadata)
    return flattened


def _is_union_with_none(tp: type) -> tuple[bool, type | None]:
    """Check if tp is X | None.  Returns (True, X) or (False, None)."""
    if get_origin(tp) is types.UnionType:
        args = get_args(tp)
        non_none = [a for a in args if a is not type(None)]
        if type(None) in args and len(non_none) == 1:
            return True, non_none[0]
    return False, None


def _has_ge_constraint(metadata: list[object], value: int = 0) -> bool:
    """Check if metadata contains a ge constraint with the given value."""
    for item in metadata:
        if hasattr(item, "ge") and item.ge == value:
            return True
    return False


def _assert_type_matches(
    feature_type_str: str,
    model: type[BaseModel],
    field_name: str,
    *,
    allow_optional_model_field: bool = False,
) -> None:
    """Assert that a Feature type notation matches the Pydantic field type."""
    ft = _parse_feature_type(feature_type_str)
    field_info: FieldInfo = model.model_fields[field_name]
    python_type = field_info.annotation
    assert python_type is not None, f"{model.__name__}.{field_name} has no annotation"

    python_type, top_metadata = _unwrap_annotated(python_type)
    top_metadata = _flatten_metadata([*top_metadata, *field_info.metadata])

    if not ft.nullable and allow_optional_model_field:
        is_nullable, inner = _is_union_with_none(python_type)
        if is_nullable:
            assert field_info.default is None, (
                f"{model.__name__}.{field_name}: optional payload field must "
                f"default to None, got {field_info.default!r}"
            )
            assert inner is not None
            python_type = inner
            python_type, top_metadata = _unwrap_annotated(python_type)
            top_metadata = _flatten_metadata(top_metadata)

    if ft.nullable:
        is_nullable, inner = _is_union_with_none(python_type)
        assert is_nullable, (
            f"{model.__name__}.{field_name}: expected nullable type, got {python_type}"
        )
        assert inner is not None
        python_type = inner
        python_type, top_metadata = _unwrap_annotated(python_type)
        top_metadata = _flatten_metadata(top_metadata)

        if ft.optional:
            assert field_info.default is None, (
                f"{model.__name__}.{field_name}: '| undefined' requires default=None, "
                f"got default={field_info.default!r}"
            )
        else:
            assert field_info.is_required(), (
                f"{model.__name__}.{field_name}: '| null' should be required (no default)"
            )

    if ft.array:
        assert get_origin(python_type) is list, (
            f"{model.__name__}.{field_name}: expected list, got {python_type}"
        )
        (elem_type,) = get_args(python_type)
        elem_type, elem_metadata = _unwrap_annotated(elem_type)
        elem_metadata = _flatten_metadata(elem_metadata)
    else:
        elem_type = python_type
        elem_metadata = top_metadata

    _assert_base_type(ft, elem_type, elem_metadata, model, field_name)


def _assert_base_type(
    ft: FeatureType,
    python_type: type,
    metadata: list[object],
    model: type[BaseModel],
    field_name: str,
) -> None:
    """Assert the base type and constraints match."""
    prefix = f"{model.__name__}.{field_name}"

    if ft.base == "literal":
        assert get_origin(python_type) is Literal, (
            f"{prefix}: expected Literal, got {python_type}"
        )
        actual_literals = set(get_args(python_type))
        expected_literals = set(ft.literals)
        assert actual_literals == expected_literals, (
            f"{prefix}: Literal values mismatch: "
            f"expected {expected_literals}, got {actual_literals}"
        )
        return

    if ft.base == "inline_object":
        assert isinstance(python_type, type) and issubclass(python_type, BaseModel), (
            f"{prefix}: expected BaseModel subclass for inline object, got {python_type}"
        )
        for sub_field, sub_type_str in ft.inline_fields.items():
            assert sub_field in python_type.model_fields, (
                f"{prefix}: inline object missing field '{sub_field}'"
            )
            _assert_type_matches(sub_type_str, python_type, sub_field)
        assert set(ft.inline_fields.keys()) == set(python_type.model_fields.keys()), (
            f"{prefix}: inline object field mismatch: "
            f"expected {sorted(ft.inline_fields.keys())}, "
            f"got {sorted(python_type.model_fields.keys())}"
        )
        return

    if ft.base == "string":
        if ft.annotation == "ISO 8601 with TZ":
            assert python_type is AwareDatetime, (
                f"{prefix}: expected AwareDatetime for '(ISO 8601 with TZ)', "
                f"got {python_type}"
            )
        else:
            assert python_type is str, f"{prefix}: expected str, got {python_type}"
        return

    if ft.base == "number":
        assert python_type in (int, float), (
            f"{prefix}: expected int or float, got {python_type}"
        )
        if ft.annotation in ("seconds", "0-indexed"):
            assert _has_ge_constraint(metadata), (
                f"{prefix}: expected ge=0 constraint for '({ft.annotation})'"
            )
        return

    if ft.base == "boolean":
        assert python_type is bool, f"{prefix}: expected bool, got {python_type}"
        return

    if ft.base == "true":
        assert get_origin(python_type) is Literal, (
            f"{prefix}: expected Literal[True] for 'true', got {python_type}"
        )
        assert get_args(python_type) == (True,), (
            f"{prefix}: expected Literal[True], got Literal{get_args(python_type)}"
        )
        return

    if ft.base == "object":
        assert python_type is object, f"{prefix}: expected object, got {python_type}"
        return

    expected_model = _NAMED_MODELS.get(ft.base)
    assert expected_model is not None, f"{prefix}: unknown model name '{ft.base}'"
    assert python_type is expected_model, (
        f"{prefix}: expected {expected_model.__name__}, got {python_type}"
    )


def _parse_datatable(datatable: list[list[str]]) -> dict[str, str]:
    """Parse a datatable (with header row) into {field: type_str}."""
    rows = datatable[1:]
    return {row[0]: row[1] for row in rows}


def _model_field_names(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields.keys())


def _assert_fields_match(datatable: list[list[str]], model: type[BaseModel]) -> None:
    """Assert that the datatable field names and types match the model."""
    dt_fields = _parse_datatable(datatable)
    model_fields = _model_field_names(model)
    assert set(dt_fields.keys()) == model_fields, (
        f"Field mismatch: datatable={sorted(dt_fields.keys())}, "
        f"model={sorted(model_fields)}"
    )
    for field_name, type_str in dt_fields.items():
        _assert_type_matches(type_str, model, field_name)


def _assert_fields_subset(datatable: list[list[str]], model: type[BaseModel]) -> None:
    """Assert datatable fields are a subset of model fields, with type checks."""
    dt_fields = _parse_datatable(datatable)
    model_fields = _model_field_names(model)
    assert set(dt_fields.keys()) <= model_fields, (
        f"Datatable has fields not in model: {set(dt_fields.keys()) - model_fields}"
    )
    for field_name, type_str in dt_fields.items():
        _assert_type_matches(
            type_str,
            model,
            field_name,
            allow_optional_model_field=True,
        )


def _normalize_scenario_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower().replace("→", ""))


def _model_for_scenario(
    scenario_name: str,
    models: dict[str, type[BaseModel] | None],
    registry_name: str,
) -> type[BaseModel] | None:
    normalized_name = _normalize_scenario_key(scenario_name)
    matches = [
        (key, model)
        for key, model in models.items()
        if _normalize_scenario_key(key) in normalized_name
    ]
    assert len(matches) == 1, (
        f"Expected exactly one {registry_name} model for scenario "
        f"'{scenario_name}', got {[key for key, _ in matches]}"
    )
    return matches[0][1]


@then("a Song has the following fields:")
def song_type(datatable):
    _assert_fields_match(datatable, Song)


@then("a Winner has the following fields:")
def winner_type(datatable):
    _assert_fields_match(datatable, Winner)


@then("the WebSocket endpoint is /ws")
def ws_endpoint():
    assert WS_ENDPOINT == "/ws"


@then("the connection uses the ateruta-player-id cookie for session identification")
def ws_cookie_session():
    assert SESSION_COOKIE == "ateruta-player-id"


@then("the following custom close codes are used:")
def custom_close_codes(datatable):
    rows = datatable[1:]
    codes = {int(row[0]): row[1] for row in rows}
    assert codes == {
        4401: "Unauthorized",
        4409: "Connected from another location",
    }


@then("all WebSocket messages use JSON with the following structure:")
def ws_message_structure(datatable):
    _assert_fields_match(datatable, WSEnvelope)


@then('the event field is the event name (e.g. "room:join", "game:answer")')
def event_field_description():
    assert "event" in WSEnvelope.model_fields


@then("the payload field contains the event-specific data")
def payload_field_description():
    assert "payload" in WSEnvelope.model_fields


_HTTP_RESPONSE_MODELS: dict[str, dict[int, type[BaseModel]]] = {
    "POST /api/room": {
        201: PostRoomResponse201,
        401: ErrorResponse,
        500: ErrorResponse,
    },
    "GET /api/room/{code}": {
        200: GetRoomResponse200,
        400: ErrorResponse,
        401: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
    "GET /api/session": {
        200: GetSessionResponse200,
    },
    "GET /api/token": {
        200: GetTokenResponse200,
        500: ErrorResponse,
    },
}


@then(parsers.parse("{status:d} response has the following fields:"))
def http_response_fields(status, datatable, request):
    scenario_name = request.node.name
    for endpoint, status_map in _HTTP_RESPONSE_MODELS.items():
        if (
            _normalize_scenario_key(endpoint) in _normalize_scenario_key(scenario_name)
            and status in status_map
        ):
            _assert_fields_match(datatable, status_map[status])
            return
    raise AssertionError(
        f"No HTTP response model registered for scenario '{scenario_name}' "
        f"at status {status}.  Add the (endpoint, status) entry to "
        f"_HTTP_RESPONSE_MODELS."
    )


_PAYLOAD_MODELS: dict[str, type[BaseModel] | None] = {
    "room:join payload": RoomJoinPayload,
    "room:leave payload": None,
    "room:nickname payload": RoomNicknamePayload,
    "room:handicap payload": RoomHandicapPayload,
    "room:settings payload (C→S)": RoomSettingsCSPayload,
    "game:start payload": None,
    "game:play-song payload (C→S)": None,
    "game:answer payload": GameAnswerPayload,
    "game:extend payload (C→S)": None,
    "game:close-answers payload": None,
    "game:next-round payload": None,
    "game:end payload": None,
    "game:back-to-lobby payload": None,
    "room:settings payload (S→C)": RoomSettingsSCPayload,
    "error event payload": ErrorPayload,
    "game:shuffled-songs payload": ShuffledSongsPayload,
    "game:play-song payload (S→C)": None,
    "game:scored payload": ScoredPayload,
    "game:wrong-answer payload": WrongAnswerPayload,
    "game:reveal payload": RevealPayload,
    "game:player-state payload": PlayerStatePayload,
    "game:restore-reveal payload": RestoreRevealPayload,
    "room:closed payload": RoomClosedPayload,
}


@then("the payload has the following fields:")
def payload_has_fields(datatable, request):
    model = _model_for_scenario(request.node.name, _PAYLOAD_MODELS, "payload")
    assert model is not None, f"Scenario '{request.node.name}' expects an empty payload"
    _assert_fields_match(datatable, model)


@then("the payload is empty")
def payload_is_empty(request):
    model = _model_for_scenario(request.node.name, _PAYLOAD_MODELS, "payload")
    assert model is None, f"Scenario '{request.node.name}' must use an empty payload"


@then("the payload is a partial object with optional fields:")
def payload_partial_fields(datatable, request):
    model = _model_for_scenario(
        request.node.name,
        {"room:settings payload (C→S)": RoomSettingsCSPayload},
        "partial-payload",
    )
    assert model is not None
    _assert_fields_subset(datatable, model)


@then("the payload is RoomState | null")
def payload_roomstate_or_null():
    assert SC_EVENT_SCHEMAS.get("room:state") is RoomState


@then("RoomState has the following fields:")
def roomstate_fields(datatable):
    _assert_fields_match(datatable, RoomState)


@then('the event name is "error"')
def event_name_is_error():
    assert "error" in SC_EVENT_SCHEMAS


@then("scored is true if and only if scoredRankIndex is not null")
def scored_iff_rank_not_null():
    PlayerStatePayload(
        scored=True,
        scoredRankIndex=0,
        wrongAnswerCount=0,
        lockoutExpiresAt=None,
        pendingSongId=None,
        pendingExpiresAt=None,
    )
    PlayerStatePayload(
        scored=False,
        scoredRankIndex=None,
        wrongAnswerCount=0,
        lockoutExpiresAt=None,
        pendingSongId=None,
        pendingExpiresAt=None,
    )
    with pytest.raises(ValidationError):
        PlayerStatePayload(
            scored=True,
            scoredRankIndex=None,
            wrongAnswerCount=0,
            lockoutExpiresAt=None,
            pendingSongId=None,
            pendingExpiresAt=None,
        )
    with pytest.raises(ValidationError):
        PlayerStatePayload(
            scored=False,
            scoredRankIndex=0,
            wrongAnswerCount=0,
            lockoutExpiresAt=None,
            pendingSongId=None,
            pendingExpiresAt=None,
        )
