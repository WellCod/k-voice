"""Cache em memória de áudio para frases curtas e repetidas.

O agente repete muito as mesmas falas ("Um momento, por favor.", "Posso ajudar em mais
alguma coisa?"). A partir da segunda vez, a frase sai da memória sem passar pela GPU:
o primeiro áudio sai na hora e o motor fica livre para as outras ligações.

Vale por processo. A chave inclui a voz inteira (speaker, referência e instrução), o
estilo, a velocidade e o texto já normalizado. As rotas de admin que mudam uma voz
limpam o cache; a validade limita o que sobrar em outras réplicas.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections import OrderedDict
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass

from prometheus_client import Counter

from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, TTSEngine, Voice

_CHUNK_SAMPLES = 4_800  # 200 ms a 24 kHz, como os motores
_RE_FIM_DE_FRASE = re.compile(r"(?<=[.!?])\s+")

audio_cache_hits = Counter("kvoice_audio_cache_hits_total", "Frases servidas do cache de áudio")
audio_cache_misses = Counter(
    "kvoice_audio_cache_misses_total", "Frases curtas que foram ao motor e entraram no cache"
)

_Chave = tuple[str, Voice, str, float, str]


@dataclass
class _Entrada:
    pcm: bytes
    sample_rate: int
    expira_em: float


class CacheAudio:
    """LRU por bytes, com validade por entrada."""

    def __init__(self, max_bytes: int, ttl_s: float) -> None:
        self.max_bytes = max_bytes
        self.ttl_s = ttl_s
        self._itens: OrderedDict[_Chave, _Entrada] = OrderedDict()
        self._bytes = 0

    def obter(self, chave: _Chave) -> _Entrada | None:
        entrada = self._itens.get(chave)
        if entrada is None:
            return None
        if entrada.expira_em < time.monotonic():
            self._remover(chave)
            return None
        self._itens.move_to_end(chave)
        return entrada

    def guardar(self, chave: _Chave, pcm: bytes, sample_rate: int) -> None:
        if not pcm or len(pcm) > self.max_bytes:
            return
        if chave in self._itens:
            self._remover(chave)
        self._itens[chave] = _Entrada(pcm, sample_rate, time.monotonic() + self.ttl_s)
        self._bytes += len(pcm)
        while self._bytes > self.max_bytes:
            antiga = next(iter(self._itens))
            self._remover(antiga)

    def limpar(self) -> None:
        self._itens.clear()
        self._bytes = 0

    @property
    def tamanho_bytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._itens)

    def _remover(self, chave: _Chave) -> None:
        entrada = self._itens.pop(chave)
        self._bytes -= len(entrada.pcm)


_caches: list[CacheAudio] = []


def limpar_caches_de_audio() -> None:
    """Chamado pelas rotas de admin quando uma voz muda (referência, instrução, speaker)."""
    for cache in _caches:
        cache.limpar()


async def _um_item(texto: str) -> AsyncIterator[str]:
    yield texto


class MotorComCache:
    """Envolve um TTSEngine e serve frases curtas repetidas da memória.

    No streaming, cada item de texto é dividido em frases e cada frase vai ao motor em
    separado (os motores já sintetizam frase a frase): o normalizador entrega várias
    frases num item só, e o cache é por frase. Cada item termina com exatamente um
    `textos_concluidos`, na última frase.
    """

    def __init__(self, motor: TTSEngine, max_bytes: int, max_caracteres: int, ttl_s: float) -> None:
        self.motor = motor
        self.name = motor.name
        self.sample_rate = motor.sample_rate
        self.max_caracteres = max_caracteres
        self.cache = CacheAudio(max_bytes, ttl_s)
        _caches.append(self.cache)

    def _chave(self, texto: str, voice: Voice, opts: SynthOptions) -> _Chave | None:
        if len(texto) > self.max_caracteres:
            return None
        return (self.motor.name, voice, opts.style, opts.speed, texto)

    async def stream(
        self, text: AsyncIterator[str], voice: Voice, opts: SynthOptions
    ) -> AsyncGenerator[AudioChunk, None]:
        async def _gen() -> AsyncGenerator[AudioChunk, None]:
            async for item in text:
                frases = [f for f in _RE_FIM_DE_FRASE.split(item.strip()) if f] or [item]
                for i, frase in enumerate(frases):
                    ultima = i == len(frases) - 1
                    async for chunk in self._stream_frase(frase, voice, opts, ultima):
                        yield chunk

        return _gen()

    async def _stream_frase(
        self, texto: str, voice: Voice, opts: SynthOptions, marcar: bool
    ) -> AsyncGenerator[AudioChunk, None]:
        chave = self._chave(texto, voice, opts)
        entrada = self.cache.obter(chave) if chave is not None else None
        if entrada is not None:
            audio_cache_hits.inc()
            pcm, taxa = entrada.pcm, entrada.sample_rate
            step = _CHUNK_SAMPLES * 2
            partes = [pcm[i : i + step] for i in range(0, len(pcm), step)]
            for i, parte in enumerate(partes):
                yield AudioChunk(
                    data=parte,
                    sample_rate=taxa,
                    duration_ms=(len(parte) // 2) / taxa * 1000,
                    textos_concluidos=1 if marcar and i == len(partes) - 1 else 0,
                )
            return

        coletado: list[bytes] = []
        taxa = self.sample_rate
        marcou = False
        gen = await self.motor.stream(_um_item(texto), voice, opts)
        async with contextlib.aclosing(gen):
            async for chunk in gen:
                coletado.append(chunk.data)
                taxa = chunk.sample_rate
                concluidos = 1 if marcar and chunk.textos_concluidos and not marcou else 0
                marcou = marcou or bool(concluidos)
                yield AudioChunk(chunk.data, chunk.sample_rate, chunk.duration_ms, concluidos)
        if marcar and not marcou:
            yield AudioChunk(b"", taxa, 0.0, textos_concluidos=1)
        # Só chega aqui se o item terminou inteiro: corte ou erro não entram no cache.
        if chave is not None:
            audio_cache_misses.inc()
            self.cache.guardar(chave, b"".join(coletado), taxa)

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio:
        chave = self._chave(text, voice, opts)
        entrada = self.cache.obter(chave) if chave is not None else None
        if entrada is not None:
            audio_cache_hits.inc()
            return Audio(
                data=entrada.pcm,
                sample_rate=entrada.sample_rate,
                duration_ms=(len(entrada.pcm) // 2) / entrada.sample_rate * 1000,
                ttfa_ms=0.0,
            )
        audio = await self.motor.synthesize(text, voice, opts)
        if chave is not None:
            audio_cache_misses.inc()
            self.cache.guardar(chave, audio.data, audio.sample_rate)
        return audio

    def capacity(self) -> Capacity:
        return self.motor.capacity()
