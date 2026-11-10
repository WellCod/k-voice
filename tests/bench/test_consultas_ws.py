from __future__ import annotations

from bench.consultas_ws import _percentil, _resumo


def test_percentil_e_resumo() -> None:
    valores = [float(v) for v in range(1, 101)]
    assert _percentil(valores, 50) in (50.0, 51.0)
    assert _percentil(valores, 95) == 95.0
    r = _resumo(valores)
    assert r["max"] == 100.0
    assert r["p50"] == 50.5
