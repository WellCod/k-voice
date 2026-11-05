from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _uso() -> Iterator[AsyncMock]:
    """Medição de uso grava no banco; nos testes, só registra a chamada."""
    with patch("kvoice.mcp.server.gravar_uso", AsyncMock(return_value=None)) as mock:
        yield mock
