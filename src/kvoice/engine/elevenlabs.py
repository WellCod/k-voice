"""Engine de fallback para a API da ElevenLabs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, Voice

_SAMPLE_RATE = 24_000
_CHUNK_SAMPLES = 4_800  # 200 ms a 24 kHz


class ElevenLabsEngine:
    """TTSEngine que delega para a API da ElevenLabs."""

    name: str = "elevenlabs"
    sample_rate: int = _SAMPLE_RATE

    def __init__(self, api_key: str) -> None:
        try:
            from elevenlabs import ElevenLabs as _EL
        except ImportError as exc:
            raise ImportError("elevenlabs não instalado; instale com: uv add elevenlabs") from exc
        self._client = _EL(api_key=api_key)
        self._active = 0

    def capacity(self) -> Capacity:
        return Capacity(active_streams=self._active, queued=0, rtf_recent=None)

    def _convert_sync(self, voice_id: str, text: str) -> bytes:
        audio_iter = self._client.text_to_speech.stream(
            voice_id=voice_id,
            text=text,
            model_id="eleven_turbo_v2_5",
            output_format="pcm_24000",
        )
        return b"".join(audio_iter)

    async def stream(
        self,
        text: AsyncIterator[str],
        voice: Voice,
        opts: SynthOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        parts: list[str] = []
        async for t in text:
            parts.append(t)
        full_text = "".join(parts)
        return self._stream_impl(full_text, voice)

    async def _stream_impl(
        self,
        text: str,
        voice: Voice,
    ) -> AsyncGenerator[AudioChunk, None]:
        if not text.strip():
            return

        self._active += 1
        try:
            loop = asyncio.get_running_loop()
            audio_bytes = await loop.run_in_executor(None, self._convert_sync, voice.id, text)
        finally:
            self._active -= 1

        chunk_bytes = _CHUNK_SAMPLES * 2  # 16-bit mono
        offset = 0
        while offset < len(audio_bytes):
            chunk = audio_bytes[offset : offset + chunk_bytes]
            offset += chunk_bytes
            duration_ms = (len(chunk) // 2) / _SAMPLE_RATE * 1000
            yield AudioChunk(data=chunk, sample_rate=_SAMPLE_RATE, duration_ms=duration_ms)

    async def synthesize(
        self,
        text: str,
        voice: Voice,
        opts: SynthOptions,
    ) -> Audio:
        self._active += 1
        try:
            loop = asyncio.get_running_loop()
            audio_bytes = await loop.run_in_executor(None, self._convert_sync, voice.id, text)
        finally:
            self._active -= 1

        duration_ms = (len(audio_bytes) // 2) / _SAMPLE_RATE * 1000
        return Audio(
            data=audio_bytes,
            sample_rate=_SAMPLE_RATE,
            duration_ms=duration_ms,
            ttfa_ms=0.0,
        )


_instance: ElevenLabsEngine | None = None


def get_elevenlabs_engine() -> ElevenLabsEngine | None:
    """Retorna instância singleton; None se api_key não configurada ou SDK não instalado."""
    global _instance
    if _instance is not None:
        return _instance
    from kvoice.settings import get_settings

    api_key = get_settings().elevenlabs_api_key
    if not api_key:
        return None
    try:
        _instance = ElevenLabsEngine(api_key=api_key)
    except ImportError:
        return None
    return _instance


def reset_elevenlabs_engine() -> None:
    """Zera o singleton — usado em testes."""
    global _instance
    _instance = None
