from __future__ import annotations

import json
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kvoice.db.models import RoutingMode, VoiceOrigin

# -----------------------------------------------------------------------
# Client
# -----------------------------------------------------------------------


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime


# -----------------------------------------------------------------------
# Token
# -----------------------------------------------------------------------


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=list)


class TokenCreated(BaseModel):
    id: uuid.UUID
    name: str
    token: str  # raw token — exibido apenas uma vez
    scopes: list[str]


class TokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    scopes_list: list[str]
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None


# -----------------------------------------------------------------------
# Voice
# -----------------------------------------------------------------------


class VoiceCreate(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    gender: str | None = None
    age_range: str | None = None
    style: str | None = None
    language: str = "pt-BR"
    origin: VoiceOrigin
    model_id: str | None = None
    style_prompt: str | None = None


class VoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    gender: str | None
    age_range: str | None
    style: str | None
    language: str
    origin: VoiceOrigin
    model_id: str | None
    is_active: bool
    created_at: datetime


# -----------------------------------------------------------------------
# Usage event
# -----------------------------------------------------------------------


# -----------------------------------------------------------------------
# Routing rule
# -----------------------------------------------------------------------


class RoutingRuleCreate(BaseModel):
    mode: RoutingMode
    kvoice_pct: float = Field(default=1.0, ge=0.0, le=1.0)
    voice_mapping: dict[str, str] | None = None

    @model_validator(mode="after")
    def _valida_pct(self) -> RoutingRuleCreate:
        if self.mode == RoutingMode.percentual and self.kvoice_pct is None:
            raise ValueError("kvoice_pct obrigatório no modo percentual")
        return self


class RoutingRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    mode: RoutingMode
    kvoice_pct: float
    voice_mapping: dict[str, str] | None
    is_active: bool

    @field_validator("voice_mapping", mode="before")
    @classmethod
    def _parse_mapping(cls, v: object) -> dict[str, str] | None:
        if isinstance(v, str):
            parsed: dict[str, str] = json.loads(v)
            return parsed
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}
        return None


# -----------------------------------------------------------------------
# Usage event
# -----------------------------------------------------------------------


class UsageEventIn(BaseModel):
    request_id: uuid.UUID
    client_id: uuid.UUID
    voice_id: str
    model: str
    characters: int
    audio_ms: float
    ttfa_ms: float
    total_ms: float
    engine: str
    fallback: bool = False
    fallback_reason: str | None = None
