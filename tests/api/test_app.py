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


async def test_falha_ao_gravar_uso_vira_log_e_nao_erro(caplog: pytest.LogCaptureFixture) -> None:
    import uuid
    from unittest.mock import patch

    from kvoice.api.deps import gravar_uso

    rid = uuid.uuid4()
    with patch("kvoice.api.deps.session_factory", side_effect=RuntimeError("banco fora")):
        await gravar_uso(
            request_id=rid,
            client_id=uuid.uuid4(),
            voice_id="v",
            engine_name="stub",
            characters=1,
            audio_ms=1.0,
            ttfa_ms=1.0,
            total_ms=1.0,
        )
    assert f"falha ao gravar uso (request_id={rid})" in caplog.text
