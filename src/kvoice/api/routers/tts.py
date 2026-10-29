from __future__ import annotations

import asyncio
import contextlib
import re
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Response, WebSocket, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.websockets import WebSocketDisconnect

from kvoice.api.auth import hash_token
from kvoice.api.deps import AuthDep, DbSession
from kvoice.api.metrics import (
    streams_active,
    streams_cancelled,
    streams_done,
    streams_errors,
    streams_started,
    ttfa_seconds,
)
from kvoice.api.routing import RoutingDecision, decide_engine
from kvoice.api.schemas import BatchRequest, BatchResponse
from kvoice.api.ws_proto import CancelMsg, EndMsg, StartMsg, TextMsg, parse_client_msg
from kvoice.audio import encode as encode_audio
from kvoice.audio import pcm_duration_ms
from kvoice.db.models import ApiToken, BatchJob, BatchStatus, Client
from kvoice.db.models import Voice as DbVoice
from kvoice.db.session import session_factory
from kvoice.engine.types import Audio, SynthOptions, Voice
from kvoice.normalize import apply_dict, load_dict, normalize, normalize_incremental
from kvoice.storage import get_storage

router = APIRouter(tags=["tts"])

_EXT: dict[str, str] = {"ogg_opus": "ogg", "mp3_44100": "mp3", "wav_24000": "wav"}
_FLUSH = "\x00"
_MAX_CHARS_SEGMENTO = 600
# Preferência: dividir apenas em ponto final para preservar contexto de perguntas/exclamações
_RE_FRASE_PONTO = re.compile(r"(?<=[.])\s+")
_RE_FRASE = re.compile(r"(?<=[.!?])\s+")


def _split_sentencas(text: str) -> list[str]:
    """Divide texto longo em sentenças para preservar prosódia por segmento."""
    if len(text) <= _MAX_CHARS_SEGMENTO:
        return [text]
    # Prefere dividir apenas em ponto final; cai para qualquer pontuação se necessário
    for regex in (_RE_FRASE_PONTO, _RE_FRASE):
        partes = regex.split(text.strip())
        if len(partes) > 1:
            break
    grupos: list[str] = []
    atual = ""
    for parte in partes:
        if not atual:
            atual = parte
        elif len(atual) + 1 + len(parte) <= _MAX_CHARS_SEGMENTO:
            atual += " " + parte
        else:
            grupos.append(atual)
            atual = parte
    if atual:
        grupos.append(atual)
    return grupos or [text]


async def _autenticar_ws(token: str) -> tuple[Client, ApiToken] | None:
    token_hash = hash_token(token)
    async with session_factory()() as db:
        result = await db.execute(
            select(ApiToken)
            .join(Client, ApiToken.client_id == Client.id)
            .where(
                ApiToken.token_hash == token_hash,
                ApiToken.is_active.is_(True),
                Client.is_active.is_(True),
            )
            .options(selectinload(ApiToken.client))
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return record.client, record


async def _buscar_voz(voice_id: str) -> DbVoice | None:
    async with session_factory()() as db:
        return await db.get(DbVoice, voice_id)


async def _gravar_uso(
    *,
    request_id: uuid.UUID,
    client_id: uuid.UUID,
    voice_id: str,
    engine_name: str,
    characters: int,
    audio_ms: float,
    ttfa_ms: float,
    total_ms: float,
    fallback: bool = False,
    fallback_reason: str | None = None,
) -> None:
    try:
        from kvoice.api.deps import registrar_uso

        async with session_factory()() as db:
            await registrar_uso(
                db,
                request_id=request_id,
                client_id=client_id,
                voice_id=voice_id,
                model=engine_name,
                characters=characters,
                audio_ms=audio_ms,
                ttfa_ms=ttfa_ms,
                total_ms=total_ms,
                engine=engine_name,
                fallback=fallback,
                fallback_reason=fallback_reason,
            )
    except Exception:
        pass


@router.post("/v1/tts", response_model=None)
async def sintetizar_lote(body: BatchRequest, db: DbSession, auth: AuthDep) -> Response:
    client, token = auth
    if not token.has_scope("tts:batch"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Escopo 'tts:batch' necessário",
        )

    orm_voice = await db.get(DbVoice, body.voice_id)
    if orm_voice is None or not orm_voice.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voz não encontrada")

    decision = await decide_engine(client.id, body.voice_id)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Motor indisponível",
        )

    voice = Voice(
        id=decision.effective_voice_id,
        name=orm_voice.name,
        language=orm_voice.language,
        model_id=orm_voice.model_id,
        ref_audio=orm_voice.ref_audio_key,
        ref_text=orm_voice.ref_text,
        style_prompt=orm_voice.style_prompt,
    )
    opts = SynthOptions(format=body.format, style=body.style_prompt or "neutro")
    pron = await load_dict(client.id)
    normalized = normalize(apply_dict(body.text, pron))

    sentencas = _split_sentencas(normalized)
    if len(sentencas) == 1:
        audio = await decision.engine.synthesize(sentencas[0], voice, opts)
    else:
        pcm_parts: list[bytes] = []
        primeiro_ttfa = 0.0
        for i, sent in enumerate(sentencas):
            seg = await decision.engine.synthesize(sent, voice, opts)
            if i == 0:
                primeiro_ttfa = seg.ttfa_ms
            pcm_parts.append(seg.data)
        silence = b"\x00" * int(0.06 * decision.engine.sample_rate) * 2
        combined = silence.join(pcm_parts)
        audio = Audio(
            data=combined,
            sample_rate=decision.engine.sample_rate,
            duration_ms=pcm_duration_ms(combined, decision.engine.sample_rate),
            ttfa_ms=primeiro_ttfa,
        )

    encoded, content_type = encode_audio(audio.data, audio.sample_rate, body.format)
    duration_ms = round(pcm_duration_ms(audio.data, audio.sample_rate), 1)
    request_id = uuid.uuid4()

    if body.delivery == "bytes":
        job = BatchJob(
            id=request_id,
            client_id=client.id,
            voice_id=body.voice_id,
            status=BatchStatus.done,
            input_text=body.text,
            format=body.format,
            duration_ms=duration_ms,
            completed_at=datetime.now(UTC),
        )
        db.add(job)
        await db.commit()
        return Response(
            content=encoded,
            media_type=content_type,
            headers={
                "X-Request-Id": str(request_id),
                "X-Duration-Ms": str(duration_ms),
            },
        )

    key = f"outputs/{request_id}.{_EXT[body.format]}"
    storage = get_storage()
    await storage.upload(key, encoded, content_type)
    url = await storage.presigned_url(key, body.url_ttl_s)

    job = BatchJob(
        id=request_id,
        client_id=client.id,
        voice_id=body.voice_id,
        status=BatchStatus.done,
        input_text=body.text,
        format=body.format,
        output_key=key,
        duration_ms=duration_ms,
        completed_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(seconds=body.url_ttl_s),
    )
    db.add(job)
    await db.commit()

    return JSONResponse(
        BatchResponse(
            request_id=request_id,
            url=url,
            duration_ms=duration_ms,
            characters=len(body.text),
        ).model_dump(mode="json")
    )


@router.websocket("/v1/tts/stream")
async def ws_stream(websocket: WebSocket, token: str = Query(...)) -> None:
    await websocket.accept()

    auth = await _autenticar_ws(token)
    if auth is None:
        await websocket.send_json({"type": "error", "code": "unauthorized"})
        await websocket.close(code=4001)
        return

    client, api_token = auth
    if not api_token.has_scope("tts:stream"):
        await websocket.send_json({"type": "error", "code": "forbidden"})
        await websocket.close(code=4003)
        return

    streams_started.inc()
    streams_active.inc()
    try:
        await _executar_stream(websocket, client)
    except Exception:
        streams_errors.labels(code="internal").inc()
        raise
    finally:
        streams_active.dec()


async def _executar_stream(
    websocket: WebSocket,
    client: Client,
) -> None:
    try:
        raw = await websocket.receive_text()
        first_msg = parse_client_msg(raw)
    except (WebSocketDisconnect, ValidationError):
        return

    if not isinstance(first_msg, StartMsg):
        await websocket.send_json({"type": "error", "code": "protocol"})
        await websocket.close()
        return

    start = first_msg

    orm_voice = await _buscar_voz(start.voice_id)
    if orm_voice is None or not orm_voice.is_active:
        await websocket.send_json({"type": "error", "code": "voice_not_found"})
        await websocket.close()
        return

    decision = await decide_engine(client.id, start.voice_id)

    if decision is None:
        await websocket.send_json({"type": "error", "code": "capacity"})
        await websocket.close(code=1013)
        return

    await _executar_com_engine(websocket, client, start, orm_voice, decision)


async def _executar_com_engine(
    websocket: WebSocket,
    client: Client,
    start: StartMsg,
    orm_voice: DbVoice,
    decision: RoutingDecision,
) -> None:
    engine = decision.engine
    voice = Voice(
        id=decision.effective_voice_id,
        name=orm_voice.name,
        language=orm_voice.language,
        model_id=orm_voice.model_id,
        ref_audio=orm_voice.ref_audio_key,
        ref_text=orm_voice.ref_text,
        style_prompt=orm_voice.style_prompt,
    )
    opts = SynthOptions(
        speed=start.options.speed,
        style=start.options.style,
        format=start.format,
    )
    request_id = uuid.uuid4()

    send_queue: asyncio.Queue[bytes | dict[str, object] | None] = asyncio.Queue()
    text_queue: asyncio.Queue[str | None] = asyncio.Queue()
    cancelled = asyncio.Event()

    await send_queue.put(
        {
            "type": "started",
            "request_id": str(request_id),
            "engine": decision.engine_name,
            "sample_rate": engine.sample_rate,
        }
    )

    t0 = time.monotonic()
    ttfa_ms = 0.0
    total_audio_ms = 0.0
    total_chars = 0
    first_chunk = True

    async def _text_iter() -> AsyncIterator[str]:
        pending = ""
        while True:
            item = await text_queue.get()
            if item is None:
                if pending and not cancelled.is_set():
                    normed = normalize(pending)
                    if normed:
                        yield normed
                return
            if item is _FLUSH:
                if pending:
                    normed = normalize(pending)
                    pending = ""
                    if normed:
                        yield normed
                await send_queue.put({"type": "flushed"})
                continue
            ready, pending = normalize_incremental(pending + item)
            if ready:
                yield ready

    async def _send_audio() -> None:
        nonlocal ttfa_ms, total_audio_ms, first_chunk
        try:
            async for chunk in await engine.stream(_text_iter(), voice, opts):
                if cancelled.is_set():
                    break
                if first_chunk:
                    ttfa_ms = (time.monotonic() - t0) * 1000
                    first_chunk = False
                await send_queue.put(chunk.data)
                total_audio_ms += chunk.duration_ms
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            await send_queue.put({"type": "error", "code": "engine", "detail": str(exc)})

    async def _sender() -> None:
        while True:
            item = await send_queue.get()
            if item is None:
                break
            if isinstance(item, (bytes, bytearray)):
                await websocket.send_bytes(item)
            else:
                await websocket.send_json(item)

    audio_task = asyncio.create_task(_send_audio())
    sender_task = asyncio.create_task(_sender())

    cancelled_by_client = False
    try:
        async for raw in websocket.iter_text():
            try:
                msg = parse_client_msg(raw)
            except ValidationError:
                continue

            if isinstance(msg, TextMsg):
                total_chars += len(msg.text)
                await text_queue.put(msg.text)
                if msg.flush:
                    await text_queue.put(_FLUSH)
            elif isinstance(msg, CancelMsg):
                cancelled.set()
                await text_queue.put(None)
                cancelled_by_client = True
                break
            elif isinstance(msg, EndMsg):
                await text_queue.put(None)
                break
        else:
            cancelled.set()
            await text_queue.put(None)
            cancelled_by_client = True

    except WebSocketDisconnect:
        cancelled.set()
        await text_queue.put(None)
        cancelled_by_client = True

    finally:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await audio_task
        if not audio_task.done():
            audio_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await audio_task
        await send_queue.put(None)
        with contextlib.suppress(Exception):
            await sender_task

    if not cancelled_by_client:
        streams_done.inc()
        if ttfa_ms > 0:
            ttfa_seconds.observe(ttfa_ms / 1000)
        await websocket.send_json(
            {
                "type": "done",
                "ttfa_ms": round(ttfa_ms, 1),
                "audio_ms": round(total_audio_ms, 1),
            }
        )
        total_ms = (time.monotonic() - t0) * 1000
        asyncio.create_task(
            _gravar_uso(
                request_id=request_id,
                client_id=client.id,
                voice_id=start.voice_id,
                engine_name=decision.engine_name,
                characters=total_chars,
                audio_ms=total_audio_ms,
                ttfa_ms=ttfa_ms,
                total_ms=total_ms,
                fallback=decision.is_fallback,
                fallback_reason=decision.fallback_reason,
            )
        )
    else:
        streams_cancelled.inc()
        with contextlib.suppress(Exception):
            await websocket.close()
