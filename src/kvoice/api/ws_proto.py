from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class Options(BaseModel):
    speed: float = 1.0
    style: str = "neutro"


class StartMsg(BaseModel):
    type: Literal["start"]
    voice_id: str
    format: str = "pcm_24000"
    options: Options = Field(default_factory=Options)


class TextMsg(BaseModel):
    type: Literal["text"]
    text: str
    flush: bool = False


class CancelMsg(BaseModel):
    type: Literal["cancel"]


class EndMsg(BaseModel):
    type: Literal["end"]


_WsClientMsg = Annotated[
    StartMsg | TextMsg | CancelMsg | EndMsg,
    Field(discriminator="type"),
]

_adapter: TypeAdapter[StartMsg | TextMsg | CancelMsg | EndMsg] = TypeAdapter(_WsClientMsg)


def parse_client_msg(raw: str) -> StartMsg | TextMsg | CancelMsg | EndMsg:
    return _adapter.validate_json(raw)
