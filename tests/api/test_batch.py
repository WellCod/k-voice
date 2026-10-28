"""Testes do endpoint de síntese em lote: POST /v1/tts."""

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
# Engine fake com synthesize real
# ---------------------------------------------------------------------------


class _FakeBatchEngine:
    name = "qwen3-tts"
    sample_rate = 24_000

    async def stream(
        self,
        text: Any,
        voice: Voice,
        opts: SynthOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        async def _gen() -> AsyncGenerator[AudioChunk, None]:
            yield AudioChunk(data=b"\x00" * 960, sample_rate=24_000, duration_ms=20.0)

        return _gen()

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio:
        return Audio(data=b"\x00" * 48_000, sample_rate=24_000, duration_ms=1000.0, ttfa_ms=50.0)

    def capacity(self) -> Capacity:
        return Capacity(active_streams=0, queued=0, rtf_recent=None)


assert isinstance(_FakeBatchEngine(), TTSEngine)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENCODED = b"audio_encoded"
_CONTENT_TYPE = "audio/ogg; codecs=opus"
_PRESIGNED_URL = "https://s3.example.com/outputs/xxx.ogg?sig=abc"


def _make_app() -> FastAPI:
    from kvoice.api.routers import tts

    app = FastAPI()
    app.include_router(tts.router)
    return app


def _fake_voice_orm() -> Any:
    v = MagicMock()
    v.id = "v_fake"
    v.name = "Fake"
    v.is_active = True
    v.style_prompt = None
    return v


def _fake_client() -> Any:
    return types.SimpleNamespace(id=uuid.uuid4(), name="Test", is_active=True)


def _fake_token_batch() -> Any:
    def _has_scope(scope: str) -> bool:
        return scope in {"tts:batch", "admin"}

    return types.SimpleNamespace(
        scopes="tts:batch", is_active=True, name="tok", has_scope=_has_scope
    )


def _fake_token_stream_only() -> Any:
    def _has_scope(scope: str) -> bool:
        return scope == "tts:stream"

    return types.SimpleNamespace(
        scopes="tts:stream", is_active=True, name="tok", has_scope=_has_scope
    )


def _kvoice_decision() -> RoutingDecision:
    return RoutingDecision(
        engine=_FakeBatchEngine(),  # type: ignore[arg-type]
        engine_name="qwen3-tts",
        effective_voice_id="v_fake",
        is_fallback=False,
        fallback_reason=None,
    )


def _setup_app(
    app: FastAPI,
    fake_client: Any,
    fake_token: Any,
    fake_voice: Any,
) -> None:
    from kvoice.api.deps import _autenticar, get_db

    async def _auth() -> tuple[Any, Any]:
        return fake_client, fake_token

    async def _db() -> Any:
        db = AsyncMock()
        db.get = AsyncMock(return_value=fake_voice)
        db.add = MagicMock()
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[_autenticar] = _auth
    app.dependency_overrides[get_db] = _db


def _mock_storage() -> Any:
    storage = AsyncMock()
    storage.upload = AsyncMock()
    storage.presigned_url = AsyncMock(return_value=_PRESIGNED_URL)
    return storage


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------


def test_lote_bytes_kvoice() -> None:
    """delivery=bytes — áudio retornado diretamente no corpo."""
    fc = _fake_client()
    ft = _fake_token_batch()
    fv = _fake_voice_orm()
    app = _make_app()
    _setup_app(app, fc, ft, fv)

    with (
        patch("kvoice.api.routers.tts.decide_engine", AsyncMock(return_value=_kvoice_decision())),
        patch("kvoice.api.routers.tts.encode_audio", return_value=(_ENCODED, _CONTENT_TYPE)),
        patch("kvoice.api.routers.tts.load_dict", AsyncMock(return_value=[])),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/v1/tts",
            json={"text": "Olá, tudo bem?", "voice_id": "v_fake", "delivery": "bytes"},
        )

    assert resp.status_code == 200
    assert resp.content == _ENCODED
    assert resp.headers["content-type"] == _CONTENT_TYPE
    assert "x-request-id" in resp.headers
    assert "x-duration-ms" in resp.headers


def test_lote_url_kvoice() -> None:
    """delivery=url — URL assinada retornada em JSON."""
    fc = _fake_client()
    ft = _fake_token_batch()
    fv = _fake_voice_orm()
    app = _make_app()
    _setup_app(app, fc, ft, fv)

    with (
        patch("kvoice.api.routers.tts.decide_engine", AsyncMock(return_value=_kvoice_decision())),
        patch("kvoice.api.routers.tts.encode_audio", return_value=(_ENCODED, _CONTENT_TYPE)),
        patch("kvoice.api.routers.tts.get_storage", return_value=_mock_storage()),
        patch("kvoice.api.routers.tts.load_dict", AsyncMock(return_value=[])),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/v1/tts",
            json={
                "text": "Mensagem para o WhatsApp.",
                "voice_id": "v_fake",
                "format": "ogg_opus",
                "delivery": "url",
                "url_ttl_s": 3600,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "request_id" in data
    assert data["url"] == _PRESIGNED_URL
    assert data["characters"] == len("Mensagem para o WhatsApp.")
    assert data["duration_ms"] > 0


def test_lote_formato_wav() -> None:
    """Formato wav_24000 com delivery=bytes."""
    fc = _fake_client()
    ft = _fake_token_batch()
    fv = _fake_voice_orm()
    app = _make_app()
    _setup_app(app, fc, ft, fv)

    with (
        patch("kvoice.api.routers.tts.decide_engine", AsyncMock(return_value=_kvoice_decision())),
        patch(
            "kvoice.api.routers.tts.encode_audio",
            return_value=(b"wav_bytes", "audio/wav"),
        ),
        patch("kvoice.api.routers.tts.load_dict", AsyncMock(return_value=[])),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/v1/tts",
            json={"text": "Olá", "voice_id": "v_fake", "format": "wav_24000", "delivery": "bytes"},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"


def test_lote_sem_motor() -> None:
    """Sem motor disponível → 503."""
    fc = _fake_client()
    ft = _fake_token_batch()
    fv = _fake_voice_orm()
    app = _make_app()
    _setup_app(app, fc, ft, fv)

    with (
        patch("kvoice.api.routers.tts.decide_engine", AsyncMock(return_value=None)),
        TestClient(app) as client,
    ):
        resp = client.post("/v1/tts", json={"text": "Olá", "voice_id": "v_fake"})

    assert resp.status_code == 503


def test_lote_voz_nao_encontrada() -> None:
    """Voz inexistente → 404."""
    fc = _fake_client()
    ft = _fake_token_batch()
    app = _make_app()
    _setup_app(app, fc, ft, None)  # db.get retorna None

    with TestClient(app) as client:
        resp = client.post("/v1/tts", json={"text": "Olá", "voice_id": "v_nao_existe"})

    assert resp.status_code == 404


def test_lote_sem_escopo() -> None:
    """Token sem tts:batch → 403."""
    fc = _fake_client()
    ft = _fake_token_stream_only()
    fv = _fake_voice_orm()
    app = _make_app()
    _setup_app(app, fc, ft, fv)

    with TestClient(app) as client:
        resp = client.post("/v1/tts", json={"text": "Olá", "voice_id": "v_fake"})

    assert resp.status_code == 403
