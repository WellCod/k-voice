from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, WebSocket
from pydantic import ValidationError
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from kvoice.api.auth import hash_token
from kvoice.api.metrics import (
    streams_active,
    streams_cancelled,
    streams_done,
    streams_errors,
    streams_started,
    ttfa_seconds,
)
from kvoice.api.ws_proto import CancelMsg, EndMsg, StartMsg, TextMsg, parse_client_msg
from kvoice.db.models import ApiToken, Client
from kvoice.db.models import Voice as DbVoice
from kvoice.db.session import session_factory
from kvoice.engine.registry import _ADMISSION_MAX_QUEUE, get_engine
from kvoice.engine.types import SynthOptions, TTSEngine, Voice
from kvoice.normalize import normalize, normalize_incremental

router = APIRouter(tags=["tts"])

# Sentinel inserido na fila de texto para forçar flush imediato do normalizador.
_FLUSH = "\x00"


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
            )
    except Exception:
        pass  # uso não crítico — não derrubar a chamada por falha de medição


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

    engine = get_engine()
    if engine is None or engine.capacity().queued >= _ADMISSION_MAX_QUEUE:
        await websocket.send_json({"type": "error", "code": "capacity"})
        await websocket.close(code=1013)
        return

    streams_started.inc()
    streams_active.inc()
    try:
        await _executar_stream(websocket, client, engine)
    except Exception:
        streams_errors.labels(code="internal").inc()
        raise
    finally:
        streams_active.dec()


async def _executar_stream(
    websocket: WebSocket,
    client: Client,
    engine: TTSEngine,
) -> None:
    # Aguarda mensagem start
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

    voice = Voice(
        id=orm_voice.id,
        name=orm_voice.name,
        style_prompt=orm_voice.style_prompt,
    )
    opts = SynthOptions(
        speed=start.options.speed,
        style=start.options.style,
        format=start.format,
    )
    request_id = uuid.uuid4()

    # Fila de saída única — garante sends sequenciais no WebSocket.
    send_queue: asyncio.Queue[bytes | dict[str, object] | None] = asyncio.Queue()
    text_queue: asyncio.Queue[str | None] = asyncio.Queue()
    cancelled = asyncio.Event()

    await send_queue.put(
        {
            "type": "started",
            "request_id": str(request_id),
            "engine": engine.name,
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
        # Aguarda audio_task encerrar naturalmente (text_queue já tem None)
        # antes de parar o sender; evita cancelar enquanto chunks estão na fila.
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
                engine_name=engine.name,
                characters=total_chars,
                audio_ms=total_audio_ms,
                ttfa_ms=ttfa_ms,
                total_ms=total_ms,
            )
        )
    else:
        streams_cancelled.inc()
