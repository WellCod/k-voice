"""Engine Qwen3-TTS — CustomVoice (preset) e Base (clonagem de voz)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

import numpy as np

from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, Voice

_SAMPLE_RATE = 24_000
_CHUNK_SAMPLES = 4_800  # 200 ms a 24 kHz
_DEFAULT_SPEAKER = "vivian"
_DEFAULT_LANGUAGE = "portuguese"

# ISO/BCP-47 → nome completo esperado pelo Qwen3-TTS
_LANGUAGE_MAP: dict[str, str] = {
    "pt": "portuguese",
    "pt-BR": "portuguese",
    "pt-PT": "portuguese",
    "en": "english",
    "en-US": "english",
    "es": "spanish",
    "fr": "french",
    "de": "german",
    "it": "italian",
    "ja": "japanese",
    "ko": "korean",
    "ru": "russian",
    "zh": "chinese",
    "zh-CN": "chinese",
}

# Speakers disponíveis no modelo CustomVoice (0.6B e 1.7B)
_VALID_SPEAKERS = frozenset(
    {"aiden", "dylan", "eric", "ono_anna", "ryan", "serena", "sohee", "uncle_fu", "vivian"}
)


def _pcm_from_wav(wav: np.ndarray) -> bytes:
    return (wav.flatten() * 32767).clip(-32767, 32767).astype(np.int16).tobytes()


def _resolve_language(voice: Voice) -> str:
    return _LANGUAGE_MAP.get(voice.language, _DEFAULT_LANGUAGE)


class Qwen3TTSEngine:
    """TTSEngine com suporte a vozes preset (CustomVoice) e clonagem (Base)."""

    name = "qwen3-tts"
    sample_rate = _SAMPLE_RATE

    def __init__(
        self,
        custom_model: object,
        base_model_id: str,
        speaker: str = _DEFAULT_SPEAKER,
    ) -> None:
        self._custom_model = custom_model
        self._base_model_id = base_model_id
        self._base_model: object | None = None
        self._base_loading = False
        self._speaker = speaker
        self._active = 0
        self._lock = asyncio.Semaphore(1)  # CPU: serializa inferências
        self._base_lock = asyncio.Semaphore(1)

    @classmethod
    def load(
        cls,
        custom_model_id: str,
        base_model_id: str,
        speaker: str = _DEFAULT_SPEAKER,
    ) -> Qwen3TTSEngine:
        import torch
        from qwen_tts import Qwen3TTSModel

        model = Qwen3TTSModel.from_pretrained(
            custom_model_id,
            device_map="cpu",
            dtype=torch.float32,
        )
        return cls(model, base_model_id, speaker)

    def _ensure_base_model(self) -> object:
        """Carrega o modelo Base na primeira chamada de clonagem (lazy)."""
        if self._base_model is not None:
            return self._base_model
        import torch
        from qwen_tts import Qwen3TTSModel

        self._base_model = Qwen3TTSModel.from_pretrained(
            self._base_model_id,
            device_map="cpu",
            dtype=torch.float32,
        )
        return self._base_model

    # ------------------------------------------------------------------
    # Inferência preset (CustomVoice)
    # ------------------------------------------------------------------

    def _speaker_for(self, voice: Voice) -> str:
        candidate = (voice.model_id or "").lower().replace(" ", "_")
        return candidate if candidate in _VALID_SPEAKERS else self._speaker

    def _infer_preset(
        self, text: str, speaker: str, language: str, instruct: str | None
    ) -> tuple[list[np.ndarray], int]:
        from qwen_tts import Qwen3TTSModel

        assert isinstance(self._custom_model, Qwen3TTSModel)
        return self._custom_model.generate_custom_voice(  # type: ignore[no-any-return]
            text=text,
            speaker=speaker,
            language=language,
            instruct=instruct or None,
        )

    # ------------------------------------------------------------------
    # Inferência por clonagem (Base)
    # ------------------------------------------------------------------

    def _infer_clone(
        self, text: str, language: str, ref_audio_path: str, ref_text: str
    ) -> tuple[list[np.ndarray], int]:
        from qwen_tts import Qwen3TTSModel

        base = self._ensure_base_model()
        assert isinstance(base, Qwen3TTSModel)
        return base.generate_voice_clone(  # type: ignore[no-any-return]
            text=text,
            language=language,
            ref_audio=ref_audio_path,
            ref_text=ref_text,
        )

    # ------------------------------------------------------------------
    # Interface pública TTSEngine
    # ------------------------------------------------------------------

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio:
        language = _resolve_language(voice)

        if voice.ref_audio and voice.ref_text:
            # Voz clonada — usa modelo Base
            async with self._base_lock:
                self._active += 1
                try:
                    wavs, sr = await asyncio.to_thread(
                        self._infer_clone, text, language, voice.ref_audio, voice.ref_text
                    )
                finally:
                    self._active -= 1
        else:
            # Voz preset — usa modelo CustomVoice
            speaker = self._speaker_for(voice)
            instruct = (
                opts.style
                if (opts.style and opts.style.lower() not in ("", "neutro"))
                else (voice.style_prompt or None)
            )
            async with self._lock:
                self._active += 1
                try:
                    wavs, sr = await asyncio.to_thread(
                        self._infer_preset, text, speaker, language, instruct
                    )
                finally:
                    self._active -= 1

        pcm = _pcm_from_wav(wavs[0])
        duration_ms = len(wavs[0]) / sr * 1000
        return Audio(data=pcm, sample_rate=sr, duration_ms=duration_ms, ttfa_ms=0.0)

    async def stream(
        self,
        text: AsyncIterator[str],
        voice: Voice,
        opts: SynthOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        full_text = ""
        async for part in text:
            full_text += part
        audio = await self.synthesize(full_text, voice, opts) if full_text else None
        return self._stream_impl(audio)

    async def _stream_impl(self, audio: Audio | None) -> AsyncGenerator[AudioChunk, None]:
        if audio is None:
            return
        step = _CHUNK_SAMPLES * 2  # 2 bytes por sample int16
        for i in range(0, len(audio.data), step):
            chunk_data = audio.data[i : i + step]
            chunk_ms = (len(chunk_data) // 2) / _SAMPLE_RATE * 1000
            yield AudioChunk(data=chunk_data, sample_rate=_SAMPLE_RATE, duration_ms=chunk_ms)
            await asyncio.sleep(0)

    def capacity(self) -> Capacity:
        return Capacity(active_streams=self._active, queued=0, rtf_recent=None)
