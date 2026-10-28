"""Lógica de roteamento por cliente: kvoice, elevenlabs ou percentual."""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from kvoice.db.models import RoutingMode, RoutingRule
from kvoice.db.session import session_factory
from kvoice.engine.registry import _ADMISSION_MAX_QUEUE, get_engine
from kvoice.engine.types import TTSEngine


@dataclass
class RoutingDecision:
    engine: TTSEngine
    engine_name: str
    effective_voice_id: str
    is_fallback: bool
    fallback_reason: str | None


async def _buscar_regra(client_id: uuid.UUID) -> RoutingRule | None:
    async with session_factory()() as db:
        result = await db.execute(
            select(RoutingRule)
            .where(RoutingRule.client_id == client_id, RoutingRule.is_active.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none()


def _remap_voice(voice_id: str, mapping_json: str | None) -> str:
    if not mapping_json:
        return voice_id
    try:
        mapping: dict[str, str] = json.loads(mapping_json)
        return mapping.get(voice_id, voice_id)
    except (json.JSONDecodeError, TypeError):
        return voice_id


def _eleven() -> TTSEngine | None:
    from kvoice.engine.elevenlabs import get_elevenlabs_engine

    return get_elevenlabs_engine()


async def decide_engine(
    client_id: uuid.UUID,
    voice_id: str,
) -> RoutingDecision | None:
    """Decide qual engine usar para a requisição.

    Retorna None quando nenhum engine está disponível (capacity excedida sem fallback).
    """
    rule = await _buscar_regra(client_id)
    kvoice = get_engine()
    eleven = _eleven()

    mode = rule.mode if rule else RoutingMode.kvoice
    voice_mapping = rule.voice_mapping if rule else None

    if mode == RoutingMode.elevenlabs:
        if eleven is None:
            return None
        return RoutingDecision(
            engine=eleven,
            engine_name="elevenlabs",
            effective_voice_id=_remap_voice(voice_id, voice_mapping),
            is_fallback=False,
            fallback_reason=None,
        )

    # kvoice ou percentual: tenta k-voice primeiro
    use_kvoice = True
    if mode == RoutingMode.percentual and rule is not None:
        use_kvoice = random.random() < rule.kvoice_pct

    if use_kvoice and kvoice is not None:
        cap = kvoice.capacity()
        if cap.queued < _ADMISSION_MAX_QUEUE:
            return RoutingDecision(
                engine=kvoice,
                engine_name=kvoice.name,
                effective_voice_id=voice_id,
                is_fallback=False,
                fallback_reason=None,
            )
        # capacidade esgotada → fallback para ElevenLabs
        if eleven is not None:
            return RoutingDecision(
                engine=eleven,
                engine_name="elevenlabs",
                effective_voice_id=_remap_voice(voice_id, voice_mapping),
                is_fallback=True,
                fallback_reason="capacity",
            )
        return None  # cheio e sem fallback

    # percentual sorteou ElevenLabs
    if eleven is not None:
        return RoutingDecision(
            engine=eleven,
            engine_name="elevenlabs",
            effective_voice_id=_remap_voice(voice_id, voice_mapping),
            is_fallback=False,
            fallback_reason=None,
        )

    # ElevenLabs indisponível → cai no k-voice se possível
    if kvoice is not None:
        cap = kvoice.capacity()
        if cap.queued < _ADMISSION_MAX_QUEUE:
            return RoutingDecision(
                engine=kvoice,
                engine_name=kvoice.name,
                effective_voice_id=voice_id,
                is_fallback=True,
                fallback_reason="elevenlabs_unavailable",
            )
    return None
