"""Testa QwenTTSEngine com um modelo stub (sem GPU)."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import Any

import numpy as np
import pytest

from kvoice.engine.qwen import QwenTTSEngine
from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, Voice

SR = 24_000
VOICE = Voice(id="v_ana", name="Ana")
VOICE_CLONE = Voice(id="v_clone", name="Clone", ref_audio="/tmp/ref.wav", ref_text="referência")
OPTS = SynthOptions()


class _FakeModel:
    def generate_voice_design_streaming(
        self, *, text: str, language: str, instruct: str, chunk_size: int
    ) -> Generator[tuple[Any, int, dict[str, Any]], None, None]:
        for _ in range(3):
            yield np.zeros(SR // 2, dtype=np.float32), SR, {}

    def generate_voice_clone_streaming(
        self,
        *,
        text: str,
        language: str,
        ref_audio: str,
        ref_text: str,
        chunk_size: int,
    ) -> Generator[tuple[Any, int, dict[str, Any]], None, None]:
        for _ in range(2):
            yield np.ones(SR // 4, dtype=np.float32) * 0.5, SR, {}


@pytest.fixture
def engine() -> QwenTTSEngine:
    e = QwenTTSEngine()
    e._model = _FakeModel()
    return e


async def _texto(s: str):  # type: ignore[return]  # async generator
    yield s


async def test_capacity_inicial(engine: QwenTTSEngine) -> None:
    cap = engine.capacity()
    assert isinstance(cap, Capacity)
    assert cap.active_streams == 0
    assert cap.queued == 0
    assert cap.rtf_recent is None


async def test_stream_retorna_chunks(engine: QwenTTSEngine) -> None:
    chunks: list[AudioChunk] = []
    async for chunk in await engine.stream(_texto("olá"), VOICE, OPTS):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert all(isinstance(c, AudioChunk) for c in chunks)
    assert all(c.sample_rate == SR for c in chunks)


async def test_stream_pcm_16bit(engine: QwenTTSEngine) -> None:
    async for chunk in await engine.stream(_texto("teste"), VOICE, OPTS):
        # SR // 2 amostras × 2 bytes/amostra
        assert len(chunk.data) == (SR // 2) * 2
        break


async def test_stream_duracao(engine: QwenTTSEngine) -> None:
    async for chunk in await engine.stream(_texto("duração"), VOICE, OPTS):
        assert chunk.duration_ms == pytest.approx(500.0, abs=1.0)
        break


async def test_stream_com_clonagem(engine: QwenTTSEngine) -> None:
    chunks: list[AudioChunk] = []
    async for chunk in await engine.stream(_texto("clone"), VOICE_CLONE, OPTS):
        chunks.append(chunk)
    assert len(chunks) == 2


async def test_stream_active_contador(engine: QwenTTSEngine) -> None:
    assert engine._active == 0
    async for _ in await engine.stream(_texto("x"), VOICE, OPTS):
        pass
    assert engine._active == 0


async def test_stream_cancelamento(engine: QwenTTSEngine) -> None:
    gen = await engine.stream(_texto("cancelar"), VOICE, OPTS)
    count = 0
    async for _ in gen:
        count += 1
        await gen.aclose()
        break

    await asyncio.sleep(0.05)  # thread percebe o cancel
    assert count == 1
    assert engine._active == 0


async def test_synthesize_retorna_audio(engine: QwenTTSEngine) -> None:
    audio = await engine.synthesize("olá mundo", VOICE, OPTS)
    assert isinstance(audio, Audio)
    assert len(audio.data) > 0
    assert audio.sample_rate == SR
    assert audio.duration_ms > 0
    assert audio.ttfa_ms > 0


async def test_synthesize_concatena_chunks(engine: QwenTTSEngine) -> None:
    audio = await engine.synthesize("texto", VOICE, OPTS)
    # 3 chunks × (SR // 2) amostras × 2 bytes
    assert len(audio.data) == 3 * (SR // 2) * 2


async def test_load_sem_dependencia_levanta_importerror(engine: QwenTTSEngine) -> None:
    engine._model = None
    with pytest.raises(ImportError, match="faster-qwen3-tts"):
        engine.load()
