"""Testes de regressão do normalizador pt-BR guiados por casos.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from kvoice.normalize import normalize, normalize_incremental

_YAML = Path(__file__).parent / "casos.yaml"


def _carregar() -> list[dict[str, Any]]:
    with _YAML.open(encoding="utf-8") as f:
        return yaml.safe_load(f)["casos"]  # type: ignore[no-any-return]


@pytest.mark.parametrize("caso", [c for c in _carregar() if not c.get("incremental")])
def test_normalize(caso: dict[str, Any]) -> None:
    dict_ = caso.get("dict")
    resultado = normalize(caso["entrada"], dict_)
    assert resultado == caso["esperado"], (
        f"[{caso['id']}] entrada={caso['entrada']!r}\n"
        f"  esperado : {caso['esperado']!r}\n"
        f"  obtido   : {resultado!r}"
    )


@pytest.mark.parametrize("caso", [c for c in _carregar() if c.get("incremental")])
def test_normalize_incremental(caso: dict[str, Any]) -> None:
    dict_ = caso.get("dict")
    pronto, pendente = normalize_incremental(caso["entrada"], dict_)
    assert pronto == caso["pronto"], (
        f"[{caso['id']}] pronto esperado={caso['pronto']!r}, obtido={pronto!r}"
    )
    assert pendente == caso["pendente"], (
        f"[{caso['id']}] pendente esperado={caso['pendente']!r}, obtido={pendente!r}"
    )
