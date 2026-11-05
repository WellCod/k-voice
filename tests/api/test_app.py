from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from kvoice.api.app import _OcultaToken
from kvoice.api.schemas import PronunciationEntryCreate


def test_log_do_websocket_oculta_token() -> None:
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        '%s - "WebSocket %s" [accepted]',
        ("127.0.0.1:5000", "/v1/tts/stream?token=segredo123&x=1"),
        None,
    )
    _OcultaToken().filter(record)
    texto = record.getMessage()
    assert "segredo123" not in texto
    assert "token=***&x=1" in texto


def test_regex_invalida_no_dicionario_e_rejeitada() -> None:
    with pytest.raises(ValidationError):
        PronunciationEntryCreate(term="([a-z", expansion="x", is_regex=True)
    PronunciationEntryCreate(term="([a-z", expansion="x", is_regex=False)
    PronunciationEntryCreate(term=r"\bkm\b", expansion="quilômetros", is_regex=True)
