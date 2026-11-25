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
from kvoice.cache_consultas import em_cache
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
# Marcador na fila de texto: o cliente pediu flush depois do texto anterior.
_FLUSH = object()
# Depois do "done", a conexão espera o próximo "start" por este tempo antes de fechar.
_OCIOSO_ENTRE_FALAS_S = 60.0


async def _autenticar_ws(token: str) -> tuple[Client, ApiToken] | None:
    return await autenticar_token(token)


@em_cache
async def _buscar_voz(voice_id: str) -> DbVoice | None:
    """Carrega a voz com sessão própria; o WebSocket não usa a sessão por requisição."""
    async with session_factory()() as db:
        return await db.get(DbVoice, voice_id)


@router.post("/v1/tts", response_model=None)
async def sintetizar_lote(body: BatchRequest, db: DbSession, auth: AuthDep) -> Response:
    """Sintetiza o texto inteiro de uma vez.

    Com `delivery="bytes"` devolve o áudio no corpo; senão grava no bucket e devolve uma
    URL assinada que expira em `url_ttl_s`. Nos dois casos registra o job e o uso.
    """
    client, token = auth
    if not token.has_scope("tts:batch"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Escopo 'tts:batch' necessário",
        )

    orm_voice = await db.get(DbVoice, body.voice_id)
    # Voz privada de outro cliente responde como inexistente, para não vazar que existe.
    if orm_voice is None or not orm_voice.visivel_para(client.id, token.has_scope("admin")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voz não encontrada")

    inicio = time.monotonic()
    decision = await decide_engine(client.id, body.voice_id, orm_voice.elevenlabs_voice_id)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Motor indisponível",
        )

    voice = decision.voz(orm_voice)
    opcoes = SynthOptions(format=body.format, style=body.style_prompt or "neutro")
    dicionario = await load_dict(client.id)
    texto_normalizado = normalize(apply_dict(body.text, dicionario))

    audio = await sintetizar_em_partes(decision.engine, texto_normalizado, voice, opcoes)

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
        total_ms=(time.monotonic() - inicio) * 1000,
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

    chave_objeto = f"outputs/{request_id}.{_EXT[body.format]}"
    storage = get_storage()
    await storage.upload(chave_objeto, encoded, content_type)
    url = await storage.presigned_url(chave_objeto, body.url_ttl_s)

    job = BatchJob(
        id=request_id,
        client_id=client.id,
        voice_id=body.voice_id,
        status=BatchStatus.done,
        input_text=body.text,
        format=body.format,
        output_key=chave_objeto,
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
    """Streaming de TTS por WebSocket.

    O token vai na query porque o handshake do navegador não aceita cabeçalho. Aceita
    antes de autenticar para poder mandar o erro em JSON e fechar com código 4001/4003.
    """
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

    streams_active.inc()
    try:
        await _executar_stream(websocket, client, admin=api_token.has_scope("admin"))
    except Exception:
        streams_errors.labels(code="internal").inc()
        raise
    finally:
        streams_active.dec()


class _Leitor:
    """Lê o socket de uma conexão sem perder mensagem quando quem lê é cancelado.

    A leitura em andamento é uma tarefa própria, aguardada com `shield`: se a fala acaba
    e a tarefa que lia é cancelada logo depois de a mensagem chegar (o "start" da
    próxima fala, por exemplo), a mensagem fica guardada e sai na próxima leitura.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._pendente: asyncio.Task[str] | None = None

    async def receber(self, timeout: float | None = None) -> str:
        """Devolve a próxima mensagem de texto, retomando a leitura pendente se houver."""
        if self._pendente is None:
            self._pendente = asyncio.ensure_future(self._websocket.receive_text())
        tarefa = self._pendente
        try:
            mensagem = await asyncio.wait_for(asyncio.shield(tarefa), timeout)
        except asyncio.CancelledError:
            # Quem lia foi cancelado: a leitura fica guardada mesmo se já terminou, senão
            # a mensagem que acabou de chegar se perde.
            raise
        except BaseException:
            if tarefa.done():
                self._pendente = None  # a própria leitura falhou (socket fechado)
            raise
        self._pendente = None
        return mensagem

    def encerrar(self) -> None:
        if self._pendente is not None:
            self._pendente.cancel()
            self._pendente = None


async def _proximo_start(
    leitor: _Leitor, websocket: WebSocket, timeout: float | None
) -> StartMsg | None:
    """Espera o "start" da próxima fala. None: o cliente fechou, ficou ocioso ou errou."""
    try:
        mensagem_bruta = await leitor.receber(timeout)
        msg = parse_client_msg(mensagem_bruta)
    except (WebSocketDisconnect, ValidationError, TimeoutError):
        return None
    if isinstance(msg, StartMsg):
        return msg
    # "end" fora de uma fala é o jeito educado de encerrar; qualquer outra coisa é erro.
    if not isinstance(msg, EndMsg):
        await websocket.send_json({"type": "error", "code": "protocol"})
    return None


async def _executar_stream(
    websocket: WebSocket,
    client: Client,
    admin: bool = False,
) -> None:
    """Uma ou mais falas na mesma conexão.

    Depois do "done", o cliente pode mandar outro "start" e reaproveitar a conexão e a
    autenticação. A voz e o dicionário são carregados de novo só quando a voz muda; a
    decisão de motor é refeita a cada fala, porque a fila muda. Mandar "end" fora de uma
    fala, fechar o socket ou ficar ocioso encerra a conexão.
    """
    leitor = _Leitor(websocket)
    try:
        await _falas(websocket, client, admin, leitor)
    finally:
        leitor.encerrar()


async def _falas(websocket: WebSocket, client: Client, admin: bool, leitor: _Leitor) -> None:
    """Laço das falas de uma conexão: valida a voz, decide o motor e roda cada fala.

    A primeira fala espera o "start" sem limite de tempo; as seguintes, no máximo
    `_OCIOSO_ENTRE_FALAS_S`. Erro de voz ou de capacidade fecha a conexão.
    """
    start = await _proximo_start(leitor, websocket, timeout=None)
    if start is None:
        with contextlib.suppress(Exception):
            await websocket.close()
        return

    orm_voice: DbVoice | None = None
    dicionario: list[PronEntry] | None = None
    while start is not None:
        if orm_voice is None or orm_voice.id != start.voice_id:
            orm_voice = await _buscar_voz(start.voice_id)
            if orm_voice is None or not orm_voice.visivel_para(client.id, admin):
                await websocket.send_json({"type": "error", "code": "voice_not_found"})
                await websocket.close()
                return

        decision = await decide_engine(client.id, start.voice_id, orm_voice.elevenlabs_voice_id)
        if decision is None:
            await websocket.send_json({"type": "error", "code": "capacity"})
            await websocket.close(code=1013)
            return

        if dicionario is None:
            # Uma consulta por conexão, fora do caminho crítico do áudio.
            dicionario = await load_dict(client.id)
        streams_started.inc()
        continuar, proxima = await _executar_com_engine(
            websocket, client, start, orm_voice, decision, dicionario, leitor
        )
        if not continuar:
            return
        # O "start" seguinte pode ter chegado durante a fala; senão, espera por ele.
        start = proxima or await _proximo_start(leitor, websocket, timeout=_OCIOSO_ENTRE_FALAS_S)

    with contextlib.suppress(Exception):
        await websocket.close()


async def _executar_com_engine(
    websocket: WebSocket,
    client: Client,
    start: StartMsg,
    orm_voice: DbVoice,
    decision: RoutingDecision,
    dicionario: list[PronEntry],
    leitor: _Leitor | None = None,
) -> tuple[bool, StartMsg | None]:
    """Roda uma fala. Devolve (a conexão segue aberta?, "start" da próxima fala já lido).

    Três tarefas cooperam por filas:
    - leitura (`_reader`): recebe "text", "flush", "end" e "cancel" e alimenta a fila de
      texto;
    - áudio (`_send_audio`): consome o texto normalizado, chama o motor em streaming e
      põe os chunks na fila de envio;
    - envio (`_sender`): única tarefa que escreve no socket, na ordem da fila.

    A fala termina quando o motor esgota o texto (depois do "end") ou quando a leitura
    para (cancelamento, desconexão ou excesso de texto).
    """
    engine = decision.engine
    voice = decision.voz(orm_voice)
    opcoes = SynthOptions(
        speed=start.options.speed,
        style=start.options.style,
        format=start.format,
    )
    request_id = uuid.uuid4()

    # Fila de envio: bytes de áudio, dicts de controle e None para encerrar o envio.
    send_queue: asyncio.Queue[bytes | dict[str, object] | None] = asyncio.Queue()
    # Fila de texto: pedaços do cliente, _FLUSH e None para fim do texto.
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

    inicio = time.monotonic()
    ttfa_ms = 0.0
    total_audio_ms = 0.0
    total_chars = 0
    first_chunk = True
    # "flushed" só sai depois do áudio do texto anterior ao flush: o motor marca em cada
    # chunk quantos itens de texto terminaram de soar (AudioChunk.textos_concluidos).
    entregues = 0
    concluidos = 0
    # Para cada flush pendente, quantos itens de texto precisam ter soado antes do aviso.
    flushes: deque[int] = deque()

    async def _liberar_flushes() -> None:
        while flushes and flushes[0] <= concluidos:
            flushes.popleft()
            await send_queue.put({"type": "flushed"})

    async def _text_iter() -> AsyncIterator[str]:
        """Entrega ao motor o texto normalizado, frase a frase.

        Guarda em `pendente` o que ainda não fecha frase. Flush e fim do texto despejam
        o pendente mesmo sem pontuação. Cada item entregue conta em `entregues`.
        """
        nonlocal entregues
        pendente = ""
        while True:
            item = await text_queue.get()
            if item is None:
                if pendente and not cancelled.is_set():
                    normalizado = normalize(apply_dict(pendente, dicionario))
                    if normalizado:
                        entregues += 1
                        yield normalizado
                return
            if item is _FLUSH:
                if pendente:
                    normalizado = normalize(apply_dict(pendente, dicionario))
                    pendente = ""
                    if normalizado:
                        entregues += 1
                        yield normalizado
                flushes.append(entregues)
                await _liberar_flushes()
                continue
            assert isinstance(item, str)
            pronto, pendente = normalize_incremental(
                pendente + item, pre=lambda trecho: apply_dict(trecho, dicionario)
            )
            if pronto:
                entregues += 1
                yield pronto
            # Texto sem fim de frase se acumularia sem limite: cada pedaço reprocessaria
            # tudo (custo quadrático no loop) e a "frase" final seguraria o lock do motor.
            while len(pendente) > MAX_CARACTERES_SEGMENTO:
                cabeca, pendente = cortar_em_pausa(pendente)
                normalizado = normalize(apply_dict(cabeca, dicionario))
                if normalizado:
                    entregues += 1
                    yield normalizado

    falhou = False

    async def _send_audio() -> None:
        """Gera o áudio e enfileira os chunks; mede o TTFA e libera os flushes cumpridos."""
        nonlocal ttfa_ms, total_audio_ms, first_chunk, concluidos, falhou
        try:
            # aclosing: ao sair do loop o motor para a geração na hora, não só no GC.
            async with contextlib.aclosing(
                await engine.stream(_text_iter(), voice, opcoes)
            ) as geracao:
                async for chunk in geracao:
                    if cancelled.is_set():
                        break
                    if chunk.data:
                        if first_chunk:
                            ttfa_ms = (time.monotonic() - inicio) * 1000
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
    proxima_fala: StartMsg | None = None

    def _interromper() -> None:
        # Marca o cancelamento e solta o _text_iter que pode estar esperando texto.
        nonlocal cancelled_by_client
        cancelled.set()
        cancelled_by_client = True
        text_queue.put_nowait(None)

    async def _sender() -> None:
        # Depois do cancelamento, descarta o áudio que ainda estava na fila, mas deixa
        # passar as mensagens de controle (erro, por exemplo).
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
        nonlocal total_chars, proxima_fala
        encerrado = False
        # Sem leitor compartilhado (chamada direta, nos testes), lê com um próprio.
        leitor_da_fala = leitor or _Leitor(websocket)
        try:
            while True:
                mensagem_bruta = await leitor_da_fala.receber()
                try:
                    msg = parse_client_msg(mensagem_bruta)
                except ValidationError:
                    continue
                if isinstance(msg, CancelMsg):
                    _interromper()
                    return
                if encerrado:
                    if isinstance(msg, StartMsg):
                        # Próxima fala chegou antes do "done" desta: guarda e para de ler.
                        proxima_fala = msg
                        return
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
        # O motor acabando encerra a fala normalmente; a leitura acabando antes significa
        # cancelamento, desconexão, texto longo demais ou o "start" da próxima fala.
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
        # Só agora encerra o envio, para o "done" sair depois de todo o áudio enfileirado.
        await send_queue.put(None)
        with contextlib.suppress(Exception):
            await sender_task

    if falhou and not cancelled_by_client:
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
        return False, None

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
        total_ms = (time.monotonic() - inicio) * 1000
        # Gravação do uso fora do caminho crítico: a próxima fala não espera o banco.
        tarefa_uso = asyncio.create_task(
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
        _tarefas_uso.add(tarefa_uso)
        tarefa_uso.add_done_callback(_tarefas_uso.discard)
        return True, proxima_fala
    # Cancelamento (do cliente, por desconexão ou por texto longo) fecha a conexão.
    streams_cancelled.inc()
    with contextlib.suppress(Exception):
        await websocket.close()
    return False, None
