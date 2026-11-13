import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _cache_de_consultas_limpo() -> None:
    from kvoice.cache_consultas import limpar_cache_de_consultas

    limpar_cache_de_consultas()
