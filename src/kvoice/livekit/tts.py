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
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

import websockets
from livekit.agents import tts as agents_tts  # type: ignore[import-untyped]

_SAMPLE_RATE = 24000
_NUM_CHANNELS = 1


@dataclass
class _Opts:
    base_url: str
    token: str
    voice_id: str


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

    @property
    def provider(self) -> str:
        return "kvoice"

    def synthesize(self, text: str, **kwargs: Any) -> ChunkedStream:
        return ChunkedStream(tts=self, input_text=text, conn_options=kwargs.get("conn_options"))

    def stream(self, **kwargs: Any) -> SynthesizeStream:
        return SynthesizeStream(tts=self, conn_options=kwargs.get("conn_options"))


class ChunkedStream(agents_tts.ChunkedStream):
    """Síntese de texto completo via WebSocket do k-voice."""

    def __init__(self, *, tts: TTS, input_text: str, conn_options: Any = None) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)

    async def _run(self, output_emitter: Any) -> None:
        opts: _Opts = self._tts._opts  # type: ignore[attr-defined]
        ws_url = f"{opts.base_url}/v1/tts/stream?token={opts.token}"
        request_id = str(uuid.uuid4())

        async with websockets.connect(ws_url) as ws:
            await ws.send(
                json.dumps({"type": "start", "voice_id": opts.voice_id, "format": "pcm_24000"})
            )
            first = json.loads(await ws.recv())
            if first.get("type") != "started":
                raise RuntimeError(f"k-voice: resposta inesperada ao start: {first}")

            output_emitter.initialize(
                request_id=request_id,
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
                        break
                    if msg.get("type") == "error":
                        raise RuntimeError(f"k-voice error: {msg.get('code')}")

        output_emitter.end_input()
        await output_emitter.join()


class SynthesizeStream(agents_tts.SynthesizeStream):
    """Síntese incremental com texto chegando em tokens do LLM."""

    def __init__(self, *, tts: TTS, conn_options: Any = None) -> None:
        super().__init__(tts=tts, conn_options=conn_options)

    async def _run(self, output_emitter: Any) -> None:
        opts: _Opts = self._tts._opts  # type: ignore[attr-defined]
        ws_url = f"{opts.base_url}/v1/tts/stream?token={opts.token}"
        request_id = str(uuid.uuid4())

        async with websockets.connect(ws_url) as ws:
            await ws.send(
                json.dumps({"type": "start", "voice_id": opts.voice_id, "format": "pcm_24000"})
            )
            first = json.loads(await ws.recv())
            if first.get("type") != "started":
                raise RuntimeError(f"k-voice: resposta inesperada ao start: {first}")

            output_emitter.initialize(
                request_id=request_id,
                sample_rate=_SAMPLE_RATE,
                num_channels=_NUM_CHANNELS,
                mime_type="audio/pcm",
                stream=True,
            )

            segment_id = str(uuid.uuid4())
            output_emitter.start_segment(segment_id=segment_id)

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
                            segment_id = str(uuid.uuid4())
                            output_emitter.start_segment(segment_id=segment_id)
                        elif t == "done":
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

        output_emitter.end_segment()
        output_emitter.end_input()
        await output_emitter.join()
