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


@pytest.mark.parametrize("expansao", [r"\1", r"\d", r"\g<nome>"])
def test_expansao_invalida_no_dicionario_e_rejeitada(expansao: str) -> None:
    with pytest.raises(ValidationError):
        PronunciationEntryCreate(term=r"\bkm\b", expansion=expansao, is_regex=True)
    PronunciationEntryCreate(term=r"(\d+)km", expansion=r"\1 quilômetros", is_regex=True)


def test_regex_quebrada_ja_gravada_nao_derruba_a_fala() -> None:
    from kvoice.normalize import apply_dict

    entradas = [("km", "quilômetros", False), (r"\bx\b", r"\1", True), ("ok", "certo", True)]
    assert apply_dict("5 km x ok", entradas) == "5 quilômetros x certo"


def test_duracao_da_referencia_vem_do_audio() -> None:
    import io
    import shutil
    import wave

    import numpy as np

    from kvoice.audio import _ffmpeg_bin, preprocess_ref_audio

    if shutil.which(_ffmpeg_bin()) is None:
        pytest.skip("ffmpeg ausente")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16_000)
        t = np.arange(32_000) / 16_000
        wf.writeframes((np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16).tobytes())

    wav, duracao = preprocess_ref_audio(buf.getvalue(), "wav")

    assert duracao == pytest.approx(2.0, abs=0.2)
    with wave.open(io.BytesIO(wav), "rb") as wf:
        assert wf.getframerate() == 16_000
        assert wf.getnframes() / 16_000 == pytest.approx(duracao)


def test_mcp_responde_por_http_em_barra_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from kvoice.api.app import create_app
    from kvoice.settings import get_settings

    monkeypatch.setenv("QWEN3_ENABLED", "false")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            r = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "teste", "version": "1"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
            assert r.status_code == 200
            assert '"serverInfo"' in r.text
            assert client.get("/health").json()["status"] == "ok"
    finally:
        get_settings.cache_clear()


def test_falha_ao_carregar_o_qwen_impede_o_servidor_de_subir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from kvoice.api.app import create_app
    from kvoice.engine.registry import clear_engine, get_engine
    from kvoice.settings import get_settings

    monkeypatch.setenv("QWEN3_ENABLED", "true")
    monkeypatch.setenv("QWEN3_DEVICE", "cpu")
    get_settings.cache_clear()
    clear_engine()
    try:
        with (
            patch(
                "kvoice.engine.qwen3_tts.Qwen3TTSEngine.load",
                side_effect=RuntimeError("pesos ausentes"),
            ),
            pytest.raises(RuntimeError, match="pesos ausentes"),
            TestClient(create_app()),
        ):
            pass
        assert get_engine() is None
    finally:
        get_settings.cache_clear()
        clear_engine()


@pytest.mark.parametrize(
    "campos",
    [
        {"age_range": "x" * 33},
        {"gender": "x" * 33},
        {"language": "x" * 17},
        {"id": "../referencias"},
        {"id": "voz com espaco"},
    ],
)
def test_voz_com_campo_fora_do_limite_da_coluna_e_rejeitada(campos: dict[str, str]) -> None:
    from kvoice.api.schemas import VoiceCreate

    base = {"id": "v_ok", "name": "Voz", "origin": "preset"}
    VoiceCreate.model_validate(base)
    with pytest.raises(ValidationError):
        VoiceCreate.model_validate({**base, **campos})


def test_voz_equivalente_na_elevenlabs_aceita_id_e_vazio_no_patch() -> None:
    from kvoice.api.schemas import VoiceCreate, VoicePatch

    VoiceCreate(id="v_ok", name="Voz", origin="preset", elevenlabs_voice_id="21m00Tcm4TlvDq8ikWAM")
    assert VoicePatch(elevenlabs_voice_id="").elevenlabs_voice_id == ""
    with pytest.raises(ValidationError):
        VoiceCreate(id="v_ok", name="Voz", origin="preset", elevenlabs_voice_id="")
    with pytest.raises(ValidationError):
        VoicePatch(elevenlabs_voice_id="../x")
