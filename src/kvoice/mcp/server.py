"""Servidor MCP com ferramentas de síntese de voz para agentes de IA.

Ferramentas:
  synthesize(text, voice_id, format, url_ttl_s) → {request_id, url, duration_ms, characters}
  list_voices(language)                          → [{id, name, ...}]
  get_voice(voice_id)                            → {id, name, ...}

Autenticação: Bearer token de cliente (mesmo esquema da API REST).
Sem streaming de áudio — ADR-0006.
"""

from __future__ import annotations

import uuid
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import MCPError
from sqlalchemy import select

from kvoice.api.auth import hash_token
from kvoice.api.routing import decide_engine
from kvoice.audio import encode as encode_audio
from kvoice.audio import pcm_duration_ms
from kvoice.db.models import ApiToken, Client
from kvoice.db.models import Voice as DbVoice
from kvoice.db.session import session_factory
from kvoice.engine.types import SynthOptions, Voice
from kvoice.normalize import apply_dict, load_dict, normalize
from kvoice.storage import get_storage

mcp = MCPServer(name="k-voice", description="Síntese de voz pt-BR para agentes de IA")

_EXT: dict[str, str] = {"ogg_opus": "ogg", "mp3_44100": "mp3", "wav_24000": "wav"}


# ---------------------------------------------------------------------------
# Helpers de acesso a dados (patcháveis em testes)
# ---------------------------------------------------------------------------


async def _validar_token(raw: str) -> tuple[Client, ApiToken] | None:
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
            return None
        return record.client, record


async def _buscar_voz(voice_id: str) -> DbVoice | None:
    async with session_factory()() as db:
        return await db.get(DbVoice, voice_id)


async def _listar_vozes(language: str | None = None) -> list[DbVoice]:
    async with session_factory()() as db:
        stmt = select(DbVoice).where(DbVoice.is_active.is_(True)).order_by(DbVoice.name)
        if language is not None:
            stmt = stmt.where(DbVoice.language == language)
        result = await db.execute(stmt)
        return list(result.scalars().all())


def _voice_to_dict(v: DbVoice) -> dict[str, Any]:
    return {
        "id": v.id,
        "name": v.name,
        "gender": v.gender,
        "age_range": v.age_range,
        "style": v.style,
        "language": v.language,
        "origin": str(v.origin),
        "model_id": v.model_id,
    }


async def _auth(ctx: Context, scope: str) -> tuple[Client, ApiToken]:
    headers = dict(ctx.headers or {})
    authorization = headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise MCPError(-32000, "Token ausente")
    raw = authorization[7:]
    result = await _validar_token(raw)
    if result is None:
        raise MCPError(-32000, "Token inválido")
    client, token = result
    if not token.has_scope(scope):
        raise MCPError(-32000, f"Escopo '{scope}' necessário")
    return client, token


# ---------------------------------------------------------------------------
# Ferramentas MCP
# ---------------------------------------------------------------------------


@mcp.tool(description="Sintetiza texto em áudio e devolve URL assinada do S3.")
async def synthesize(
    text: str,
    voice_id: str,
    format: str = "ogg_opus",
    url_ttl_s: int = 86400,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """
    Sintetiza o texto na voz indicada e grava o resultado no bucket S3.
    Formatos: ogg_opus (padrão, WhatsApp), mp3_44100, wav_24000.
    url_ttl_s: validade da URL em segundos (60–604800, padrão 86400).
    """
    if format not in _EXT:
        formatos = "ogg_opus, mp3_44100, wav_24000"
        raise MCPError(-32602, f"Formato inválido: {format!r}. Use {formatos}.")

    client, _token = await _auth(ctx, "tts:batch")

    orm_voice = await _buscar_voz(voice_id)
    if orm_voice is None or not orm_voice.is_active:
        raise MCPError(-32000, f"Voz {voice_id!r} não encontrada.")

    decision = await decide_engine(client.id, voice_id)
    if decision is None:
        raise MCPError(-32000, "Motor de síntese indisponível.")

    voice = Voice(
        id=decision.effective_voice_id,
        name=orm_voice.name,
        style_prompt=orm_voice.style_prompt,
    )
    pron = await load_dict(client.id)
    normalized = normalize(apply_dict(text, pron))
    audio = await decision.engine.synthesize(normalized, voice, SynthOptions(format=format))

    encoded, content_type = encode_audio(audio.data, audio.sample_rate, format)
    duration_ms = round(pcm_duration_ms(audio.data, audio.sample_rate), 1)
    request_id = uuid.uuid4()

    key = f"outputs/{request_id}.{_EXT[format]}"
    storage = get_storage()
    await storage.upload(key, encoded, content_type)
    url = await storage.presigned_url(key, url_ttl_s)

    return {
        "request_id": str(request_id),
        "url": url,
        "duration_ms": duration_ms,
        "characters": len(text),
    }


@mcp.tool(description="Lista vozes disponíveis no catálogo.")
async def list_voices(
    language: str | None = None,
    ctx: Context = None,  # type: ignore[assignment]
) -> list[dict[str, Any]]:
    """
    Retorna vozes ativas. Filtre por language (ex: 'pt-BR').
    """
    await _auth(ctx, "voices:read")
    vozes = await _listar_vozes(language=language)
    return [_voice_to_dict(v) for v in vozes]


@mcp.tool(description="Retorna dados de uma voz específica.")
async def get_voice(
    voice_id: str,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """
    Busca voz por ID. Levanta erro se não encontrada ou inativa.
    """
    await _auth(ctx, "voices:read")
    voz = await _buscar_voz(voice_id)
    if voz is None or not voz.is_active:
        raise MCPError(-32000, f"Voz {voice_id!r} não encontrada.")
    return _voice_to_dict(voz)
