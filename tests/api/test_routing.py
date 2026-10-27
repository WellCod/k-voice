"""Testes da lógica de roteamento por cliente."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kvoice.api.routing import RoutingDecision, decide_engine
from kvoice.db.models import RoutingMode, RoutingRule
from kvoice.engine.types import Capacity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_kvoice(queued: int = 0) -> MagicMock:
    engine = MagicMock()
    engine.name = "qwen3-tts"
    engine.sample_rate = 24000
    engine.capacity.return_value = Capacity(active_streams=0, queued=queued, rtf_recent=None)
    return engine


def _mock_eleven() -> MagicMock:
    engine = MagicMock()
    engine.name = "elevenlabs"
    engine.sample_rate = 24000
    return engine



async def _decide(
    voice_id: str,
    rule: RoutingRule | None,
    kvoice: MagicMock | None,
    eleven: MagicMock | None,
) -> RoutingDecision | None:
    client_id = uuid.uuid4()
    with (
        patch("kvoice.api.routing._buscar_regra", AsyncMock(return_value=rule)),
        patch("kvoice.api.routing.get_engine", return_value=kvoice),
        patch("kvoice.api.routing._eleven", return_value=eleven),
    ):
        return await decide_engine(client_id, voice_id)


def _rule(
    mode: RoutingMode,
    kvoice_pct: float = 1.0,
    voice_mapping: dict[str, str] | None = None,
) -> MagicMock:
    r = MagicMock(spec=RoutingRule)
    r.mode = mode
    r.kvoice_pct = kvoice_pct
    r.voice_mapping = json.dumps(voice_mapping) if voice_mapping else None
    return r


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sem_regra_usa_kvoice() -> None:
    kvoice = _mock_kvoice(queued=0)
    decision = await _decide("v_ana", None, kvoice, None)
    assert decision is not None
    assert decision.engine is kvoice
    assert decision.engine_name == "qwen3-tts"
    assert decision.effective_voice_id == "v_ana"
    assert not decision.is_fallback
    assert decision.fallback_reason is None


@pytest.mark.asyncio
async def test_regra_kvoice_usa_kvoice() -> None:
    rule = _rule(RoutingMode.kvoice)
    kvoice = _mock_kvoice(queued=0)
    decision = await _decide("v_ana", rule, kvoice, None)
    assert decision is not None
    assert decision.engine is kvoice
    assert not decision.is_fallback


@pytest.mark.asyncio
async def test_kvoice_cheio_fallback_eleven() -> None:
    """k-voice com fila cheia → fallback automático para ElevenLabs."""
    kvoice = _mock_kvoice(queued=10)  # >= _ADMISSION_MAX_QUEUE (8)
    eleven = _mock_eleven()
    decision = await _decide("v_ana", None, kvoice, eleven)
    assert decision is not None
    assert decision.engine is eleven
    assert decision.engine_name == "elevenlabs"
    assert decision.is_fallback
    assert decision.fallback_reason == "capacity"


@pytest.mark.asyncio
async def test_kvoice_cheio_sem_fallback_retorna_none() -> None:
    kvoice = _mock_kvoice(queued=10)
    decision = await _decide("v_ana", None, kvoice, None)
    assert decision is None


@pytest.mark.asyncio
async def test_mode_elevenlabs_usa_eleven() -> None:
    rule = _rule(RoutingMode.elevenlabs)
    eleven = _mock_eleven()
    decision = await _decide("v_ana", rule, None, eleven)
    assert decision is not None
    assert decision.engine is eleven
    assert decision.engine_name == "elevenlabs"
    assert not decision.is_fallback


@pytest.mark.asyncio
async def test_mode_elevenlabs_sem_eleven_retorna_none() -> None:
    rule = _rule(RoutingMode.elevenlabs)
    decision = await _decide("v_ana", rule, None, None)
    assert decision is None


@pytest.mark.asyncio
async def test_voice_mapping_remapeia_id() -> None:
    rule = _rule(RoutingMode.elevenlabs, voice_mapping={"v_ana": "el_ana_xyz"})
    eleven = _mock_eleven()
    decision = await _decide("v_ana", rule, None, eleven)
    assert decision is not None
    assert decision.effective_voice_id == "el_ana_xyz"


@pytest.mark.asyncio
async def test_voice_mapping_sem_entrada_mantém_id() -> None:
    rule = _rule(RoutingMode.elevenlabs, voice_mapping={"v_outro": "el_outro"})
    eleven = _mock_eleven()
    decision = await _decide("v_ana", rule, None, eleven)
    assert decision is not None
    assert decision.effective_voice_id == "v_ana"


@pytest.mark.asyncio
async def test_percentual_pct_1_usa_kvoice() -> None:
    """kvoice_pct=1.0 → sempre k-voice."""
    rule = _rule(RoutingMode.percentual, kvoice_pct=1.0)
    kvoice = _mock_kvoice(queued=0)
    decision = await _decide("v_ana", rule, kvoice, None)
    assert decision is not None
    assert decision.engine is kvoice


@pytest.mark.asyncio
async def test_percentual_pct_0_usa_eleven() -> None:
    """kvoice_pct=0.0 → sempre ElevenLabs."""
    rule = _rule(RoutingMode.percentual, kvoice_pct=0.0)
    eleven = _mock_eleven()
    kvoice = _mock_kvoice(queued=0)
    with patch("kvoice.api.routing.random.random", return_value=0.5):
        decision = await _decide("v_ana", rule, kvoice, eleven)
    assert decision is not None
    assert decision.engine is eleven


@pytest.mark.asyncio
async def test_percentual_eleven_indisponivel_usa_kvoice() -> None:
    """Percentual sorteou ElevenLabs mas ela não está disponível → k-voice como fallback."""
    rule = _rule(RoutingMode.percentual, kvoice_pct=0.0)
    kvoice = _mock_kvoice(queued=0)
    with patch("kvoice.api.routing.random.random", return_value=0.5):
        decision = await _decide("v_ana", rule, kvoice, None)
    assert decision is not None
    assert decision.engine is kvoice
    assert decision.is_fallback
    assert decision.fallback_reason == "elevenlabs_unavailable"
