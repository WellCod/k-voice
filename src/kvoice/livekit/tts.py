"""Plugin LiveKit Agents para o k-voice TTS com streaming e cancelamento.

Uso:
    from kvoice.livekit import TTS, create_tts

    # TTS direto
    tts = TTS(base_url="ws://localhost:8000", token="tok", voice_id="v_ana")

    # Com fallback para ElevenLabs via FallbackAdapter
    tts = create_tts(
        base_url="ws://...",
        token="tok",
        voice_id="v_ana",
        elevenlabs_api_key="...",
        elevenlabs_voice_id="...",
    )

Conexões: depois do "done" a conexão volta para um pool e a próxima fala a reaproveita,
sem handshake nem autenticação de novo. Fala cancelada (barge-in) ou com erro fecha a
conexão; conexão que caiu ou ficou ociosa no pool é trocada por uma nova sem virar
erro, para não acionar o fallback por nada.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import websockets
from livekit.agents import tts as agents_tts  # type: ignore[import-untyped]
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State

_SAMPLE_RATE = 24000
_NUM_CHANNELS = 1
# O servidor fecha a conexão depois de 60 s sem fala; o pool descarta antes disso.
_OCIOSA_MAX_S = 45.0
_POOL_MAX = 4
_TIMEOUT_CONEXAO_S = 5.0


@dataclass
class _Opts:
    base_url: str
    token: str
    voice_id: str


class _Pool:
    """Conexões ociosas com o k-voice, reaproveitadas entre falas."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._ociosas: list[tuple[Any, float]] = []

    async def abrir(self) -> Any:
        return await websockets.connect(self._url, open_timeout=_TIMEOUT_CONEXAO_S)

    def pegar(self) -> Any | None:
        agora = time.monotonic()
        while self._ociosas:
            ws, desde = self._ociosas.pop()
            if ws.state is State.OPEN and agora - desde < _OCIOSA_MAX_S:
                return ws
            asyncio.ensure_future(_fechar(ws))
        return None

    def devolver(self, ws: Any) -> None:
        if ws.state is State.OPEN and len(self._ociosas) < _POOL_MAX:
            self._ociosas.append((ws, time.monotonic()))
        else:
            asyncio.ensure_future(_fechar(ws))

    async def fechar_todas(self) -> None:
        ociosas, self._ociosas = self._ociosas, []
        for ws, _ in ociosas:
            await _fechar(ws)


async def _fechar(ws: Any) -> None:
    with contextlib.suppress(Exception):
        await ws.close()


class TTS(agents_tts.TTS):
    """TTS k-voice para LiveKit Agents com streaming incremental."""

    def __init__(
        self,
        *,
        base_url: str = "ws://localhost:8000",
        token: str,
        voice_id: str,
    ) -> None:
        super().__init__(
            capabilities=agents_tts.TTSCapabilities(
                streaming=True,
                aligned_transcript=False,
            ),
            sample_rate=_SAMPLE_RATE,
            num_channels=_NUM_CHANNELS,
        )
        self._opts = _Opts(
            base_url=base_url.rstrip("/"),
            token=token,
            voice_id=voice_id,
        )
        self._pool = _Pool(f"{self._opts.base_url}/v1/tts/stream?token={self._opts.token}")

    @property
    def provider(self) -> str:
        return "kvoice"

    def synthesize(self, text: str, **kwargs: Any) -> ChunkedStream:
        return ChunkedStream(tts=self, input_text=text, conn_options=kwargs.get("conn_options"))

    def stream(self, **kwargs: Any) -> SynthesizeStream:
        return SynthesizeStream(tts=self, conn_options=kwargs.get("conn_options"))

    async def aclose(self) -> None:
        await self._pool.fechar_todas()
        await super().aclose()

    async def _iniciar_fala(self) -> Any:
        """Conexão com a fala iniciada ("started" recebido).

        Tenta uma conexão do pool; se ela caiu enquanto esperava, abre outra. Só a falha
        de uma conexão nova vira erro (e aí o FallbackAdapter assume).
        """
        start = json.dumps(
            {"type": "start", "voice_id": self._opts.voice_id, "format": "pcm_24000"}
        )
        reaproveitada = self._pool.pegar()
        for ws in (reaproveitada, None):
            if ws is None:
                ws = await self._pool.abrir()
            try:
                await ws.send(start)
                first = json.loads(await ws.recv())
            except ConnectionClosed:
                await _fechar(ws)
                if ws is reaproveitada:
                    continue
                raise
            if first.get("type") != "started":
                await _fechar(ws)
                raise RuntimeError(f"k-voice: resposta inesperada ao start: {first}")
            return ws
        raise RuntimeError("k-voice: não foi possível iniciar a fala")  # pragma: no cover

    def _terminar_fala(self, ws: Any, ok: bool) -> None:
        if ok:
            self._pool.devolver(ws)
        else:
            asyncio.ensure_future(_fechar(ws))


class ChunkedStream(agents_tts.ChunkedStream):
    """Síntese de texto completo via WebSocket do k-voice."""

    def __init__(self, *, tts: TTS, input_text: str, conn_options: Any = None) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)

    async def _run(self, output_emitter: Any) -> None:
        tts: TTS = self._tts  # type: ignore[assignment]
        ws = await tts._iniciar_fala()
        ok = False
        try:
            output_emitter.initialize(
                request_id=str(uuid.uuid4()),
                sample_rate=_SAMPLE_RATE,
                num_channels=_NUM_CHANNELS,
                mime_type="audio/pcm",
                stream=False,
            )
            await ws.send(json.dumps({"type": "text", "text": self._input_text}))
            await ws.send(json.dumps({"type": "end"}))

            async for raw in ws:
                if isinstance(raw, bytes):
                    output_emitter.push(raw)
                elif isinstance(raw, str):
                    msg = json.loads(raw)
                    if msg.get("type") == "done":
                        ok = True
                        break
                    if msg.get("type") == "error":
                        raise RuntimeError(f"k-voice error: {msg.get('code')}")
        finally:
            tts._terminar_fala(ws, ok)

        output_emitter.end_input()
        await output_emitter.join()


class SynthesizeStream(agents_tts.SynthesizeStream):
    """Síntese incremental com texto chegando em tokens do LLM."""

    def __init__(self, *, tts: TTS, conn_options: Any = None) -> None:
        super().__init__(tts=tts, conn_options=conn_options)

    async def _run(self, output_emitter: Any) -> None:
        tts: TTS = self._tts  # type: ignore[assignment]
        ws = await tts._iniciar_fala()
        ok = False

        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=_SAMPLE_RATE,
            num_channels=_NUM_CHANNELS,
            mime_type="audio/pcm",
            stream=True,
        )
        output_emitter.start_segment(segment_id=str(uuid.uuid4()))

        async def _send() -> None:
            async for item in self._input_ch:
                if isinstance(item, agents_tts.SynthesizeStream._FlushSentinel):
                    # Força flush do normalizador e sinaliza fim de segmento.
                    await ws.send(json.dumps({"type": "text", "text": "", "flush": True}))
                else:
                    await ws.send(json.dumps({"type": "text", "text": item}))
            await ws.send(json.dumps({"type": "end"}))

        send_task = asyncio.create_task(_send())
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    output_emitter.push(raw)
                elif isinstance(raw, str):
                    msg = json.loads(raw)
                    t = msg.get("type")
                    if t == "flushed":
                        output_emitter.end_segment()
                        output_emitter.start_segment(segment_id=str(uuid.uuid4()))
                    elif t == "done":
                        # O "end" já saiu (o servidor só manda "done" depois dele); a conexão
                        # só volta ao pool com o envio encerrado.
                        await send_task
                        ok = True
                        break
                    elif t == "error":
                        raise RuntimeError(f"k-voice error: {msg.get('code')}")
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await ws.send(json.dumps({"type": "cancel"}))
            raise
        finally:
            if not send_task.done():
                send_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await send_task
            tts._terminar_fala(ws, ok)

        output_emitter.end_segment()
        output_emitter.end_input()
        await output_emitter.join()
