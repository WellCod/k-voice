"""Qwen3-TTS com streaming real em GPU via faster-qwen3-tts (CUDA graphs).

O modelo gera o áudio em pedaços de ~chunk_size/12 s enquanto a frase é decodificada:
o primeiro som sai antes de a frase terminar. Só roda em CUDA; em CPU o servidor usa
o Qwen3TTSEngine, que sintetiza frase a frase.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
from typing import Any

import numpy as np

from kvoice.engine.qwen3_tts import (
    _DEFAULT_SPEAKER,
    _VALID_SPEAKERS,
    _pcm_from_wav,
    _resolve_language,
)
from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, Voice, fatiar_pcm
from kvoice.referencias import arquivo_decifrado

_SAMPLE_RATE = 24_000
_CHUNK_SAMPLES = 4_800  # 200 ms a 24 kHz

_Gerador = Iterator[tuple[np.ndarray, int, dict[str, Any]]]


def _carregar(model_id: str, device: str, dtype: str) -> Any:
    import torch
    from faster_qwen3_tts import FasterQwen3TTS

    if not device.startswith("cuda") or not torch.cuda.is_available():
        raise RuntimeError(f"faster-qwen3-tts exige CUDA; QWEN3_DEVICE={device}")
    torch_dtype = torch.bfloat16 if dtype == "auto" else getattr(torch, dtype)
    model = FasterQwen3TTS.from_pretrained(model_id, device=device, dtype=torch_dtype)
    # Captura os CUDA graphs agora; sem isso a primeira fala paga a captura.
    model.warmup()
    return model


class FasterQwen3Engine:
    """TTSEngine com geração em streaming dentro da frase (CustomVoice e clonagem)."""

    name = "qwen3-tts"
    sample_rate = _SAMPLE_RATE

    def __init__(
        self,
        custom_model: Any,
        base_model_id: str,
        speaker: str = _DEFAULT_SPEAKER,
        device: str = "cuda",
        dtype: str = "auto",
        chunk_size: int = 8,
    ) -> None:
        self._custom_model = custom_model
        self._base_model: Any = None
        self._base_model_id = base_model_id
        self._speaker = speaker
        self._device = device
        self._dtype = dtype
        self._chunk_size = chunk_size
        self._active = 0
        self._waiting = 0
        # CUDA graphs são estáticos: uma geração por vez em cada modelo.
        self._lock = asyncio.Semaphore(1)
        self._base_lock = asyncio.Semaphore(1)

    @classmethod
    def load(
        cls,
        custom_model_id: str,
        base_model_id: str,
        speaker: str = _DEFAULT_SPEAKER,
        device: str = "cuda",
        dtype: str = "auto",
        chunk_size: int = 8,
    ) -> FasterQwen3Engine:
        model = _carregar(custom_model_id, device, dtype)
        return cls(model, base_model_id, speaker, device, dtype, chunk_size)

    def _speaker_for(self, voice: Voice) -> str:
        candidate = (voice.model_id or "").lower().replace(" ", "_")
        return candidate if candidate in _VALID_SPEAKERS else self._speaker

    def _fabrica(
        self, text: str, voice: Voice, opts: SynthOptions
    ) -> tuple[asyncio.Semaphore, Callable[[], _Gerador]]:
        language = _resolve_language(voice)
        if voice.ref_audio and voice.ref_text:
            ref_audio, ref_text = voice.ref_audio, voice.ref_text

            def _clone() -> _Gerador:
                if self._base_model is None:
                    self._base_model = _carregar(self._base_model_id, self._device, self._dtype)
                # O arquivo decifrado vive enquanto o gerador roda; _rodar fecha o gerador.
                with arquivo_decifrado(ref_audio) as ref:
                    yield from self._base_model.generate_voice_clone_streaming(
                        text=text,
                        language=language,
                        ref_audio=ref,
                        ref_text=ref_text,
                        chunk_size=self._chunk_size,
                    )

            return self._base_lock, _clone

        speaker = self._speaker_for(voice)
        # O 0.6B ignora instruct (o próprio pacote zera); o 1.7B usa.
        instruct = (
            opts.style
            if (opts.style and opts.style.lower() not in ("", "neutro"))
            else (voice.style_prompt or None)
        )

        def _preset() -> _Gerador:
            gen: _Gerador = self._custom_model.generate_custom_voice_streaming(
                text=text,
                speaker=speaker,
                language=language,
                instruct=instruct,
                chunk_size=self._chunk_size,
            )
            return gen

        return self._lock, _preset

    async def _gerar(
        self, lock: asyncio.Semaphore, fabrica: Callable[[], _Gerador]
    ) -> AsyncGenerator[bytes, None]:
        """Roda o gerador síncrono numa thread e repassa cada pedaço de PCM assim que sai."""
        self._waiting += 1
        try:
            await lock.acquire()
        finally:
            self._waiting -= 1
        self._active += 1

        loop = asyncio.get_running_loop()
        fila: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue()
        parar = threading.Event()

        def _entregar(item: bytes | BaseException | None) -> None:
            with contextlib.suppress(RuntimeError):  # loop já fechado
                loop.call_soon_threadsafe(fila.put_nowait, item)

        def _rodar() -> None:
            try:
                gen = fabrica()
                try:
                    for audio, sr, _timing in gen:
                        if parar.is_set():
                            break
                        if sr != _SAMPLE_RATE:
                            raise RuntimeError(f"taxa inesperada do modelo: {sr} Hz")
                        _entregar(_pcm_from_wav(np.asarray(audio)))
                finally:
                    close = getattr(gen, "close", None)
                    if close is not None:
                        close()
                _entregar(None)
            except BaseException as exc:
                _entregar(exc)

        fut = loop.run_in_executor(None, _rodar)

        # O cancelamento só para a geração no próximo pedaço; o lock fica preso até a
        # thread sair, senão duas gerações rodariam no mesmo modelo.
        def _liberar(_f: asyncio.Future[None]) -> None:
            self._active -= 1
            lock.release()

        fut.add_done_callback(_liberar)
        try:
            while True:
                item = await fila.get()
                if item is None:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            parar.set()

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio:
        t0 = time.monotonic()
        ttfa_ms = 0.0
        partes: list[bytes] = []
        lock, fabrica = self._fabrica(text, voice, opts)
        async with contextlib.aclosing(self._gerar(lock, fabrica)) as gen:
            async for pcm in gen:
                if not partes:
                    ttfa_ms = (time.monotonic() - t0) * 1000
                partes.append(pcm)
        data = b"".join(partes)
        return Audio(
            data=data,
            sample_rate=_SAMPLE_RATE,
            duration_ms=(len(data) // 2) / _SAMPLE_RATE * 1000,
            ttfa_ms=ttfa_ms,
        )

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
        async for frase in text:
            if frase.strip():
                lock, fabrica = self._fabrica(frase, voice, opts)
                async with contextlib.aclosing(self._gerar(lock, fabrica)) as gen:
                    async for pcm in gen:
                        for chunk in fatiar_pcm(pcm, _SAMPLE_RATE, _CHUNK_SAMPLES):
                            yield chunk
            # Marca o fim da frase sem segurar áudio: chunk vazio só para o "flushed".
            yield AudioChunk(
                data=b"", sample_rate=_SAMPLE_RATE, duration_ms=0.0, textos_concluidos=1
            )

    def capacity(self) -> Capacity:
        return Capacity(active_streams=self._active, queued=self._waiting, rtf_recent=None)
