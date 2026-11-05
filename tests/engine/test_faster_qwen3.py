"""FasterQwen3Engine com modelo falso: valida o streaming sem GPU."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from typing import Any

import numpy as np
import pytest

from kvoice.engine.faster_qwen3 import FasterQwen3Engine
from kvoice.engine.types import SynthOptions, Voice

_SR = 24_000
_PEDACO = np.full(16_000, 0.1, dtype=np.float32)  # ~667 ms, como chunk_size=8


class _ModeloFalso:
    """Imita generate_*_streaming: rende (audio, sr, timing) a cada pedaço."""

    def __init__(self, pedacos: int = 3, sr: int = _SR) -> None:
        self.pedacos = pedacos
        self.sr = sr
        self.chamadas: list[dict[str, Any]] = []
        self.gerados = 0
        self.liberar = threading.Event()
        self.liberar.set()
        self.em_execucao = 0
        self.pico = 0

    def _gen(self, **kwargs: Any) -> Iterator[tuple[np.ndarray, int, dict[str, Any]]]:
        self.chamadas.append(kwargs)
        self.em_execucao += 1
        self.pico = max(self.pico, self.em_execucao)
        try:
            for i in range(self.pedacos):
                if i > 0:
                    self.liberar.wait(timeout=5)
                self.gerados += 1
                yield _PEDACO, self.sr, {"chunk_index": i}
        finally:
            self.em_execucao -= 1

    def generate_custom_voice_streaming(
        self, **kwargs: Any
    ) -> Iterator[tuple[np.ndarray, int, dict[str, Any]]]:
        return self._gen(**kwargs)

    def generate_voice_clone_streaming(
        self, **kwargs: Any
    ) -> Iterator[tuple[np.ndarray, int, dict[str, Any]]]:
        return self._gen(**kwargs)


async def _texto(*frases: str) -> AsyncIterator[str]:
    for f in frases:
        yield f


async def _esperar_ocioso(engine: FasterQwen3Engine) -> None:
    for _ in range(200):
        if engine.capacity().active_streams == 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("motor não liberou o lock")


def _voz(**kw: Any) -> Voice:
    return Voice(id="v", name="V", **kw)


async def test_primeiro_audio_sai_antes_da_frase_terminar() -> None:
    modelo = _ModeloFalso(pedacos=3)
    modelo.liberar.clear()  # trava a geração depois do primeiro pedaço
    engine = FasterQwen3Engine(modelo, base_model_id="x")

    gen = await engine.stream(_texto("Uma frase longa."), _voz(), SynthOptions())
    primeiro = await asyncio.wait_for(anext(gen), timeout=2)

    assert primeiro.data
    assert modelo.gerados == 1  # o resto da frase ainda não foi gerado
    modelo.liberar.set()
    resto = [c async for c in gen]
    assert sum(c.textos_concluidos for c in [primeiro, *resto]) == 1
    assert resto[-1].data == b"" and resto[-1].textos_concluidos == 1


async def test_parametros_do_preset_e_chunk_size() -> None:
    modelo = _ModeloFalso(pedacos=1)
    engine = FasterQwen3Engine(modelo, base_model_id="x", speaker="vivian", chunk_size=4)

    gen = await engine.stream(_texto("Oi."), _voz(model_id="Serena"), SynthOptions(style="calma"))
    _ = [c async for c in gen]

    assert modelo.chamadas == [
        {
            "text": "Oi.",
            "speaker": "serena",
            "language": "portuguese",
            "instruct": "calma",
            "chunk_size": 4,
        }
    ]


async def test_clonagem_usa_modelo_base() -> None:
    preset, base = _ModeloFalso(pedacos=1), _ModeloFalso(pedacos=1)
    engine = FasterQwen3Engine(preset, base_model_id="x")
    engine._base_model = base

    voz = _voz(ref_audio="/ref.wav", ref_text="texto de referência")
    gen = await engine.stream(_texto("Oi."), voz, SynthOptions())
    _ = [c async for c in gen]

    assert preset.chamadas == []
    assert base.chamadas[0]["ref_audio"] == "/ref.wav"
    assert base.chamadas[0]["ref_text"] == "texto de referência"


async def test_cancelar_para_a_geracao_e_segura_o_lock_ate_a_thread_sair() -> None:
    modelo = _ModeloFalso(pedacos=50)
    modelo.liberar.clear()
    engine = FasterQwen3Engine(modelo, base_model_id="x")

    gen = await engine.stream(_texto("Frase."), _voz(), SynthOptions())
    await anext(gen)
    await gen.aclose()

    assert engine.capacity().active_streams == 1  # thread ainda presa no pedaço 2
    modelo.liberar.set()
    await _esperar_ocioso(engine)
    assert modelo.gerados < 50  # parou de puxar pedaços depois do cancelamento

    # A próxima geração só começa depois que a anterior saiu do modelo.
    await engine.synthesize("Outra.", _voz(), SynthOptions())
    assert modelo.pico == 1


async def test_duas_frases_marcam_dois_textos() -> None:
    engine = FasterQwen3Engine(_ModeloFalso(pedacos=2), base_model_id="x")
    gen = await engine.stream(_texto("Uma.", "", "Duas."), _voz(), SynthOptions())
    chunks = [c async for c in gen]
    assert sum(c.textos_concluidos for c in chunks) == 3  # frase vazia também conta


async def test_synthesize_junta_pedacos() -> None:
    engine = FasterQwen3Engine(_ModeloFalso(pedacos=3), base_model_id="x")
    audio = await engine.synthesize("Oi.", _voz(), SynthOptions())
    assert len(audio.data) == 3 * len(_PEDACO) * 2
    assert audio.sample_rate == _SR


async def test_taxa_diferente_levanta_erro() -> None:
    engine = FasterQwen3Engine(_ModeloFalso(pedacos=1, sr=16_000), base_model_id="x")
    with pytest.raises(RuntimeError, match="taxa inesperada"):
        await engine.synthesize("Oi.", _voz(), SynthOptions())
    # O erro chega antes de a thread sair; o lock é liberado quando ela termina.
    await _esperar_ocioso(engine)


async def test_load_sem_cuda_falha_com_mensagem_clara() -> None:
    with pytest.raises(RuntimeError, match="exige CUDA"):
        FasterQwen3Engine.load("x", "y", device="cpu")


async def test_fila_conta_quem_espera_o_lock() -> None:
    modelo = _ModeloFalso(pedacos=3)
    modelo.liberar.clear()
    engine = FasterQwen3Engine(modelo, base_model_id="x")

    primeira = asyncio.create_task(engine.synthesize("Um.", _voz(), SynthOptions()))
    await asyncio.sleep(0.05)
    segunda = asyncio.create_task(engine.synthesize("Dois.", _voz(), SynthOptions()))
    await asyncio.sleep(0.05)
    assert (engine.capacity().active_streams, engine.capacity().queued) == (1, 1)

    modelo.liberar.set()
    await asyncio.gather(primeira, segunda)
    assert engine.capacity().queued == 0
