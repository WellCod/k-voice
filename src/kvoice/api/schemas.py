from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kvoice.api.sintese import MAX_CARACTERES
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


_ID_VOZ_ELEVENLABS = r"^[A-Za-z0-9]+$"
_ID_VOZ_ELEVENLABS_OU_VAZIO = r"^[A-Za-z0-9]*$"


class VoiceCreate(BaseModel):
    # Limites iguais às colunas: texto maior virava 500 do banco em vez de 422. O id entra
    # no caminho do áudio de referência, então só letras, números, "-" e "_".
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=255)
    gender: str | None = Field(default=None, max_length=32)
    age_range: str | None = Field(default=None, max_length=32)
    style: str | None = Field(default=None, max_length=64)
    language: str = Field(default="pt-BR", max_length=16)
    origin: VoiceOrigin
    model_id: str | None = Field(default=None, max_length=255)
    style_prompt: str | None = None
    elevenlabs_voice_id: str | None = Field(default=None, max_length=64, pattern=_ID_VOZ_ELEVENLABS)
    # Cliente dono; sem ele a voz é do catálogo e todos os clientes a usam.
    client_id: uuid.UUID | None = None


class VoicePatch(BaseModel):
    style_prompt: str | None = None
    model_id: str | None = None
    # "" remove o mapeamento; None deixa como está.
    elevenlabs_voice_id: str | None = Field(
        default=None, max_length=64, pattern=_ID_VOZ_ELEVENLABS_OU_VAZIO
    )


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
    style_prompt: str | None
    elevenlabs_voice_id: str | None = None
    client_id: uuid.UUID | None = None
    is_active: bool
    created_at: datetime


class VoiceConsentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    voice_id: str
    consenter_name: str
    consenter_email: str
    audio_key: str
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


# -----------------------------------------------------------------------
# Síntese em lote
# -----------------------------------------------------------------------


class BatchRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CARACTERES)
    voice_id: str = Field(min_length=1)
    format: Literal["ogg_opus", "mp3_44100", "wav_24000"] = "ogg_opus"
    delivery: Literal["url", "bytes"] = "url"
    url_ttl_s: int = Field(default=86400, ge=60, le=604800)
    style_prompt: str | None = Field(default=None, max_length=500)


class BatchResponse(BaseModel):
    request_id: uuid.UUID
    url: str
    duration_ms: float
    characters: int


# -----------------------------------------------------------------------
# Dicionário de pronúncia
# -----------------------------------------------------------------------


class PronunciationEntryCreate(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    expansion: str = Field(min_length=1, max_length=1024)
    is_regex: bool = False

    @model_validator(mode="after")
    def _regex_valida(self) -> PronunciationEntryCreate:
        if self.is_regex:
            try:
                padrao = re.compile(self.term)
            except re.error as exc:
                raise ValueError(f"Regex inválida: {exc}") from exc
            try:
                # Grupo inexistente ou escape inválido na expansão só estouraria na síntese.
                padrao.sub(self.expansion, "")
            except (re.error, IndexError) as exc:
                raise ValueError(f"Expansão inválida para a regex: {exc}") from exc
        return self


class PronunciationEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID | None
    term: str
    expansion: str
    is_regex: bool
