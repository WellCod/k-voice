from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from kvoice.engine.qwen3_tts import Qwen3TTSEngine
from kvoice.engine.types import SynthOptions, Voice


def _infer_lento(*_args: object) -> tuple[list[np.ndarray], int]:
    time.sleep(0.3)
    return [np.zeros(240, dtype=np.float32)], 24_000


@pytest.mark.asyncio
async def test_capacity_conta_fila_de_espera() -> None:
    engine = Qwen3TTSEngine(custom_model=None, base_model_id="x")
    engine._infer_preset = _infer_lento  # type: ignore[method-assign]
    voz = Voice(id="v", name="V")

    tarefas = [asyncio.create_task(engine.synthesize("oi", voz, SynthOptions())) for _ in range(3)]
    await asyncio.sleep(0.05)
    cap = engine.capacity()
    assert cap.active_streams == 1
    assert cap.queued == 2

    await asyncio.gather(*tarefas)
    cap = engine.capacity()
    assert (cap.active_streams, cap.queued) == (0, 0)


@pytest.mark.asyncio
async def test_capacity_desconta_espera_cancelada() -> None:
    engine = Qwen3TTSEngine(custom_model=None, base_model_id="x")
    engine._infer_preset = _infer_lento  # type: ignore[method-assign]
    voz = Voice(id="v", name="V")

    primeira = asyncio.create_task(engine.synthesize("oi", voz, SynthOptions()))
    await asyncio.sleep(0.01)
    segunda = asyncio.create_task(engine.synthesize("oi", voz, SynthOptions()))
    await asyncio.sleep(0.01)
    segunda.cancel()
    with pytest.raises(asyncio.CancelledError):
        await segunda
    assert engine.capacity().queued == 0
    await primeira


async def test_cancelar_durante_inferencia_mantem_lock_ate_thread_terminar() -> None:
    engine = Qwen3TTSEngine(custom_model=None, base_model_id="x")
    em_execucao = 0
    pico = 0

    def _infer(*_args: object) -> tuple[list[np.ndarray], int]:
        nonlocal em_execucao, pico
        em_execucao += 1
        pico = max(pico, em_execucao)
        time.sleep(0.2)
        em_execucao -= 1
        return [np.zeros(240, dtype=np.float32)], 24_000

    engine._infer_preset = _infer  # type: ignore[method-assign]
    voz = Voice(id="v", name="V")

    primeira = asyncio.create_task(engine.synthesize("oi", voz, SynthOptions()))
    await asyncio.sleep(0.05)
    primeira.cancel()
    with pytest.raises(asyncio.CancelledError):
        await primeira
    assert engine.capacity().active_streams == 1

    await engine.synthesize("oi", voz, SynthOptions())
    assert pico == 1
    assert engine.capacity().active_streams == 0
