"""Engine stub para testes locais sem GPU nem ElevenLabs.

Gera um tom senoidal simples proporcional ao comprimento do texto,
simulando a duração esperada de áudio real.
"""

from __future__ import annotations

import asyncio
import math
import struct
from collections.abc import AsyncGenerator, AsyncIterator

from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, Voice, fatiar_pcm

_SAMPLE_RATE = 24_000
_CHUNK_SAMPLES = 4_800  # 200 ms
_CHARS_PER_SECOND = 15.0  # velocidade estimada de fala
_FREQ = 440.0  # Hz — La 4


def _gerar_tom(
    n_amostras: int, frequencia: float = _FREQ, taxa_amostragem: int = _SAMPLE_RATE
) -> bytes:
    """PCM 16-bit de uma senoide a 30% da amplitude máxima."""
    quadros = []
    for indice in range(n_amostras):
        instante_s = indice / taxa_amostragem
        amostra = int(32767 * 0.3 * math.sin(2 * math.pi * frequencia * instante_s))
        quadros.append(struct.pack("<h", amostra))
    return b"".join(quadros)


class StubEngine:
    """TTSEngine que gera áudio sintético para testes locais."""

    name = "stub"
    sample_rate = _SAMPLE_RATE

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio:
        n_caracteres = max(len(text), 1)
        duracao_s = n_caracteres / _CHARS_PER_SECOND / opts.speed
        n_amostras = int(duracao_s * _SAMPLE_RATE)
        data = _gerar_tom(n_amostras)
        return Audio(
            data=data,
            sample_rate=_SAMPLE_RATE,
            duration_ms=duracao_s * 1000,
            ttfa_ms=0.0,
        )

    async def stream(
        self,
        text: AsyncIterator[str],
        voice: Voice,
        opts: SynthOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        return self._stream_impl(text, opts)

    async def _stream_impl(
        self, text: AsyncIterator[str], opts: SynthOptions
    ) -> AsyncGenerator[AudioChunk, None]:
        async for frase in text:
            n_caracteres = max(len(frase), 1)
            n_amostras = int(n_caracteres / _CHARS_PER_SECOND / opts.speed * _SAMPLE_RATE)
            data = _gerar_tom(n_amostras)
            for chunk in fatiar_pcm(data, _SAMPLE_RATE, _CHUNK_SAMPLES, textos_concluidos=1):
                yield chunk
                await asyncio.sleep(0)

    def capacity(self) -> Capacity:
        return Capacity(active_streams=0, queued=0, rtf_recent=None)
