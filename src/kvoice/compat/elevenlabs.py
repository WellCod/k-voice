"""Subconjunto compatível com a API REST da ElevenLabs.

Endpoint implementado:
  POST /v1/text-to-speech/{voice_id} — devolve áudio diretamente (bytes).

Autenticação: header xi-api-key (padrão ElevenLabs) ou Authorization: Bearer.
Mapeamento de formato via output_format query param.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from kvoice.api.auth import hash_token
from kvoice.api.routing import decide_engine
from kvoice.audio import encode as encode_audio
from kvoice.db.models import ApiToken, Client
from kvoice.db.models import Voice as DbVoice
from kvoice.db.session import session_factory
from kvoice.engine.types import SynthOptions, Voice
from kvoice.normalize import apply_dict, load_dict, normalize

router = APIRouter(prefix="/v1", tags=["compat-elevenlabs"])


def _map_format(output_format: str) -> str:
    if output_format.startswith("mp3_"):
        return "mp3_44100"
    if output_format.startswith("pcm_") or output_format.startswith("wav_"):
        return "wav_24000"
    if output_format.startswith("opus_") or output_format.startswith("ogg_"):
        return "ogg_opus"
    return "mp3_44100"


class _VoiceSettings(BaseModel):
    stability: float | None = None
    similarity_boost: float | None = None
    style: float | None = None
    speed: float | None = None
    use_speaker_boost: bool | None = None


class _TtsRequest(BaseModel):
    text: str
    model_id: str | None = None
    voice_settings: _VoiceSettings | None = None


async def _buscar_voz(voice_id: str) -> DbVoice | None:
    async with session_factory()() as db:
        return await db.get(DbVoice, voice_id)


async def _autenticar(xi_api_key: str | None, authorization: str | None) -> tuple[Client, ApiToken]:
    raw: str | None = None
    if xi_api_key:
        raw = xi_api_key
    elif authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:]
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chave ausente")
    token_hash = hash_token(raw)
    async with session_factory()() as db:
        result = await db.execute(
            select(ApiToken)
            .join(Client, ApiToken.client_id == Client.id)
            .where(
                ApiToken.token_hash == token_hash,
                ApiToken.is_active.is_(True),
                Client.is_active.is_(True),
            )
        )
        record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chave inválida")
    client, token = record.client, record
    if not token.has_scope("tts:batch"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Escopo 'tts:batch' necessário"
        )
    return client, token


@router.post("/text-to-speech/{voice_id}", response_model=None)
async def text_to_speech(
    voice_id: str,
    body: _TtsRequest,
    output_format: Annotated[str, Query()] = "mp3_44100_128",
    xi_api_key: Annotated[str | None, Header(alias="xi-api-key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """POST /v1/text-to-speech/{voice_id} compatível com a ElevenLabs."""
    client, _token = await _autenticar(xi_api_key, authorization)

    our_format = _map_format(output_format)

    orm_voice = await _buscar_voz(voice_id)
    if orm_voice is None or not orm_voice.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voz não encontrada")

    decision = await decide_engine(client.id, voice_id)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Motor indisponível"
        )

    speed: float = 1.0
    if body.voice_settings and body.voice_settings.speed is not None:
        speed = body.voice_settings.speed

    voice = Voice(
        id=decision.effective_voice_id,
        name=orm_voice.name,
        style_prompt=orm_voice.style_prompt,
    )
    opts = SynthOptions(format=our_format, speed=speed)
    pron = await load_dict(client.id)
    audio = await decision.engine.synthesize(normalize(apply_dict(body.text, pron)), voice, opts)
    encoded, content_type = encode_audio(audio.data, audio.sample_rate, our_format)
    return Response(content=encoded, media_type=content_type)
