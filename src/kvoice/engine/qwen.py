from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, Voice

_MODELO_PADRAO = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
_TAXA = 24_000


class QwenTTSEngine:
    name: str = "qwen3-tts"
    sample_rate: int = _TAXA

    def __init__(self, model_id: str = _MODELO_PADRAO, max_workers: int = 1) -> None:
        self._model_id = model_id
        self._model: Any = None
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qwen")
        self._active = 0

    def load(self) -> None:
        try:
            from faster_qwen3_tts import FasterQwen3TTS  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "faster-qwen3-tts não instalado: pip install faster-qwen3-tts"
            ) from exc
        self._model = FasterQwen3TTS.from_pretrained(self._model_id)

    def unload(self) -> None:
        self._model = None

    def capacity(self) -> Capacity:
        return Capacity(active_streams=self._active, queued=0, rtf_recent=None)

    def _iter_chunks(self, texto: str, voice: Voice) -> Any:
        if voice.ref_audio and voice.ref_text:
            return self._model.generate_voice_clone_streaming(
                text=texto,
                language="Portuguese",
                ref_audio=voice.ref_audio,
                ref_text=voice.ref_text,
                chunk_size=8,
            )
        instrucao = voice.style_prompt or "Voz feminina, clara, português brasileiro."
        return self._model.generate_voice_design_streaming(
            text=texto,
            language="Portuguese",
            instruct=instrucao,
            chunk_size=8,
        )

    async def stream(
        self,
        text: AsyncIterator[str],
        voice: Voice,
        opts: SynthOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        texto = "".join([t async for t in text])
        return self._stream_impl(texto, voice, opts)

    async def _stream_impl(
        self,
        texto: str,
        voice: Voice,
        opts: SynthOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        loop = asyncio.get_running_loop()
        cancel = threading.Event()
        queue: asyncio.Queue[AudioChunk | BaseException | None] = asyncio.Queue()

        def _run() -> None:
            try:
                for audio_np, sr, _ in self._iter_chunks(texto, voice):
                    if cancel.is_set():
                        return
                    arr = np.asarray(audio_np, dtype=np.float32)
                    if arr.size == 0:
                        continue
                    pcm = (arr.clip(-1.0, 1.0) * 32767).astype(np.int16).tobytes()
                    dur_ms = arr.size / int(sr) * 1000
                    chunk = AudioChunk(data=pcm, sample_rate=int(sr), duration_ms=round(dur_ms, 2))
                    asyncio.run_coroutine_threadsafe(queue.put(chunk), loop).result()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    asyncio.run_coroutine_threadsafe(queue.put(exc), loop).result(timeout=5)
            finally:
                with contextlib.suppress(Exception):
                    asyncio.run_coroutine_threadsafe(queue.put(None), loop).result(timeout=5)

        self._active += 1
        self._executor.submit(_run)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            cancel.set()
            self._active -= 1

    async def synthesize(
        self,
        text: str,
        voice: Voice,
        opts: SynthOptions,
    ) -> Audio:
        t_inicio = time.perf_counter()
        ttfa_ms: float | None = None
        chunks: list[AudioChunk] = []

        async def _text_iter() -> AsyncGenerator[str, None]:
            yield text

        gen = await self.stream(_text_iter(), voice, opts)
        async for chunk in gen:
            if ttfa_ms is None:
                ttfa_ms = (time.perf_counter() - t_inicio) * 1000
            chunks.append(chunk)

        data = b"".join(c.data for c in chunks)
        sr = chunks[0].sample_rate if chunks else self.sample_rate
        dur_ms = sum(c.duration_ms for c in chunks)
        return Audio(
            data=data,
            sample_rate=sr,
            duration_ms=dur_ms,
            ttfa_ms=round(ttfa_ms or (time.perf_counter() - t_inicio) * 1000, 2),
        )
