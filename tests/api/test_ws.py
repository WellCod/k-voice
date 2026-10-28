"""Testes do endpoint WebSocket de streaming."""

from __future__ import annotations

import threading
import time
import types
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kvoice.api.routing import RoutingDecision
from kvoice.api.ws_proto import (
    CancelMsg,
    EndMsg,
    Options,
    StartMsg,
    TextMsg,
    parse_client_msg,
)
from kvoice.engine.registry import clear_engine, set_engine
from kvoice.engine.types import AudioChunk, Capacity, SynthOptions, TTSEngine, Voice

# ---------------------------------------------------------------------------
# Mock engine
# ---------------------------------------------------------------------------


class _FakeEngine:
    name = "fake"
    sample_rate = 24000
    _queued = 0

    async def stream(
        self,
        text: Any,
        voice: Voice,
        opts: SynthOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        async def _gen() -> AsyncGenerator[AudioChunk, None]:
            async for _ in text:
                yield AudioChunk(
                    data=b"\x00" * 960,  # 20 ms @ 24 kHz 16-bit
                    sample_rate=24000,
                    duration_ms=20.0,
                )

        return _gen()

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Any: ...

    def capacity(self) -> Capacity:
        return Capacity(active_streams=0, queued=self._queued, rtf_recent=None)


assert isinstance(_FakeEngine(), TTSEngine)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_engine() -> Any:
    """Garante estado limpo do registry entre testes."""
    clear_engine()
    yield
    clear_engine()


@pytest.fixture()
def engine() -> _FakeEngine:
    eng = _FakeEngine()
    set_engine(eng)  # type: ignore[arg-type]
    return eng


@pytest.fixture()
def fake_client() -> Any:
    return types.SimpleNamespace(id=uuid.uuid4(), name="Teste", is_active=True)


@pytest.fixture()
def fake_token(fake_client: Any) -> Any:
    def _has_scope(scope: str) -> bool:
        return scope in {"tts:stream", "admin"}

    return types.SimpleNamespace(
        client_id=fake_client.id,
        scopes="tts:stream",
        is_active=True,
        name="tok",
        has_scope=_has_scope,
    )


@pytest.fixture()
def fake_voice() -> Any:
    return types.SimpleNamespace(
        id="v_fake",
        name="Fake",
        language="pt-BR",
        is_active=True,
        style_prompt=None,
        model_id=None,
        ref_audio_key=None,
        ref_text=None,
    )


def _make_app() -> Any:
    from fastapi import FastAPI

    from kvoice.api.routers import admin, tts, voices

    app = FastAPI(title="k-voice")
    app.include_router(admin.router)
    app.include_router(voices.router)
    app.include_router(tts.router)
    return app


# ---------------------------------------------------------------------------
# Helpers de patch
# ---------------------------------------------------------------------------


def _auth_patch(fake_client: Any, fake_token: Any) -> Any:
    return patch(
        "kvoice.api.routers.tts._autenticar_ws",
        AsyncMock(return_value=(fake_client, fake_token)),
    )


def _voice_patch(fake_voice: Any) -> Any:
    return patch(
        "kvoice.api.routers.tts._buscar_voz",
        AsyncMock(return_value=fake_voice),
    )


def _uso_patch() -> Any:
    return patch(
        "kvoice.api.routers.tts._gravar_uso",
        AsyncMock(return_value=None),
    )


def _routing_patch(decision: RoutingDecision | None) -> Any:
    return patch(
        "kvoice.api.routers.tts.decide_engine",
        AsyncMock(return_value=decision),
    )


def _kvoice_decision(engine: _FakeEngine, voice_id: str = "v_fake") -> RoutingDecision:
    return RoutingDecision(
        engine=engine,  # type: ignore[arg-type]
        engine_name=engine.name,
        effective_voice_id=voice_id,
        is_fallback=False,
        fallback_reason=None,
    )


# ---------------------------------------------------------------------------
# Testes de parse de mensagens
# ---------------------------------------------------------------------------


def test_parse_start() -> None:
    msg = parse_client_msg('{"type":"start","voice_id":"v_ana"}')
    assert isinstance(msg, StartMsg)
    assert msg.voice_id == "v_ana"
    assert msg.format == "pcm_24000"
    assert msg.options == Options()


def test_parse_text() -> None:
    msg = parse_client_msg('{"type":"text","text":"olá"}')
    assert isinstance(msg, TextMsg)
    assert msg.text == "olá"
    assert msg.flush is False


def test_parse_text_flush() -> None:
    msg = parse_client_msg('{"type":"text","text":"fim.","flush":true}')
    assert isinstance(msg, TextMsg)
    assert msg.flush is True


def test_parse_cancel() -> None:
    msg = parse_client_msg('{"type":"cancel"}')
    assert isinstance(msg, CancelMsg)


def test_parse_end() -> None:
    msg = parse_client_msg('{"type":"end"}')
    assert isinstance(msg, EndMsg)


def test_parse_invalido() -> None:
    with pytest.raises(ValidationError):
        parse_client_msg('{"type":"desconhecido"}')


# ---------------------------------------------------------------------------
# Testes de registry
# ---------------------------------------------------------------------------


def test_registry_sem_motor() -> None:
    from kvoice.engine.registry import can_admit, get_engine

    assert get_engine() is None
    assert can_admit() is False


def test_registry_com_motor(engine: _FakeEngine) -> None:
    from kvoice.engine.registry import can_admit, get_engine

    assert get_engine() is engine
    assert can_admit() is True


def test_registry_admissao_cheia() -> None:
    from kvoice.engine.registry import _ADMISSION_MAX_QUEUE, can_admit

    eng = _FakeEngine()
    eng._queued = _ADMISSION_MAX_QUEUE
    set_engine(eng)  # type: ignore[arg-type]
    assert can_admit() is False


# ---------------------------------------------------------------------------
# Testes de WebSocket (sync via TestClient)
# ---------------------------------------------------------------------------


def test_ws_sem_motor(fake_client: Any, fake_token: Any, fake_voice: Any) -> None:
    """Sem engine disponível → routing retorna None → capacity error após start."""
    app = _make_app()
    with (
        _auth_patch(fake_client, fake_token),
        _voice_patch(fake_voice),
        _routing_patch(None),
        TestClient(app) as client,
        client.websocket_connect("/v1/tts/stream?token=tok") as ws,
    ):
        ws.send_json({"type": "start", "voice_id": "v_fake"})
        data = ws.receive_json()
        assert data["type"] == "error"
        assert data["code"] == "capacity"


def test_ws_token_invalido(
    engine: _FakeEngine, fake_client: Any, fake_token: Any, fake_voice: Any
) -> None:
    app = _make_app()
    with (
        patch("kvoice.api.routers.tts._autenticar_ws", AsyncMock(return_value=None)),
        TestClient(app) as client,
        client.websocket_connect("/v1/tts/stream?token=invalido") as ws,
    ):
        data = ws.receive_json()
        assert data["type"] == "error"
        assert data["code"] == "unauthorized"


def test_ws_sem_escopo(engine: _FakeEngine, fake_client: Any, fake_voice: Any) -> None:
    token_sem_escopo = types.SimpleNamespace(
        scopes="voices:read",
        is_active=True,
        has_scope=lambda scope: scope in {"voices:read"},
    )

    app = _make_app()
    with (
        _auth_patch(fake_client, token_sem_escopo),
        _voice_patch(fake_voice),
        TestClient(app) as client,
        client.websocket_connect("/v1/tts/stream?token=tok") as ws,
    ):
        data = ws.receive_json()
        assert data["type"] == "error"
        assert data["code"] == "forbidden"


def test_ws_voz_nao_encontrada(engine: _FakeEngine, fake_client: Any, fake_token: Any) -> None:
    app = _make_app()
    with (
        _auth_patch(fake_client, fake_token),
        patch("kvoice.api.routers.tts._buscar_voz", AsyncMock(return_value=None)),
        TestClient(app) as client,
        client.websocket_connect("/v1/tts/stream?token=tok") as ws,
    ):
        ws.send_json({"type": "start", "voice_id": "v_nao_existe"})
        data = ws.receive_json()
        assert data["type"] == "error"
        assert data["code"] == "voice_not_found"


def test_ws_fluxo_completo(
    engine: _FakeEngine, fake_client: Any, fake_token: Any, fake_voice: Any
) -> None:
    app = _make_app()
    with (
        _auth_patch(fake_client, fake_token),
        _voice_patch(fake_voice),
        _routing_patch(_kvoice_decision(engine)),
        _uso_patch(),
        TestClient(app) as client,
        client.websocket_connect("/v1/tts/stream?token=tok") as ws,
    ):
        ws.send_json({"type": "start", "voice_id": "v_fake"})
        started = ws.receive_json()
        assert started["type"] == "started"
        assert started["engine"] == "fake"
        assert "request_id" in started

        ws.send_json({"type": "text", "text": "Olá mundo."})
        ws.send_json({"type": "end"})

        chunk = ws.receive_bytes()
        assert len(chunk) > 0

        done = ws.receive_json()
        assert done["type"] == "done"
        assert "ttfa_ms" in done
        assert "audio_ms" in done


def test_ws_cancel(engine: _FakeEngine, fake_client: Any, fake_token: Any, fake_voice: Any) -> None:
    app = _make_app()
    with (
        _auth_patch(fake_client, fake_token),
        _voice_patch(fake_voice),
        _routing_patch(_kvoice_decision(engine)),
        _uso_patch(),
        TestClient(app) as client,
        client.websocket_connect("/v1/tts/stream?token=tok") as ws,
    ):
        ws.send_json({"type": "start", "voice_id": "v_fake"})
        ws.receive_json()  # started

        ws.send_json({"type": "text", "text": "texto"})
        ws.send_json({"type": "cancel"})
        # conexão encerra sem mensagem done


# ---------------------------------------------------------------------------
# Gate da Fase 1 — funcionalidade (sem GPU; threshold generoso para CPU)
# ---------------------------------------------------------------------------


def test_ws_concorrencia(
    engine: _FakeEngine, fake_client: Any, fake_token: Any, fake_voice: Any
) -> None:
    """N streams simultâneos completam sem deadlock ou erro."""
    N = 4
    app = _make_app()
    resultados: list[str] = []
    lock = threading.Lock()

    def _sessao() -> None:
        with (
            TestClient(app) as client,
            client.websocket_connect("/v1/tts/stream?token=tok") as ws,
        ):
            ws.send_json({"type": "start", "voice_id": "v_fake"})
            ws.receive_json()  # started
            ws.send_json({"type": "text", "text": "Olá, tudo bem com você hoje?"})
            ws.send_json({"type": "end"})
            ws.receive_bytes()  # primeiro chunk de áudio
            msg = ws.receive_json()
            with lock:
                resultados.append(msg.get("type", ""))

    with (
        _auth_patch(fake_client, fake_token),
        _voice_patch(fake_voice),
        _routing_patch(_kvoice_decision(engine)),
        _uso_patch(),
    ):
        threads = [threading.Thread(target=_sessao) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

    assert len(resultados) == N, f"esperado {N} respostas, recebido {len(resultados)}"
    assert all(r == "done" for r in resultados)


def test_ws_cancel_timing(
    engine: _FakeEngine, fake_client: Any, fake_token: Any, fake_voice: Any
) -> None:
    """Cancelamento para o stream; WS fecha em < 500 ms em CPU sem motor real."""
    app = _make_app()
    t0: float = 0.0
    with (
        _auth_patch(fake_client, fake_token),
        _voice_patch(fake_voice),
        _routing_patch(_kvoice_decision(engine)),
        _uso_patch(),
        TestClient(app) as client,
        client.websocket_connect("/v1/tts/stream?token=tok") as ws,
    ):
        ws.send_json({"type": "start", "voice_id": "v_fake"})
        ws.receive_json()  # started
        ws.send_json({"type": "text", "text": "Olá mundo, como vai você hoje?"})

        t0 = time.monotonic()
        ws.send_json({"type": "cancel"})
        # Sai do with imediatamente; TestClient aguarda o handler encerrar.

    elapsed_ms = (time.monotonic() - t0) * 1000
    # 500 ms de folga para CPU/CI — gate real (50 ms) é medido em GPU com motor real
    assert elapsed_ms < 500, f"cancelamento demorou {elapsed_ms:.0f} ms"
