"""Testes E2E do padrão de chamada SIP: streaming de tokens e múltiplos turnos.

Cobre os cenários específicos de uma chamada VoIP:
  - texto chegando palavra a palavra (tokens do LLM)
  - flush em fronteiras de sentença
  - múltiplos turnos consecutivos por chamada
  - roteamento misto (k-voice + ElevenLabs) em chamadas concorrentes
"""

from __future__ import annotations

import types
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from kvoice.api.routing import RoutingDecision
from kvoice.engine.registry import clear_engine, set_engine
from kvoice.engine.types import AudioChunk, Capacity, SynthOptions, TTSEngine, Voice

# ---------------------------------------------------------------------------
# Engines fake
# ---------------------------------------------------------------------------


class _FakeEngine:
    name = "qwen3-tts"
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
                yield AudioChunk(data=b"\x00" * 960, sample_rate=24000, duration_ms=20.0)

        return _gen()

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Any: ...

    def capacity(self) -> Capacity:
        return Capacity(active_streams=0, queued=self._queued, rtf_recent=None)


class _FakeElevenEngine(_FakeEngine):
    name = "elevenlabs"


assert isinstance(_FakeEngine(), TTSEngine)
assert isinstance(_FakeElevenEngine(), TTSEngine)


# ---------------------------------------------------------------------------
# Fixtures e helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_engine() -> Any:
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
def fake_token() -> Any:
    def _has_scope(scope: str) -> bool:
        return scope in {"tts:stream", "admin"}

    return types.SimpleNamespace(
        scopes="tts:stream",
        is_active=True,
        name="tok",
        has_scope=_has_scope,
    )


@pytest.fixture()
def fake_voice() -> Any:
    return types.SimpleNamespace(
        id="v_fake", name="Fake", language="pt-BR", is_active=True, style_prompt=None
    )


def _make_app() -> Any:
    from fastapi import FastAPI

    from kvoice.api.routers import tts

    app = FastAPI()
    app.include_router(tts.router)
    return app


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
    return patch("kvoice.api.routers.tts._gravar_uso", AsyncMock(return_value=None))


def _routing_patch(decision: RoutingDecision | None) -> Any:
    return patch("kvoice.api.routers.tts.decide_engine", AsyncMock(return_value=decision))


def _kvoice_decision(engine: _FakeEngine) -> RoutingDecision:
    return RoutingDecision(
        engine=engine,  # type: ignore[arg-type]
        engine_name=engine.name,
        effective_voice_id="v_fake",
        is_fallback=False,
        fallback_reason=None,
    )


# ---------------------------------------------------------------------------
# Testes de padrão de chamada SIP
# ---------------------------------------------------------------------------


def test_turno_streaming_de_tokens(
    engine: _FakeEngine, fake_client: Any, fake_token: Any, fake_voice: Any
) -> None:
    """Texto chegando palavra a palavra — verifica que o servidor produz áudio."""
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
        assert started["engine"] == "qwen3-tts"

        # Simula LLM enviando uma palavra de cada vez
        for palavra in ["Olá", "como", "você", "está"]:
            ws.send_json({"type": "text", "text": palavra + " "})

        ws.send_json({"type": "end"})

        chunk = ws.receive_bytes()
        assert len(chunk) > 0

        done = ws.receive_json()
        assert done["type"] == "done"


def test_flush_em_fronteira_de_sentenca(
    engine: _FakeEngine, fake_client: Any, fake_token: Any, fake_voice: Any
) -> None:
    """Flush em fronteira de sentença → servidor retorna mensagem 'flushed'."""
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

        # Primeira sentença
        ws.send_json({"type": "text", "text": "Olá, tudo bem."})
        # Flush sinaliza fim de sentença
        ws.send_json({"type": "text", "text": "", "flush": True})

        # Segunda sentença + end
        ws.send_json({"type": "text", "text": "Como posso ajudar?"})
        ws.send_json({"type": "end"})

        # Coleta todas as mensagens até "done"
        msgs: list[dict[str, Any]] = []
        tipos_texto: list[str] = []
        while True:
            # pode chegar bytes (áudio) ou JSON
            try:
                chunk = ws.receive_bytes()
                msgs.append({"_bytes": len(chunk)})
            except Exception:
                pass
            try:
                msg = ws.receive_json()
                msgs.append(msg)
                tipos_texto.append(msg.get("type", ""))
                if msg.get("type") in ("done", "error"):
                    break
            except Exception:
                break

        assert "done" in tipos_texto
        # "flushed" é enviado após processar o flush do normalizador
        assert "flushed" in tipos_texto


def test_multiplos_turnos_por_chamada(
    engine: _FakeEngine, fake_client: Any, fake_token: Any, fake_voice: Any
) -> None:
    """Múltiplos turnos consecutivos de TTS na mesma chamada (N conexões WS)."""
    N_TURNOS = 3
    app = _make_app()
    turnos_ok = 0

    for turno_idx in range(N_TURNOS):
        texto = f"Este é o turno número {turno_idx + 1} da chamada."
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
            ws.send_json({"type": "text", "text": texto})
            ws.send_json({"type": "end"})
            ws.receive_bytes()  # áudio
            done = ws.receive_json()
            if done.get("type") == "done":
                turnos_ok += 1

    assert turnos_ok == N_TURNOS


def test_roteamento_misto_sequencial(fake_client: Any, fake_token: Any, fake_voice: Any) -> None:
    """Turnos sequenciais alternando k-voice e ElevenLabs — ambos completam com sucesso."""
    kvoice_eng = _FakeEngine()
    eleven_eng = _FakeElevenEngine()

    cenarios = [
        RoutingDecision(
            engine=kvoice_eng,  # type: ignore[arg-type]
            engine_name="qwen3-tts",
            effective_voice_id="v_fake",
            is_fallback=False,
            fallback_reason=None,
        ),
        RoutingDecision(
            engine=eleven_eng,  # type: ignore[arg-type]
            engine_name="elevenlabs",
            effective_voice_id="v_fake",
            is_fallback=True,
            fallback_reason="capacity",
        ),
    ]

    app = _make_app()
    engines_vistas: list[str] = []

    for decision in cenarios:
        with (
            _auth_patch(fake_client, fake_token),
            _voice_patch(fake_voice),
            _routing_patch(decision),
            _uso_patch(),
            TestClient(app) as client,
            client.websocket_connect("/v1/tts/stream?token=tok") as ws,
        ):
            ws.send_json({"type": "start", "voice_id": "v_fake"})
            started = ws.receive_json()
            ws.send_json({"type": "text", "text": "Olá, como vai?"})
            ws.send_json({"type": "end"})
            ws.receive_bytes()
            done = ws.receive_json()
            assert done["type"] == "done"
            engines_vistas.append(started.get("engine", ""))

    assert "qwen3-tts" in engines_vistas
    assert "elevenlabs" in engines_vistas


def test_turno_elevenlabs_fallback(fake_client: Any, fake_token: Any, fake_voice: Any) -> None:
    """Fallback para ElevenLabs: started.engine == 'elevenlabs', turno completa normal."""
    eleven_eng = _FakeElevenEngine()
    decision = RoutingDecision(
        engine=eleven_eng,  # type: ignore[arg-type]
        engine_name="elevenlabs",
        effective_voice_id="v_fake",
        is_fallback=True,
        fallback_reason="capacity",
    )

    app = _make_app()
    with (
        _auth_patch(fake_client, fake_token),
        _voice_patch(fake_voice),
        _routing_patch(decision),
        _uso_patch(),
        TestClient(app) as client,
        client.websocket_connect("/v1/tts/stream?token=tok") as ws,
    ):
        ws.send_json({"type": "start", "voice_id": "v_fake"})
        started = ws.receive_json()
        assert started["engine"] == "elevenlabs"

        ws.send_json({"type": "text", "text": "Olá, tudo bem com você?"})
        ws.send_json({"type": "end"})
        ws.receive_bytes()
        done = ws.receive_json()
        assert done["type"] == "done"
