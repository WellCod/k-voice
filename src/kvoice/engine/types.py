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
