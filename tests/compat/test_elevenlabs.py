"""Testes da camada de compatibilidade com a API da ElevenLabs."""

from __future__ import annotations

import types
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kvoice.api.routing import RoutingDecision
from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, TTSEngine, Voice

# ---------------------------------------------------------------------------
# Engine fake
# ---------------------------------------------------------------------------


class _FakeEngine:
    name = "qwen3-tts"
    sample_rate = 24_000

    async def stream(
        self, text: Any, voice: Voice, opts: SynthOptions
    ) -> AsyncGenerator[AudioChunk, None]:
        async def _gen() -> AsyncGenerator[AudioChunk, None]:
            yield AudioChunk(data=b"\x00" * 960, sample_rate=24_000, duration_ms=20.0)

        return _gen()

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio:
        return Audio(data=b"\x00" * 48_000, sample_rate=24_000, duration_ms=1000.0, ttfa_ms=50.0)

    def capacity(self) -> Capacity:
        return Capacity(active_streams=0, queued=0, rtf_recent=None)


assert isinstance(_FakeEngine(), TTSEngine)

_ENCODED = b"audio_encoded"
_CONTENT_TYPE = "audio/mpeg"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    from kvoice.compat.elevenlabs import router

    app = FastAPI()
    app.include_router(router)
    return app


def _fake_client() -> Any:
    return types.SimpleNamespace(id=uuid.uuid4(), name="Test", is_active=True)


def _fake_token() -> Any:
    def _has_scope(scope: str) -> bool:
        return True

    return types.SimpleNamespace(scopes="tts:batch", is_active=True, has_scope=_has_scope)


def _fake_voice(voice_id: str = "v_fake") -> Any:
    v = MagicMock()
    v.id = voice_id
    v.name = "Fake"
    v.is_active = True
    v.style_prompt = None
    return v


def _kvoice_decision() -> RoutingDecision:
    return RoutingDecision(
        engine=_FakeEngine(),  # type: ignore[arg-type]
        engine_name="qwen3-tts",
        effective_voice_id="v_fake",
        is_fallback=False,
        fallback_reason=None,
    )


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------


def test_compat_mp3_xi_key() -> None:
    """Síntese com xi-api-key e formato mp3 padrão."""
    fc = _fake_client()
    ft = _fake_token()
    fv = _fake_voice()

    app = _make_app()
    with (
        patch("kvoice.compat.elevenlabs._autenticar", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.compat.elevenlabs._buscar_voz", AsyncMock(return_value=fv)),
        patch("kvoice.compat.elevenlabs.decide_engine", AsyncMock(return_value=_kvoice_decision())),
        patch("kvoice.compat.elevenlabs.encode_audio", return_value=(_ENCODED, _CONTENT_TYPE)),
        patch("kvoice.compat.elevenlabs.load_dict", AsyncMock(return_value=[])),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/v1/text-to-speech/v_fake",
            json={"text": "Olá, tudo bem?"},
            headers={"xi-api-key": "minha-chave"},
        )

    assert resp.status_code == 200
    assert resp.content == _ENCODED
    assert resp.headers["content-type"] == _CONTENT_TYPE


def test_compat_ogg_bearer() -> None:
    """Síntese com Authorization: Bearer e formato opus."""
    fc = _fake_client()
    ft = _fake_token()
    fv = _fake_voice()

    app = _make_app()
    with (
        patch("kvoice.compat.elevenlabs._autenticar", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.compat.elevenlabs._buscar_voz", AsyncMock(return_value=fv)),
        patch("kvoice.compat.elevenlabs.decide_engine", AsyncMock(return_value=_kvoice_decision())),
        patch(
            "kvoice.compat.elevenlabs.encode_audio",
            return_value=(b"ogg_bytes", "audio/ogg; codecs=opus"),
        ),
        patch("kvoice.compat.elevenlabs.load_dict", AsyncMock(return_value=[])),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/v1/text-to-speech/v_fake?output_format=opus_48000_32",
            json={"text": "Testando"},
            headers={"Authorization": "Bearer meu-token"},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/ogg")


def test_compat_speed() -> None:
    """voice_settings.speed é repassado ao motor."""
    fc = _fake_client()
    ft = _fake_token()
    fv = _fake_voice()

    captured_opts: list[SynthOptions] = []

    async def _fake_synthesize(text: str, voice: Voice, opts: SynthOptions) -> Audio:
        captured_opts.append(opts)
        return Audio(data=b"\x00" * 48_000, sample_rate=24_000, duration_ms=1000.0, ttfa_ms=50.0)

    engine = _FakeEngine()
    engine.synthesize = _fake_synthesize  # type: ignore[method-assign]
    decision = RoutingDecision(
        engine=engine,  # type: ignore[arg-type]
        engine_name="qwen3-tts",
        effective_voice_id="v_fake",
        is_fallback=False,
        fallback_reason=None,
    )

    app = _make_app()
    with (
        patch("kvoice.compat.elevenlabs._autenticar", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.compat.elevenlabs._buscar_voz", AsyncMock(return_value=fv)),
        patch("kvoice.compat.elevenlabs.decide_engine", AsyncMock(return_value=decision)),
        patch("kvoice.compat.elevenlabs.encode_audio", return_value=(_ENCODED, _CONTENT_TYPE)),
        patch("kvoice.compat.elevenlabs.load_dict", AsyncMock(return_value=[])),
        TestClient(app) as client,
    ):
        client.post(
            "/v1/text-to-speech/v_fake",
            json={"text": "Teste", "voice_settings": {"speed": 1.3}},
            headers={"xi-api-key": "chave"},
        )

    assert len(captured_opts) == 1
    assert captured_opts[0].speed == 1.3


def test_compat_voz_nao_encontrada() -> None:
    """Voz inexistente → 404."""
    fc = _fake_client()
    ft = _fake_token()

    app = _make_app()
    with (
        patch("kvoice.compat.elevenlabs._autenticar", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.compat.elevenlabs._buscar_voz", AsyncMock(return_value=None)),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/v1/text-to-speech/v_nao_existe",
            json={"text": "Olá"},
            headers={"xi-api-key": "chave"},
        )

    assert resp.status_code == 404


def test_compat_sem_motor() -> None:
    """Motor indisponível → 503."""
    fc = _fake_client()
    ft = _fake_token()
    fv = _fake_voice()

    app = _make_app()
    with (
        patch("kvoice.compat.elevenlabs._autenticar", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.compat.elevenlabs._buscar_voz", AsyncMock(return_value=fv)),
        patch("kvoice.compat.elevenlabs.decide_engine", AsyncMock(return_value=None)),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/v1/text-to-speech/v_fake",
            json={"text": "Olá"},
            headers={"xi-api-key": "chave"},
        )

    assert resp.status_code == 503


def test_compat_sem_auth() -> None:
    """Sem header de autenticação → 401."""
    app = _make_app()
    with TestClient(app) as client:
        resp = client.post("/v1/text-to-speech/v_fake", json={"text": "Olá"})

    assert resp.status_code == 401
