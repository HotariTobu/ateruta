"""Pydantic models mirroring the type definitions in api.feature.

api.feature step definitions verify that these models match the Feature file
datatables. Behavioral tests validate actual server payloads against these
models at the PlayerClient infrastructure level.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

WS_ENDPOINT = "/ws"
SESSION_COOKIE = "ateruta-player-id"

Seconds = Annotated[float, Field(ge=0)]
ZeroIndexed = Annotated[int, Field(ge=0)]


class Song(BaseModel):
    id: str
    title: str
    artist: str
    artworkUrl: str | None


class Winner(BaseModel):
    playerId: str
    rankIndex: ZeroIndexed


class WSEnvelope(BaseModel):
    event: str
    payload: object


class PostRoomResponse201(BaseModel):
    code: str


class ErrorResponse(BaseModel):
    error: str


class GetRoomResponse200(BaseModel):
    exists: Literal[True]


class GetSessionResponse200(BaseModel):
    ready: Literal[True]


class GetTokenResponse200(BaseModel):
    token: str
    expiresAt: AwareDatetime


class RoomJoinPayload(BaseModel):
    code: str


class RoomNicknamePayload(BaseModel):
    nickname: str


class RoomHandicapPayload(BaseModel):
    handicap: Seconds


class RoomSettingsCSPayload(BaseModel):
    songs: list[Song] | None = None
    totalRounds: int | None = None
    playbackDurations: list[Seconds] | None = None
    rankPoints: list[int] | None = None
    lockoutDuration: float | None = None
    attemptsLimit: int | None = None


class GameAnswerPayload(BaseModel):
    songId: str


class EmptyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Empty payloads: room:leave, game:start, game:play-song (C→S),
# game:extend, game:close-answers, game:next-round, game:end,
# game:back-to-lobby


class PlayerInSettings(BaseModel):
    id: str
    nickname: str
    handicap: Seconds


class RoomSettingsSCPayload(BaseModel):
    hostPlayerId: str
    songs: list[Song]
    totalRounds: int | None
    playbackDurations: list[Seconds]
    rankPoints: list[int]
    lockoutDuration: float | None
    attemptsLimit: int | None
    activePlayers: list[PlayerInSettings]
    inactivePlayers: list[PlayerInSettings]


class PlayerInState(BaseModel):
    id: str
    score: int


class RoomState(BaseModel):
    phase: Literal["playing", "finished"]
    currentRound: int
    playbackDurationIndex: int
    activePlayers: list[PlayerInState]
    inactivePlayers: list[PlayerInState]


class ErrorPayload(BaseModel):
    message: str
    details: list[str] | None = None


class ShuffledSongsPayload(BaseModel):
    shuffledSongIds: list[str]


class ScoredPayload(BaseModel):
    winner: Winner


class WrongAnswerPayload(BaseModel):
    lockoutExpiresAt: str | None


class RevealPayload(BaseModel):
    songId: str
    winners: list[Winner]


class PlayerStatePayload(BaseModel):
    scored: bool
    scoredRankIndex: int | None
    wrongAnswerCount: int
    lockoutExpiresAt: str | None
    pendingSongId: str | None
    pendingExpiresAt: str | None

    @model_validator(mode="after")
    def scored_matches_rank(self) -> Self:
        if self.scored != (self.scoredRankIndex is not None):
            raise ValueError(
                "scored must be true if and only if scoredRankIndex is set"
            )
        return self


class RestoreRevealPayload(BaseModel):
    songId: str
    winners: list[Winner]


class RoomClosedPayload(BaseModel):
    message: str


SC_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "room:settings": RoomSettingsSCPayload,
    "room:state": RoomState,
    "error": ErrorPayload,
    "game:shuffled-songs": ShuffledSongsPayload,
    "game:play-song": EmptyPayload,
    "game:scored": ScoredPayload,
    "game:wrong-answer": WrongAnswerPayload,
    "game:reveal": RevealPayload,
    "game:player-state": PlayerStatePayload,
    "game:restore-reveal": RestoreRevealPayload,
    "room:closed": RoomClosedPayload,
}
