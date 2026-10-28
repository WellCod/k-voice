"""Testa funções de degradação de áudio sem precisar de GPU ou ffmpeg."""

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

import numpy as np  # noqa: E402

from bench.degradar import (  # noqa: E402
    _bandpass,
    _normalize_lufs,
    _resample,
    _ulaw_round_trip,
    degradar_telefone,
)

_SR = 24_000
_DURACAO_S = 0.5


def _seno(freq: float = 1000.0, sr: int = _SR, dur: float = _DURACAO_S) -> np.ndarray:
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# -----------------------------------------------------------------------
# Testes de _bandpass
# -----------------------------------------------------------------------


def test_bandpass_preserva_comprimento() -> None:
    audio = _seno()
    saida = _bandpass(audio, _SR)
    assert len(saida) == len(audio)


def test_bandpass_atenua_dc() -> None:
    """Componente DC (0 Hz) deve ser atenuada pelo passa-banda."""
    dc = np.ones(int(_SR * _DURACAO_S), dtype=np.float32) * 0.5
    saida = _bandpass(dc, _SR)
    assert float(np.abs(saida).max()) < 0.05


def test_bandpass_passa_voz() -> None:
    """Seno em 1 kHz (centro da banda de voz) deve passar com pouca atenuação."""
    audio = _seno(freq=1000.0)
    saida = _bandpass(audio, _SR)
    # RMS da saída deve ser pelo menos 50% do RMS da entrada
    rms_in = float(np.sqrt(np.mean(audio**2)))
    rms_out = float(np.sqrt(np.mean(saida**2)))
    assert rms_out >= 0.5 * rms_in


# -----------------------------------------------------------------------
# Testes de _resample
# -----------------------------------------------------------------------


def test_resample_comprimento_esperado() -> None:
    audio = _seno()
    saida = _resample(audio, _SR, 8_000)
    esperado = int(len(audio) * 8_000 / _SR)
    assert abs(len(saida) - esperado) <= 2


def test_resample_sem_mudanca_quando_mesmo_sr() -> None:
    audio = _seno()
    saida = _resample(audio, _SR, _SR)
    np.testing.assert_array_equal(audio, saida)


# -----------------------------------------------------------------------
# Testes de _ulaw_round_trip
# -----------------------------------------------------------------------


def test_ulaw_preserva_sinal() -> None:
    """Após μ-law encode+decode, sinal deve permanecer próximo do original."""
    audio = _seno(freq=1000.0)
    saida = _ulaw_round_trip(audio)
    assert float(np.abs(audio - saida).max()) < 0.05


def test_ulaw_limita_faixa() -> None:
    audio = _ulaw_round_trip(_seno())
    assert float(audio.max()) <= 1.0
    assert float(audio.min()) >= -1.0


# -----------------------------------------------------------------------
# Testes de _normalize_lufs
# -----------------------------------------------------------------------


def test_normalize_lufs_sem_crash_audio_silencioso() -> None:
    silencio = np.zeros(int(_SR * _DURACAO_S), dtype=np.float32)
    saida = _normalize_lufs(silencio, _SR)
    assert saida is not None


# -----------------------------------------------------------------------
# Teste do pipeline completo
# -----------------------------------------------------------------------


def test_degradar_telefone_taxa_correta() -> None:
    audio = _seno()
    _, sr_out = degradar_telefone(audio, _SR)
    assert sr_out == 8_000


def test_degradar_telefone_retorna_float32() -> None:
    audio = _seno()
    audio_out, _ = degradar_telefone(audio, _SR)
    assert audio_out.dtype == np.float32
