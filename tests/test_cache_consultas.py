from __future__ import annotations

from typing import Any

import pytest

from kvoice import cache_consultas
from kvoice.cache_consultas import em_cache, limpar_cache_de_consultas
from kvoice.settings import get_settings


@pytest.fixture()
def relogio(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    agora = [1000.0]
    monkeypatch.setattr(cache_consultas.time, "monotonic", lambda: agora[0])
    return agora


@pytest.fixture()
def ttl(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _definir(valor: float) -> None:
        monkeypatch.setattr(get_settings(), "query_cache_ttl_s", valor)

    _definir(30.0)
    return _definir


async def test_repete_a_consulta_so_depois_da_validade(relogio: list[float], ttl: Any) -> None:
    chamadas: list[str] = []

    @em_cache
    async def buscar(chave: str) -> str | None:
        chamadas.append(chave)
        return None if chave == "nada" else chave.upper()

    assert await buscar("a") == "A"
    assert await buscar("a") == "A"
    assert await buscar("nada") is None
    assert await buscar("nada") is None  # None também fica guardado
    assert chamadas == ["a", "nada"]
    relogio[0] += 31
    await buscar("a")
    assert chamadas == ["a", "nada", "a"]


async def test_limpar_e_ttl_zero(relogio: list[float], ttl: Any) -> None:
    chamadas: list[int] = []

    @em_cache
    async def buscar(n: int) -> int:
        chamadas.append(n)
        return n

    await buscar(1)
    limpar_cache_de_consultas()
    await buscar(1)
    ttl(0)
    await buscar(1)
    await buscar(1)
    assert chamadas == [1, 1, 1, 1]


async def test_token_entra_no_cache_pelo_hash(ttl: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from kvoice.api import deps
    from kvoice.api.auth import hash_token

    vistos: list[str] = []

    async def _sem_banco(token_hash: str) -> None:
        vistos.append(token_hash)
        return None

    monkeypatch.setattr(deps, "_autenticar_por_hash", em_cache(_sem_banco))
    assert await deps.autenticar_token("segredo") is None
    assert await deps.autenticar_token("segredo") is None
    assert vistos == [hash_token("segredo")]
    assert "segredo" not in repr(cache_consultas._caches)


async def test_escrita_no_admin_limpa_o_cache(ttl: Any) -> None:
    from starlette.requests import Request

    from kvoice.api.routers.admin import _limpar_cache_em_escrita

    chamadas: list[int] = []

    @em_cache
    async def buscar(n: int) -> int:
        chamadas.append(n)
        return n

    async def _passar(metodo: str) -> None:
        gen = _limpar_cache_em_escrita(Request({"type": "http", "method": metodo}))
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    await buscar(1)
    await _passar("GET")
    await buscar(1)
    assert chamadas == [1]
    await _passar("PATCH")
    await buscar(1)
    assert chamadas == [1, 1]
