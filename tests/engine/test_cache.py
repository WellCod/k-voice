from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import pytest

from kvoice.engine import cache as cache_mod
from kvoice.engine.cache import CacheAudio, MotorComCache, limpar_caches_de_audio
from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, Voice

_VOZ = Voice(id="v_ana", name="Ana", model_id="vivian")
_OPTS = SynthOptions()


class _MotorQueConta:
    name = "fake"
    sample_rate = 24_000

    def __init__(self) -> None:
        self.textos: list[str] = []

    async def stream(
        self, text: AsyncIterator[str], voice: Voice, opts: SynthOptions
    ) -> AsyncGenerator[AudioChunk, None]:
        async def _gen() -> AsyncGenerator[AudioChunk, None]:
            async for t in text:
                self.textos.append(t)
                pcm = t.encode()[:4].ljust(4, b"\x00") * 3000  # 12 kB por frase
                yield AudioChunk(pcm[:6000], 24_000, 125.0)
                yield AudioChunk(pcm[6000:], 24_000, 125.0, textos_concluidos=1)

        return _gen()

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio:
        self.textos.append(text)
        return Audio(data=b"\x01\x00" * 100, sample_rate=24_000, duration_ms=4.0, ttfa_ms=50.0)

    def capacity(self) -> Capacity:
        return Capacity(active_streams=0, queued=3, rtf_recent=None)


async def _itens(*textos: str) -> AsyncIterator[str]:
    for t in textos:
        yield t


async def _consumir(motor: MotorComCache, *textos: str) -> list[AudioChunk]:
    gen = await motor.stream(_itens(*textos), _VOZ, _OPTS)
    return [c async for c in gen]


def _motor(max_caracteres: int = 200) -> tuple[MotorComCache, _MotorQueConta]:
    base = _MotorQueConta()
    return MotorComCache(base, max_bytes=1_000_000, max_caracteres=max_caracteres, ttl_s=60), base


async def test_frase_repetida_sai_do_cache_sem_ir_ao_motor() -> None:
    motor, base = _motor()
    primeira = await _consumir(motor, "Um momento.", "Já verifico.")
    segunda = await _consumir(motor, "Um momento.", "Outra coisa.")

    assert base.textos == ["Um momento.", "Já verifico.", "Outra coisa."]
    pcm = b"".join(c.data for c in primeira[:2])
    assert b"".join(c.data for c in segunda[: len(segunda) - 2]) == pcm
    # Cada item termina com exatamente um textos_concluidos, venha do cache ou do motor.
    assert sum(c.textos_concluidos for c in primeira) == 2
    assert sum(c.textos_concluidos for c in segunda) == 2


async def test_texto_longo_nao_entra_no_cache() -> None:
    motor, base = _motor(max_caracteres=10)
    await _consumir(motor, "Frase comprida demais.")
    await _consumir(motor, "Frase comprida demais.")
    assert base.textos == ["Frase comprida demais."] * 2
    assert len(motor.cache) == 0


async def test_item_interrompido_nao_entra_no_cache() -> None:
    motor, base = _motor()
    gen = await motor.stream(_itens("Um momento."), _VOZ, _OPTS)
    async with contextlib.aclosing(gen):
        async for _ in gen:
            break  # barge-in no primeiro chunk
    assert len(motor.cache) == 0


async def test_voz_ou_estilo_diferente_nao_reaproveita() -> None:
    motor, base = _motor()
    await _consumir(motor, "Olá.")
    outra_voz = Voice(id="v_bia", name="Bia", model_id="serena")
    gen = await motor.stream(_itens("Olá."), outra_voz, _OPTS)
    _ = [c async for c in gen]
    gen = await motor.stream(_itens("Olá."), _VOZ, SynthOptions(style="alegre"))
    _ = [c async for c in gen]
    assert base.textos == ["Olá."] * 3


async def test_motor_que_nao_marca_concluido_ganha_marca_no_fim() -> None:
    class _SemMarca(_MotorQueConta):
        async def stream(
            self, text: AsyncIterator[str], voice: Voice, opts: SynthOptions
        ) -> AsyncGenerator[AudioChunk, None]:
            async def _gen() -> AsyncGenerator[AudioChunk, None]:
                async for _ in text:
                    yield AudioChunk(b"\x00" * 960, 24_000, 20.0)

            return _gen()

    motor = MotorComCache(_SemMarca(), max_bytes=1_000_000, max_caracteres=200, ttl_s=60)
    chunks = await _consumir(motor, "A.", "B.")
    assert sum(c.textos_concluidos for c in chunks) == 2


async def test_synthesize_usa_cache_e_capacidade_vem_do_motor() -> None:
    motor, base = _motor()
    a = await motor.synthesize("Obrigado.", _VOZ, _OPTS)
    b = await motor.synthesize("Obrigado.", _VOZ, _OPTS)
    assert base.textos == ["Obrigado."]
    assert a.data == b.data
    assert b.ttfa_ms == 0.0
    assert motor.capacity().queued == 3


async def test_limpar_caches_esvazia_todos() -> None:
    motor, _ = _motor()
    await _consumir(motor, "Olá.")
    assert len(motor.cache) == 1
    limpar_caches_de_audio()
    assert len(motor.cache) == 0


def test_lru_respeita_limite_de_bytes() -> None:
    cache = CacheAudio(max_bytes=10, ttl_s=60)
    voz: Any = _VOZ
    cache.guardar(("m", voz, "n", 1.0, "a"), b"x" * 6, 24_000)
    cache.guardar(("m", voz, "n", 1.0, "b"), b"y" * 6, 24_000)
    assert cache.obter(("m", voz, "n", 1.0, "a")) is None
    assert cache.obter(("m", voz, "n", 1.0, "b")) is not None
    assert cache.tamanho_bytes == 6
    cache.guardar(("m", voz, "n", 1.0, "c"), b"z" * 11, 24_000)  # maior que o cache
    assert len(cache) == 1


def test_entrada_vencida_sai_do_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    agora = [1000.0]
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: agora[0])
    cache = CacheAudio(max_bytes=100, ttl_s=10)
    chave: Any = ("m", _VOZ, "n", 1.0, "a")
    cache.guardar(chave, b"x" * 4, 24_000)
    agora[0] += 11
    assert cache.obter(chave) is None
    assert cache.tamanho_bytes == 0


async def test_item_com_varias_frases_usa_cache_por_frase_e_marca_uma_vez() -> None:
    motor, base = _motor()
    await _consumir(motor, "Um momento.")
    chunks = await _consumir(motor, "Um momento. Já verifico. Um momento.")
    assert base.textos == ["Um momento.", "Já verifico."]
    assert sum(c.textos_concluidos for c in chunks) == 1
    assert chunks[-1].textos_concluidos == 1
