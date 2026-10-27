"""Testes das ferramentas MCP: synthesize, list_voices, get_voice."""

from __future__ import annotations

import types
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.shared.exceptions import MCPError

from kvoice.api.routing import RoutingDecision
from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, TTSEngine, Voice
from kvoice.mcp.server import get_voice, list_voices, synthesize

# ---------------------------------------------------------------------------
# Fixtures e helpers
# ---------------------------------------------------------------------------


class _FakeMcpEngine:
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


assert isinstance(_FakeMcpEngine(), TTSEngine)

_PRESIGNED_URL = "https://s3.example.com/outputs/x.ogg?sig=abc"
_ENCODED = b"encoded_audio"
_CONTENT_TYPE = "audio/ogg; codecs=opus"


def _fake_client() -> Any:
    return types.SimpleNamespace(id=uuid.uuid4(), name="Test", is_active=True)


def _fake_token_all() -> Any:
    def _has_scope(scope: str) -> bool:
        return True

    return types.SimpleNamespace(
        scopes="tts:batch,voices:read", is_active=True, has_scope=_has_scope
    )


def _fake_voice(voice_id: str = "v_fake") -> Any:
    v = MagicMock()
    v.id = voice_id
    v.name = "Fake"
    v.is_active = True
    v.style_prompt = None
    v.gender = "feminino"
    v.age_range = "adulto"
    v.style = "neutro"
    v.language = "pt-BR"
    v.origin = "preset"
    v.model_id = None
    return v


def _kvoice_decision() -> RoutingDecision:
    return RoutingDecision(
        engine=_FakeMcpEngine(),  # type: ignore[arg-type]
        engine_name="qwen3-tts",
        effective_voice_id="v_fake",
        is_fallback=False,
        fallback_reason=None,
    )


def _fake_ctx() -> Any:
    ctx = MagicMock()
    ctx.headers = {"authorization": "Bearer test-token"}
    return ctx


def _mock_storage() -> Any:
    s = AsyncMock()
    s.upload = AsyncMock()
    s.presigned_url = AsyncMock(return_value=_PRESIGNED_URL)
    return s


# ---------------------------------------------------------------------------
# synthesize
# ---------------------------------------------------------------------------


async def test_synthesize_retorna_url() -> None:
    """Síntese bem-sucedida devolve dict com url, duration_ms e characters."""
    fc = _fake_client()
    ft = _fake_token_all()
    fv = _fake_voice()

    with (
        patch("kvoice.mcp.server._auth", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.mcp.server._buscar_voz", AsyncMock(return_value=fv)),
        patch("kvoice.mcp.server.decide_engine", AsyncMock(return_value=_kvoice_decision())),
        patch("kvoice.mcp.server.encode_audio", return_value=(_ENCODED, _CONTENT_TYPE)),
        patch("kvoice.mcp.server.get_storage", return_value=_mock_storage()),
    ):
        result = await synthesize("Olá, tudo bem?", "v_fake", ctx=_fake_ctx())

    assert result["url"] == _PRESIGNED_URL
    assert result["duration_ms"] > 0
    assert result["characters"] == len("Olá, tudo bem?")
    assert "request_id" in result


async def test_synthesize_voz_nao_encontrada() -> None:
    """Voz inexistente → MCPError."""
    fc = _fake_client()
    ft = _fake_token_all()

    with (
        patch("kvoice.mcp.server._auth", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.mcp.server._buscar_voz", AsyncMock(return_value=None)),
        pytest.raises(MCPError, match="não encontrada"),
    ):
        await synthesize("Olá", "v_nao_existe", ctx=_fake_ctx())


async def test_synthesize_sem_motor() -> None:
    """Motor indisponível → MCPError."""
    fc = _fake_client()
    ft = _fake_token_all()
    fv = _fake_voice()

    with (
        patch("kvoice.mcp.server._auth", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.mcp.server._buscar_voz", AsyncMock(return_value=fv)),
        patch("kvoice.mcp.server.decide_engine", AsyncMock(return_value=None)),
        pytest.raises(MCPError, match="indisponível"),
    ):
        await synthesize("Olá", "v_fake", ctx=_fake_ctx())


async def test_synthesize_formato_invalido() -> None:
    """Formato inválido → MCPError antes de qualquer I/O."""
    fc = _fake_client()
    ft = _fake_token_all()

    with (
        patch("kvoice.mcp.server._auth", AsyncMock(return_value=(fc, ft))),
        pytest.raises(MCPError, match="Formato inválido"),
    ):
        await synthesize("Olá", "v_fake", format="flac_48000", ctx=_fake_ctx())


# ---------------------------------------------------------------------------
# list_voices
# ---------------------------------------------------------------------------


async def test_list_voices_sem_filtro() -> None:
    """Lista todas as vozes ativas."""
    fc = _fake_client()
    ft = _fake_token_all()
    vozes = [_fake_voice("v_ana"), _fake_voice("v_carlos")]

    with (
        patch("kvoice.mcp.server._auth", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.mcp.server._listar_vozes", AsyncMock(return_value=vozes)),
    ):
        result = await list_voices(ctx=_fake_ctx())

    assert len(result) == 2
    assert result[0]["id"] == "v_ana"
    assert result[1]["id"] == "v_carlos"
    assert "name" in result[0]
    assert "language" in result[0]


async def test_list_voices_com_filtro_language() -> None:
    """Filtro language é passado para _listar_vozes."""
    fc = _fake_client()
    ft = _fake_token_all()

    mock_listar = AsyncMock(return_value=[_fake_voice()])
    with (
        patch("kvoice.mcp.server._auth", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.mcp.server._listar_vozes", mock_listar),
    ):
        await list_voices(language="pt-BR", ctx=_fake_ctx())

    mock_listar.assert_awaited_once_with(language="pt-BR")


# ---------------------------------------------------------------------------
# get_voice
# ---------------------------------------------------------------------------


async def test_get_voice_ok() -> None:
    """Voz existente → dict com campos esperados."""
    fc = _fake_client()
    ft = _fake_token_all()
    fv = _fake_voice("v_ana")

    with (
        patch("kvoice.mcp.server._auth", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.mcp.server._buscar_voz", AsyncMock(return_value=fv)),
    ):
        result = await get_voice("v_ana", ctx=_fake_ctx())

    assert result["id"] == "v_ana"
    assert result["language"] == "pt-BR"


async def test_get_voice_nao_encontrada() -> None:
    """Voz inexistente → MCPError."""
    fc = _fake_client()
    ft = _fake_token_all()

    with (
        patch("kvoice.mcp.server._auth", AsyncMock(return_value=(fc, ft))),
        patch("kvoice.mcp.server._buscar_voz", AsyncMock(return_value=None)),
        pytest.raises(MCPError, match="não encontrada"),
    ):
        await get_voice("v_nao_existe", ctx=_fake_ctx())


# ---------------------------------------------------------------------------
# _auth
# ---------------------------------------------------------------------------


async def test_auth_token_ausente() -> None:
    """Sem header Authorization → MCPError."""
    from kvoice.mcp.server import _auth

    ctx = MagicMock()
    ctx.headers = {}
    with pytest.raises(MCPError, match="Token ausente"):
        await _auth(ctx, "tts:batch")


async def test_auth_token_invalido() -> None:
    """Token não encontrado no banco → MCPError."""
    from kvoice.mcp.server import _auth

    ctx = MagicMock()
    ctx.headers = {"authorization": "Bearer token-invalido"}
    with (
        patch("kvoice.mcp.server._validar_token", AsyncMock(return_value=None)),
        pytest.raises(MCPError, match="inválido"),
    ):
        await _auth(ctx, "tts:batch")


async def test_auth_escopo_insuficiente() -> None:
    """Token válido mas sem o escopo pedido → MCPError."""
    from kvoice.mcp.server import _auth

    fc = _fake_client()

    def _sem_escopo(scope: str) -> bool:
        return False

    ft = types.SimpleNamespace(has_scope=_sem_escopo)
    ctx = MagicMock()
    ctx.headers = {"authorization": "Bearer token-ok"}
    with (
        patch("kvoice.mcp.server._validar_token", AsyncMock(return_value=(fc, ft))),
        pytest.raises(MCPError, match="Escopo"),
    ):
        await _auth(ctx, "tts:batch")
