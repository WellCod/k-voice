"""Servidor MCP com ferramentas de síntese de voz para agentes de IA.

Ferramentas:
  synthesize(text, voice_id, format, url_ttl_s) → {request_id, url, duration_ms, characters}
  list_voices(language)                          → [{id, name, ...}]
  get_voice(voice_id)                            → {id, name, ...}

Autenticação: Bearer token de cliente (mesmo esquema da API REST).
Sem streaming de áudio — ADR-0006.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import MCPError
from sqlalchemy import select

from kvoice.api.deps import autenticar_token, gravar_uso
from kvoice.api.routing import decide_engine
from kvoice.api.sintese import MAX_CARACTERES, sintetizar_em_partes
from kvoice.audio import encode as encode_audio
from kvoice.audio import pcm_duration_ms
from kvoice.db.models import ApiToken, Client
from kvoice.db.models import Voice as DbVoice
from kvoice.db.session import session_factory
from kvoice.engine.types import SynthOptions
from kvoice.normalize import apply_dict, load_dict, normalize
from kvoice.storage import get_storage

mcp = MCPServer(name="k-voice", description="Síntese de voz pt-BR para agentes de IA")

_EXT: dict[str, str] = {"ogg_opus": "ogg", "mp3_44100": "mp3", "wav_24000": "wav"}


# ---------------------------------------------------------------------------
# Helpers de acesso a dados (patcháveis em testes)
# ---------------------------------------------------------------------------


async def _validar_token(token_em_texto: str) -> tuple[Client, ApiToken] | None:
    return await autenticar_token(token_em_texto)


async def _buscar_voz(voice_id: str) -> DbVoice | None:
    async with session_factory()() as db:
        return await db.get(DbVoice, voice_id)


async def _listar_vozes(
    client_id: uuid.UUID, admin: bool, language: str | None = None
) -> list[DbVoice]:
    """Vozes ativas que o cliente enxerga (catálogo e as próprias; admin vê todas)."""
    async with session_factory()() as db:
        consulta = (
            select(DbVoice)
            .where(DbVoice.is_active.is_(True), DbVoice.filtro_visivel(client_id, admin))
            .order_by(DbVoice.name)
        )
        if language is not None:
            consulta = consulta.where(DbVoice.language == language)
        result = await db.execute(consulta)
        return list(result.scalars().all())


def _voice_to_dict(voz: DbVoice) -> dict[str, Any]:
    return {
        "id": voz.id,
        "name": voz.name,
        "gender": voz.gender,
        "age_range": voz.age_range,
        "style": voz.style,
        "language": voz.language,
        "origin": str(voz.origin),
        "model_id": voz.model_id,
    }


async def _auth(ctx: Context, scope: str) -> tuple[Client, ApiToken]:
    """Autentica pelo `Authorization: Bearer` da requisição HTTP do MCP e exige o escopo."""
    headers = dict(ctx.headers or {})
    authorization = headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise MCPError(-32000, "Token ausente")
    token_em_texto = authorization[7:]
    result = await _validar_token(token_em_texto)
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
    if not text.strip():
        raise MCPError(-32602, "text não pode ser vazio.")
    if len(text) > MAX_CARACTERES:
        raise MCPError(-32602, f"text passa de {MAX_CARACTERES} caracteres.")
    if format not in _EXT:
        formatos = "ogg_opus, mp3_44100, wav_24000"
        raise MCPError(-32602, f"Formato inválido: {format!r}. Use {formatos}.")
    if not 60 <= url_ttl_s <= 604_800:
        raise MCPError(-32602, "url_ttl_s deve estar entre 60 e 604800.")

    client, token = await _auth(ctx, "tts:batch")

    orm_voice = await _buscar_voz(voice_id)
    if orm_voice is None or not orm_voice.visivel_para(client.id, token.has_scope("admin")):
        raise MCPError(-32000, f"Voz {voice_id!r} não encontrada.")

    inicio = time.monotonic()
    decision = await decide_engine(client.id, voice_id, orm_voice.elevenlabs_voice_id)
    if decision is None:
        raise MCPError(-32000, "Motor de síntese indisponível.")

    voice = decision.voz(orm_voice)
    dicionario = await load_dict(client.id)
    texto_normalizado = normalize(apply_dict(text, dicionario))
    audio = await sintetizar_em_partes(
        decision.engine, texto_normalizado, voice, SynthOptions(format=format)
    )

    encoded, content_type = await asyncio.to_thread(
        encode_audio, audio.data, audio.sample_rate, format
    )
    duration_ms = round(pcm_duration_ms(audio.data, audio.sample_rate), 1)
    request_id = uuid.uuid4()
    await gravar_uso(
        request_id=request_id,
        client_id=client.id,
        voice_id=voice_id,
        engine_name=decision.engine_name,
        characters=len(text),
        audio_ms=duration_ms,
        ttfa_ms=audio.ttfa_ms,
        total_ms=(time.monotonic() - inicio) * 1000,
        fallback=decision.is_fallback,
        fallback_reason=decision.fallback_reason,
    )

    chave_objeto = f"outputs/{request_id}.{_EXT[format]}"
    storage = get_storage()
    await storage.upload(chave_objeto, encoded, content_type)
    url = await storage.presigned_url(chave_objeto, url_ttl_s)

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
    client, token = await _auth(ctx, "voices:read")
    vozes = await _listar_vozes(client.id, token.has_scope("admin"), language=language)
    return [_voice_to_dict(voz) for voz in vozes]


@mcp.tool(description="Retorna dados de uma voz específica.")
async def get_voice(
    voice_id: str,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """
    Busca voz por ID. Levanta erro se não encontrada ou inativa.
    """
    client, token = await _auth(ctx, "voices:read")
    voz = await _buscar_voz(voice_id)
    if voz is None or not voz.visivel_para(client.id, token.has_scope("admin")):
        raise MCPError(-32000, f"Voz {voice_id!r} não encontrada.")
    return _voice_to_dict(voz)
