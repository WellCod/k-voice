from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Response, WebSocket, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from kvoice.api.deps import AuthDep, DbSession, autenticar_token
from kvoice.api.deps import gravar_uso as _gravar_uso
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
from kvoice.api.sintese import (
    MAX_CARACTERES,
    MAX_CARACTERES_SEGMENTO,
    cortar_em_pausa,
    sintetizar_em_partes,
)
from kvoice.api.ws_proto import CancelMsg, EndMsg, StartMsg, TextMsg, parse_client_msg
from kvoice.audio import encode as encode_audio
from kvoice.audio import pcm_duration_ms
from kvoice.db.models import ApiToken, BatchJob, BatchStatus, Client
from kvoice.db.models import Voice as DbVoice
from kvoice.db.session import session_factory
from kvoice.engine.types import SynthOptions
from kvoice.normalize import (
    PronEntry,
    apply_dict,
    load_dict,
    normalize,
    normalize_incremental,
)
from kvoice.storage import get_storage

router = APIRouter(tags=["tts"])
_log = logging.getLogger(__name__)
# Referência forte às tarefas de gravação de uso para não serem coletadas antes de terminar
_tarefas_uso: set[asyncio.Task[None]] = set()

_EXT: dict[str, str] = {"ogg_opus": "ogg", "mp3_44100": "mp3", "wav_24000": "wav"}
_FLUSH = object()


async def _autenticar_ws(token: str) -> tuple[Client, ApiToken] | None:
    return await autenticar_token(token)


async def _buscar_voz(voice_id: str) -> DbVoice | None:
    async with session_factory()() as db:
        return await db.get(DbVoice, voice_id)


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

    t0 = time.monotonic()
    decision = await decide_engine(client.id, body.voice_id, orm_voice.elevenlabs_voice_id)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Motor indisponível",
        )

    voice = decision.voz(orm_voice)
    opts = SynthOptions(format=body.format, style=body.style_prompt or "neutro")
    pron = await load_dict(client.id)
    normalized = normalize(apply_dict(body.text, pron))

    audio = await sintetizar_em_partes(decision.engine, normalized, voice, opts)

    encoded, content_type = await asyncio.to_thread(
        encode_audio, audio.data, audio.sample_rate, body.format
    )
    duration_ms = round(pcm_duration_ms(audio.data, audio.sample_rate), 1)
    request_id = uuid.uuid4()
    await _gravar_uso(
        request_id=request_id,
        client_id=client.id,
        voice_id=body.voice_id,
        engine_name=decision.engine_name,
        characters=len(body.text),
        audio_ms=duration_ms,
        ttfa_ms=audio.ttfa_ms,
        total_ms=(time.monotonic() - t0) * 1000,
        fallback=decision.is_fallback,
        fallback_reason=decision.fallback_reason,
    )

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

    decision = await decide_engine(client.id, start.voice_id, orm_voice.elevenlabs_voice_id)

    if decision is None:
        await websocket.send_json({"type": "error", "code": "capacity"})
        await websocket.close(code=1013)
        return

    # Uma consulta no início da fala, fora do caminho crítico do áudio.
    pron = await load_dict(client.id)
    await _executar_com_engine(websocket, client, start, orm_voice, decision, pron)


async def _executar_com_engine(
    websocket: WebSocket,
    client: Client,
    start: StartMsg,
    orm_voice: DbVoice,
    decision: RoutingDecision,
    pron: list[PronEntry],
) -> None:
    engine = decision.engine
    voice = decision.voz(orm_voice)
    opts = SynthOptions(
        speed=start.options.speed,
        style=start.options.style,
        format=start.format,
    )
    request_id = uuid.uuid4()

    send_queue: asyncio.Queue[bytes | dict[str, object] | None] = asyncio.Queue()
    text_queue: asyncio.Queue[str | object | None] = asyncio.Queue()
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
    # "flushed" só sai depois do áudio do texto anterior ao flush: o motor marca em cada
    # chunk quantos itens de texto terminaram de soar (AudioChunk.textos_concluidos).
    entregues = 0
    concluidos = 0
    flushes: deque[int] = deque()

    async def _liberar_flushes() -> None:
        while flushes and flushes[0] <= concluidos:
            flushes.popleft()
            await send_queue.put({"type": "flushed"})

    async def _text_iter() -> AsyncIterator[str]:
        nonlocal entregues
        pending = ""
        while True:
            item = await text_queue.get()
            if item is None:
                if pending and not cancelled.is_set():
                    normed = normalize(apply_dict(pending, pron))
                    if normed:
                        entregues += 1
                        yield normed
                return
            if item is _FLUSH:
                if pending:
                    normed = normalize(apply_dict(pending, pron))
                    pending = ""
                    if normed:
                        entregues += 1
                        yield normed
                flushes.append(entregues)
                await _liberar_flushes()
                continue
            assert isinstance(item, str)
            ready, pending = normalize_incremental(
                pending + item, pre=lambda t: apply_dict(t, pron)
            )
            if ready:
                entregues += 1
                yield ready
            # Texto sem fim de frase se acumularia sem limite: cada pedaço reprocessaria
            # tudo (custo quadrático no loop) e a "frase" final seguraria o lock do motor.
            while len(pending) > MAX_CARACTERES_SEGMENTO:
                cabeca, pending = cortar_em_pausa(pending)
                normed = normalize(apply_dict(cabeca, pron))
                if normed:
                    entregues += 1
                    yield normed

    falhou = False

    async def _send_audio() -> None:
        nonlocal ttfa_ms, total_audio_ms, first_chunk, concluidos, falhou
        try:
            # aclosing: ao sair do loop o motor para a geração na hora, não só no GC.
            async with contextlib.aclosing(await engine.stream(_text_iter(), voice, opts)) as gen:
                async for chunk in gen:
                    if cancelled.is_set():
                        break
                    if chunk.data:
                        if first_chunk:
                            ttfa_ms = (time.monotonic() - t0) * 1000
                            first_chunk = False
                        await send_queue.put(chunk.data)
                        total_audio_ms += chunk.duration_ms
                    concluidos += chunk.textos_concluidos
                    await _liberar_flushes()
            # Motor que não marca textos_concluidos: todo o texto soou ao fim do stream.
            concluidos = entregues
            await _liberar_flushes()
        except asyncio.CancelledError:
            pass
        except Exception:
            _log.exception("falha no motor %s (request_id=%s)", engine.name, request_id)
            streams_errors.labels(code="engine").inc()
            falhou = True
            await send_queue.put({"type": "error", "code": "engine"})

    cancelled_by_client = False

    def _interromper() -> None:
        nonlocal cancelled_by_client
        cancelled.set()
        cancelled_by_client = True
        text_queue.put_nowait(None)

    async def _sender() -> None:
        while True:
            item = await send_queue.get()
            if item is None:
                break
            if isinstance(item, (bytes, bytearray)):
                if cancelled.is_set():
                    continue
                try:
                    await websocket.send_bytes(item)
                except Exception:
                    # Cliente sumiu no meio do áudio: para o motor em vez de gerar para ninguém.
                    _interromper()
                    audio_task.cancel()
                    return
            else:
                await websocket.send_json(item)

    async def _reader() -> None:
        # Continua lendo depois do "end": o barge-in chega como "cancel" enquanto o
        # áudio do turno ainda está saindo, e precisa parar o motor.
        nonlocal total_chars
        encerrado = False
        try:
            async for raw in websocket.iter_text():
                try:
                    msg = parse_client_msg(raw)
                except ValidationError:
                    continue
                if isinstance(msg, CancelMsg):
                    _interromper()
                    return
                if encerrado:
                    continue
                if isinstance(msg, TextMsg):
                    total_chars += len(msg.text)
                    if total_chars > MAX_CARACTERES:
                        streams_errors.labels(code="text_too_long").inc()
                        await send_queue.put({"type": "error", "code": "text_too_long"})
                        _interromper()
                        return
                    await text_queue.put(msg.text)
                    if msg.flush:
                        await text_queue.put(_FLUSH)
                elif isinstance(msg, EndMsg):
                    encerrado = True
                    await text_queue.put(None)
        except WebSocketDisconnect:
            pass
        _interromper()

    audio_task = asyncio.create_task(_send_audio())
    sender_task = asyncio.create_task(_sender())
    reader_task = asyncio.create_task(_reader())

    try:
        await asyncio.wait({audio_task, reader_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Cancelamento não espera a síntese em curso terminar (gate: < 50 ms).
        if cancelled.is_set():
            audio_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await audio_task
        reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await reader_task
        await send_queue.put(None)
        with contextlib.suppress(Exception):
            await sender_task

    if falhou and not cancelled_by_client:
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
        return

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
        task = asyncio.create_task(
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
        _tarefas_uso.add(task)
        task.add_done_callback(_tarefas_uso.discard)
    else:
        streams_cancelled.inc()
        with contextlib.suppress(Exception):
            await websocket.close()
