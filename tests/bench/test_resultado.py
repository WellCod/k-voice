"""Testa ResultadoSintese sem precisar de GPU."""

import pytest

np = pytest.importorskip("numpy")

from bench.motores.base import ResultadoSintese


def _resultado(
    n_amostras: int = 24_000, taxa: int = 24_000, sintese_ms: float = 100.0
) -> ResultadoSintese:
    audio = np.zeros(n_amostras, dtype=np.float32)
    return ResultadoSintese(
        audio=audio,
        taxa_amostragem=taxa,
        duracao_sintese_ms=sintese_ms,
        motor="teste",
        frase_id="f_01",
    )


def test_duracao_audio_ms() -> None:
    r = _resultado(n_amostras=24_000, taxa=24_000)
    assert abs(r.duracao_audio_ms - 1000.0) < 0.1


def test_rtf_mais_rapido_que_realtime() -> None:
    # 100 ms para gerar 1 s de áudio → RTF = 0.1
    r = _resultado(n_amostras=24_000, taxa=24_000, sintese_ms=100.0)
    assert abs(r.rtf - 0.1) < 1e-6


def test_rtf_sem_divisao_por_zero() -> None:
    r = _resultado(n_amostras=0, taxa=24_000)
    assert r.rtf >= 0
