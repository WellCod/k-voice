"""Engine stub para testes locais sem GPU nem ElevenLabs.

Gera um tom senoidal simples proporcional ao comprimento do texto,
simulando a duração esperada de áudio real.
"""

from __future__ import annotations

import asyncio
import math
import struct
from collections.abc import AsyncGenerator, AsyncIterator

from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, Voice

_SAMPLE_RATE = 24_000
_CHUNK_SAMPLES = 4_800  # 200 ms
_CHARS_PER_SECOND = 15.0  # velocidade estimada de fala
_FREQ = 440.0  # Hz — La 4


def _gerar_tom(n_samples: int, freq: float = _FREQ, sample_rate: int = _SAMPLE_RATE) -> bytes:
    frames = []
    for i in range(n_samples):
        t = i / sample_rate
        sample = int(32767 * 0.3 * math.sin(2 * math.pi * freq * t))
        frames.append(struct.pack("<h", sample))
    return b"".join(frames)


class StubEngine:
    """TTSEngine que gera áudio sintético para testes locais."""

    name = "stub"
    sample_rate = _SAMPLE_RATE

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio:
        n_chars = max(len(text), 1)
        duration_s = n_chars / _CHARS_PER_SECOND / opts.speed
        n_samples = int(duration_s * _SAMPLE_RATE)
        data = _gerar_tom(n_samples)
        return Audio(
            data=data,
            sample_rate=_SAMPLE_RATE,
            duration_ms=duration_s * 1000,
            ttfa_ms=0.0,
        )

    async def stream(
        self,
        text: AsyncIterator[str],
        voice: Voice,
        opts: SynthOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        full_text = ""
        async for chunk in text:
            full_text += chunk
        return self._stream_impl(full_text, opts)

    async def _stream_impl(
        self, full_text: str, opts: SynthOptions
    ) -> AsyncGenerator[AudioChunk, None]:
        n_chars = max(len(full_text), 1)
        duration_s = n_chars / _CHARS_PER_SECOND / opts.speed
        n_samples = int(duration_s * _SAMPLE_RATE)
        produced = 0
        while produced < n_samples:
            end = min(produced + _CHUNK_SAMPLES, n_samples)
            chunk_samples = end - produced
            data = _gerar_tom(chunk_samples)
            chunk_ms = chunk_samples / _SAMPLE_RATE * 1000
            yield AudioChunk(data=data, sample_rate=_SAMPLE_RATE, duration_ms=chunk_ms)
            produced = end
            await asyncio.sleep(0)

    def capacity(self) -> Capacity:
        return Capacity(active_streams=0, queued=0, rtf_recent=None)
