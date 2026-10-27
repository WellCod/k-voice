"""Testes do plugin LiveKit para k-voice TTS.

Requer o grupo livekit instalado:
    uv run --group livekit pytest tests/livekit/

Em CI padrão (sem --group livekit), os testes são pulados automaticamente.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

livekit_agents = pytest.importorskip("livekit.agents")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pcm_chunk(ms: int = 20, sample_rate: int = 24000) -> bytes:
    samples = sample_rate * ms // 1000
    return b"\x00" * (samples * 2)  # 16-bit mono


class _MockEmitter:
    """AudioEmitter mínimo para testes."""

    def __init__(self) -> None:
        self.initialized = False
        self.pushed = b""
        self.segments: list[str] = []
        self.ended = False

    def initialize(self, **_: Any) -> None:
        self.initialized = True

    def push(self, data: bytes) -> None:
        self.pushed += data

    def push_frame(self, frame: Any) -> None:
        pass

    def start_segment(self, *, segment_id: str) -> None:
        self.segments.append(segment_id)

    def end_segment(self) -> None:
        pass

    def end_input(self) -> None:
        self.ended = True

    async def join(self) -> None:
        pass

    async def aclose(self) -> None:
        pass


def _make_ws(messages: list[Any]) -> Any:
    """Mock de websockets.ClientConnection que emite mensagens pré-definidas."""

    async def _recv_gen() -> Any:
        for m in messages:
            yield m

    ws = MagicMock()
    ws.send = AsyncMock()
    ws.__aenter__ = AsyncMock(return_value=ws)
    ws.__aexit__ = AsyncMock(return_value=False)
    ws.__aiter__ = MagicMock(return_value=_recv_gen())
    ws.recv = AsyncMock(side_effect=messages)
    return ws


# ---------------------------------------------------------------------------
# Testes de ChunkedStream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunked_stream_envia_texto_e_recebe_audio() -> None:
    from kvoice.livekit.tts import TTS, ChunkedStream

    chunk = _pcm_chunk()
    started = json.dumps({"type": "started", "request_id": "r1", "engine": "fake"})
    done = json.dumps({"type": "done", "ttfa_ms": 10.0, "audio_ms": 20.0})

    ws = _make_ws([started, chunk, done])

    tts = TTS(base_url="ws://localhost:8000", token="tok", voice_id="v_ana")
    stream = ChunkedStream(tts=tts, input_text="Olá, mundo.", conn_options=None)
    emitter = _MockEmitter()

    with patch("websockets.connect", return_value=ws):
        await stream._run(emitter)

    assert emitter.initialized
    assert emitter.pushed == chunk
    assert emitter.ended

    # Verifica que os pedidos foram enviados na ordem correta.
    calls = [json.loads(c.args[0]) for c in ws.send.call_args_list]
    assert calls[0] == {"type": "start", "voice_id": "v_ana", "format": "pcm_24000"}
    assert calls[1] == {"type": "text", "text": "Olá, mundo."}
    assert calls[2] == {"type": "end"}


@pytest.mark.asyncio
async def test_chunked_stream_erro_levanta_exception() -> None:
    from kvoice.livekit.tts import TTS, ChunkedStream

    started = json.dumps({"type": "started", "request_id": "r1", "engine": "fake"})
    error = json.dumps({"type": "error", "code": "engine"})

    ws = _make_ws([started, error])

    tts = TTS(base_url="ws://localhost:8000", token="tok", voice_id="v_ana")
    stream = ChunkedStream(tts=tts, input_text="Texto.", conn_options=None)
    emitter = _MockEmitter()

    with patch("websockets.connect", return_value=ws), pytest.raises(RuntimeError, match="engine"):
        await stream._run(emitter)


# ---------------------------------------------------------------------------
# Testes de SynthesizeStream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_stream_tokens_e_flush() -> None:
    """Tokens chegam via _input_ch; _FlushSentinel dispara flush no k-voice."""
    from livekit.agents import tts as agents_tts

    from kvoice.livekit.tts import TTS, SynthesizeStream

    chunk = _pcm_chunk()
    started = json.dumps({"type": "started", "request_id": "r1", "engine": "fake"})
    flushed = json.dumps({"type": "flushed"})
    done = json.dumps({"type": "done", "ttfa_ms": 15.0, "audio_ms": 40.0})

    ws = _make_ws([started, chunk, flushed, done])

    tts = TTS(base_url="ws://localhost:8000", token="tok", voice_id="v_ana")
    stream = SynthesizeStream(tts=tts, conn_options=None)
    emitter = _MockEmitter()

    # Alimenta o _input_ch com texto e sentinel antes de rodar.
    stream._input_ch.send_nowait("Olá")
    stream._input_ch.send_nowait(" mundo.")
    stream._input_ch.send_nowait(agents_tts.SynthesizeStream._FlushSentinel())
    stream._input_ch.close()

    with patch("websockets.connect", return_value=ws):
        await stream._run(emitter)

    assert emitter.initialized
    assert emitter.pushed == chunk
    assert len(emitter.segments) >= 1
    assert emitter.ended

    sent = [json.loads(c.args[0]) for c in ws.send.call_args_list]
    tipos = [m["type"] for m in sent]
    assert tipos[0] == "start"
    assert "text" in tipos
    assert tipos[-1] == "end"
    # Flush sentinel → mensagem text com flush=True
    flush_msgs = [m for m in sent if m.get("flush") is True]
    assert len(flush_msgs) == 1


@pytest.mark.asyncio
async def test_synthesize_stream_cancel_envia_cancel() -> None:
    """CancelledError → k-voice recebe cancel antes de propagar."""
    from kvoice.livekit.tts import TTS, SynthesizeStream

    started = json.dumps({"type": "started", "request_id": "r1", "engine": "fake"})
    chunk = _pcm_chunk()

    async def _slow_iter() -> Any:
        yield started
        yield chunk
        await asyncio.sleep(10)  # simula stream lento

    ws = MagicMock()
    ws.send = AsyncMock()
    ws.__aenter__ = AsyncMock(return_value=ws)
    ws.__aexit__ = AsyncMock(return_value=False)
    ws.recv = AsyncMock(return_value=started)
    ws.__aiter__ = MagicMock(return_value=_slow_iter())

    tts = TTS(base_url="ws://localhost:8000", token="tok", voice_id="v_ana")
    stream = SynthesizeStream(tts=tts, conn_options=None)
    emitter = _MockEmitter()

    stream._input_ch.send_nowait("Texto longo")

    async def _run_and_cancel() -> None:
        task = asyncio.create_task(stream._run(emitter))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with patch("websockets.connect", return_value=ws):
        await _run_and_cancel()

    cancel_msgs = [
        json.loads(c.args[0])
        for c in ws.send.call_args_list
        if json.loads(c.args[0]).get("type") == "cancel"
    ]
    assert len(cancel_msgs) == 1
