"""Testa as funções puras de bench/latencia.py (sem GPU, sem rede)."""

import pytest

np = pytest.importorskip("numpy")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bench.latencia import _chunkar_texto, _percentis  # noqa: E402

# -----------------------------------------------------------------------
# _chunkar_texto
# -----------------------------------------------------------------------


def test_chunkar_preserva_palavras() -> None:
    texto = "olá tudo bem meu nome é ana da clínica"
    chunks = _chunkar_texto(texto)
    reconstruido = " ".join(chunks)
    assert reconstruido == texto


def test_chunkar_tamanho_chunks() -> None:
    texto = " ".join([f"palavra{i}" for i in range(40)])
    chunks = _chunkar_texto(texto, min_palavras=3, max_palavras=8)
    for chunk in chunks:
        n = len(chunk.split())
        assert 1 <= n <= 8


def test_chunkar_texto_curto() -> None:
    chunks = _chunkar_texto("oi")
    assert chunks == ["oi"]


def test_chunkar_determinismo() -> None:
    texto = "valor total da sua fatura é de mil duzentos e trinta e quatro reais"
    assert _chunkar_texto(texto) == _chunkar_texto(texto)


# -----------------------------------------------------------------------
# _percentis
# -----------------------------------------------------------------------


def test_percentis_valores_conhecidos() -> None:
    valores = [100.0, 200.0, 300.0, 400.0, 500.0]
    p = _percentis(valores)
    assert p["p50"] == pytest.approx(300.0)
    assert p["min"] == pytest.approx(100.0)
    assert p["max"] == pytest.approx(500.0)
    assert p["n"] == 5


def test_percentis_valor_unico() -> None:
    p = _percentis([42.0])
    assert p["p50"] == pytest.approx(42.0)
    assert p["p95"] == pytest.approx(42.0)
    assert p["n"] == 1


def test_percentis_p95_maior_que_p50() -> None:
    import random

    rng = random.Random(1)
    valores = [rng.gauss(200, 50) for _ in range(100)]
    p = _percentis(valores)
    assert p["p95"] >= p["p50"]
