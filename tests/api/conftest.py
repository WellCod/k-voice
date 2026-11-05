from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _dicionario_vazio() -> Iterator[AsyncMock]:
    """O WebSocket carrega o dicionário do cliente no banco; nos testes, vazio por padrão."""
    with patch("kvoice.api.routers.tts.load_dict", AsyncMock(return_value=[])) as mock:
        yield mock


@pytest.fixture(autouse=True)
def _uso() -> Iterator[AsyncMock]:
    """Medição de uso grava no banco; nos testes, só registra a chamada."""
    with patch("kvoice.api.routers.tts._gravar_uso", AsyncMock(return_value=None)) as mock:
        yield mock
