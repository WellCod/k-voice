"""Engine Qwen3-TTS — CustomVoice (preset) e Base (clonagem de voz)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable

import numpy as np

from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, Voice, fatiar_pcm
from kvoice.referencias import arquivo_decifrado

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


def _kwargs_modelo(device: str, dtype: str) -> dict[str, object]:
    """Argumentos repassados ao AutoModel.from_pretrained pelo qwen-tts."""
    import torch

    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(f"QWEN3_DEVICE={device}, mas o torch instalado não enxerga CUDA")
    if dtype == "auto":
        dtype = "float32" if device == "cpu" else "bfloat16"
    return {"device_map": device, "dtype": getattr(torch, dtype)}


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
        device: str = "cpu",
        dtype: str = "auto",
    ) -> None:
        self._custom_model = custom_model
        self._device = device
        self._dtype = dtype
        self._base_model_id = base_model_id
        self._base_model: object | None = None
        self._base_loading = False
        self._speaker = speaker
        self._active = 0
        self._waiting = 0
        self._lock = asyncio.Semaphore(1)  # CPU: serializa inferências
        self._base_lock = asyncio.Semaphore(1)

    @classmethod
    def load(
        cls,
        custom_model_id: str,
        base_model_id: str,
        speaker: str = _DEFAULT_SPEAKER,
        device: str = "cpu",
        dtype: str = "auto",
    ) -> Qwen3TTSEngine:
        from qwen_tts import Qwen3TTSModel

        model = Qwen3TTSModel.from_pretrained(custom_model_id, **_kwargs_modelo(device, dtype))
        return cls(model, base_model_id, speaker, device, dtype)

    def _ensure_base_model(self) -> object:
        """Carrega o modelo Base na primeira chamada de clonagem (lazy)."""
        if self._base_model is not None:
            return self._base_model
        from qwen_tts import Qwen3TTSModel

        self._base_model = Qwen3TTSModel.from_pretrained(
            self._base_model_id, **_kwargs_modelo(self._device, self._dtype)
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
        with arquivo_decifrado(ref_audio_path) as ref:
            return base.generate_voice_clone(  # type: ignore[no-any-return]
                text=text,
                language=language,
                ref_audio=ref,
                ref_text=ref_text,
            )

    # ------------------------------------------------------------------
    # Interface pública TTSEngine
    # ------------------------------------------------------------------

    async def _executar(
        self,
        lock: asyncio.Semaphore,
        fn: Callable[..., tuple[list[np.ndarray], int]],
        *args: object,
    ) -> tuple[list[np.ndarray], int]:
        self._waiting += 1
        try:
            await lock.acquire()
        finally:
            self._waiting -= 1
        self._active += 1
        fut = asyncio.ensure_future(asyncio.to_thread(fn, *args))

        # A thread não para com o cancelamento: o lock só é liberado quando ela termina,
        # senão duas inferências rodariam ao mesmo tempo no mesmo modelo.
        def _liberar(f: asyncio.Future[tuple[list[np.ndarray], int]]) -> None:
            self._active -= 1
            lock.release()
            if not f.cancelled():
                f.exception()

        fut.add_done_callback(_liberar)
        return await asyncio.shield(fut)

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio:
        language = _resolve_language(voice)

        if voice.ref_audio and voice.ref_text:
            # Voz clonada — usa modelo Base
            wavs, sr = await self._executar(
                self._base_lock,
                self._infer_clone,
                text,
                language,
                voice.ref_audio,
                voice.ref_text,
            )
        else:
            # Voz preset — usa modelo CustomVoice
            speaker = self._speaker_for(voice)
            instruct = (
                opts.style
                if (opts.style and opts.style.lower() not in ("", "neutro"))
                else (voice.style_prompt or None)
            )
            wavs, sr = await self._executar(
                self._lock, self._infer_preset, text, speaker, language, instruct
            )

        pcm = _pcm_from_wav(wavs[0])
        duration_ms = len(wavs[0]) / sr * 1000
        return Audio(data=pcm, sample_rate=sr, duration_ms=duration_ms, ttfa_ms=0.0)

    async def stream(
        self,
        text: AsyncIterator[str],
        voice: Voice,
        opts: SynthOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        return self._stream_impl(text, voice, opts)

    async def _stream_impl(
        self, text: AsyncIterator[str], voice: Voice, opts: SynthOptions
    ) -> AsyncGenerator[AudioChunk, None]:
        # O qwen-tts não gera áudio em pedaços: cada frase que o normalizador libera é
        # sintetizada e enviada assim que fica pronta, sem esperar o texto acabar.
        async for frase in text:
            data = b""
            if frase.strip():
                audio = await self.synthesize(frase, voice, opts)
                data = audio.data
            for chunk in fatiar_pcm(data, _SAMPLE_RATE, _CHUNK_SAMPLES, textos_concluidos=1):
                yield chunk
                await asyncio.sleep(0)

    def capacity(self) -> Capacity:
        # Inferência é serializada: quem espera o lock é fila, base do controle de admissão.
        return Capacity(active_streams=self._active, queued=self._waiting, rtf_recent=None)
