from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    language: str = "pt-BR"
    model_id: str | None = None  # speaker/modelo específico do engine (ex: "serena" no Qwen3-TTS)
    ref_audio: str | None = None
    ref_text: str | None = None
    style_prompt: str | None = None


@dataclass(frozen=True)
class SynthOptions:
    speed: float = 1.0
    style: str = "neutro"
    format: str = "pcm_24000"


@dataclass(frozen=True)
class AudioChunk:
    data: bytes  # PCM 16-bit little-endian mono
    sample_rate: int
    duration_ms: float
    # Quantos itens do iterador de texto terminaram de soar com este chunk.
    # O WebSocket usa isso para mandar "flushed" depois do áudio, não antes.
    textos_concluidos: int = 0


def fatiar_pcm(
    data: bytes, sample_rate: int, chunk_samples: int, textos_concluidos: int = 0
) -> list[AudioChunk]:
    """Divide PCM em chunks; o último carrega textos_concluidos (vazio vira um chunk vazio)."""
    step = chunk_samples * 2
    partes = [data[i : i + step] for i in range(0, len(data), step)] or [b""]
    return [
        AudioChunk(
            data=parte,
            sample_rate=sample_rate,
            duration_ms=(len(parte) // 2) / sample_rate * 1000,
            textos_concluidos=textos_concluidos if i == len(partes) - 1 else 0,
        )
        for i, parte in enumerate(partes)
    ]


@dataclass(frozen=True)
class Audio:
    data: bytes  # PCM 16-bit little-endian mono
    sample_rate: int
    duration_ms: float
    ttfa_ms: float


@dataclass
class Capacity:
    active_streams: int
    queued: int
    rtf_recent: float | None


@runtime_checkable
class TTSEngine(Protocol):
    name: str
    sample_rate: int

    async def stream(
        self,
        text: AsyncIterator[str],
        voice: Voice,
        opts: SynthOptions,
    ) -> AsyncGenerator[AudioChunk, None]: ...

    async def synthesize(
        self,
        text: str,
        voice: Voice,
        opts: SynthOptions,
    ) -> Audio: ...

    def capacity(self) -> Capacity: ...
