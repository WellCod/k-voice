from __future__ import annotations

from typing import Any

import pytest

from kvoice.api.sintese import (
    MAX_CARACTERES_SEGMENTO,
    cortar_em_pausa,
    dividir_sentencas,
    sintetizar_em_partes,
)
from kvoice.engine.types import Audio, SynthOptions, Voice


def test_corte_prefere_virgula_a_espaco() -> None:
    cabeca, resto = cortar_em_pausa("um dois, tres quatro cinco", limite=20)
    assert cabeca == "um dois,"
    assert resto == "tres quatro cinco"


def test_corte_sem_pausa_cai_no_ultimo_espaco() -> None:
    cabeca, resto = cortar_em_pausa("aaaa bbbb cccc", limite=11)
    assert (cabeca, resto) == ("aaaa bbbb", "cccc")


def test_corte_sem_espaco_corta_no_limite() -> None:
    assert cortar_em_pausa("x" * 30, limite=10) == ("x" * 10, "x" * 20)


def test_frase_gigante_sem_pontuacao_vira_partes_dentro_do_limite() -> None:
    texto = " ".join(["palavra"] * 400)  # ~3.200 caracteres sem ponto
    partes = dividir_sentencas(texto)
    assert len(partes) > 1
    assert all(len(p) <= MAX_CARACTERES_SEGMENTO for p in partes)
    assert " ".join(partes) == texto


class _MotorQueAnota:
    sample_rate = 24_000

    def __init__(self) -> None:
        self.textos: list[str] = []

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio:
        self.textos.append(text)
        return Audio(data=b"\x01\x00" * 100, sample_rate=24_000, duration_ms=1.0, ttfa_ms=5.0)


async def test_texto_longo_sintetiza_parte_a_parte_e_junta() -> None:
    motor = _MotorQueAnota()
    texto = "Primeira frase. " * 80
    audio = await sintetizar_em_partes(
        motor,  # type: ignore[arg-type]
        texto.strip(),
        Voice(id="v", name="v"),
        SynthOptions(),
    )
    assert len(motor.textos) > 1
    assert all(len(t) <= MAX_CARACTERES_SEGMENTO for t in motor.textos)
    silencio = int(0.06 * 24_000) * 2
    assert len(audio.data) == 200 * len(motor.textos) + silencio * (len(motor.textos) - 1)
    assert audio.ttfa_ms == 5.0


@pytest.mark.parametrize("texto", ["Olá.", "x" * MAX_CARACTERES_SEGMENTO])
async def test_texto_curto_vai_inteiro(texto: str) -> None:
    motor = _MotorQueAnota()
    voz: Any = Voice(id="v", name="v")
    await sintetizar_em_partes(motor, texto, voz, SynthOptions())  # type: ignore[arg-type]
    assert motor.textos == [texto]
