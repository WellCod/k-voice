"""Lógica de roteamento por cliente: kvoice, elevenlabs ou percentual."""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from kvoice.db.models import RoutingMode, RoutingRule
from kvoice.db.models import Voice as DbVoice
from kvoice.db.session import session_factory
from kvoice.engine.registry import _ADMISSION_MAX_QUEUE, get_engine
from kvoice.engine.types import TTSEngine, Voice


@dataclass
class RoutingDecision:
    engine: TTSEngine
    engine_name: str
    effective_voice_id: str
    is_fallback: bool
    fallback_reason: str | None

    def voz(self, orm_voice: DbVoice) -> Voice:
        """Monta a voz do motor; clonagem depende de ref_audio e ref_text."""
        return Voice(
            id=self.effective_voice_id,
            name=orm_voice.name,
            language=orm_voice.language,
            model_id=orm_voice.model_id,
            ref_audio=orm_voice.ref_audio_key,
            ref_text=orm_voice.ref_text,
            style_prompt=orm_voice.style_prompt,
        )


async def _buscar_regra(client_id: uuid.UUID) -> RoutingRule | None:
    async with session_factory()() as db:
        result = await db.execute(
            select(RoutingRule)
            .where(RoutingRule.client_id == client_id, RoutingRule.is_active.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none()


def _voz_elevenlabs(
    voice_id: str, mapping_json: str | None, padrao_da_voz: str | None
) -> str | None:
    """Voz da ElevenLabs para esta fala: mapa da regra do cliente, senão a da voz.

    None quando nenhum dos dois existe. O id do k-voice nunca vai para a ElevenLabs,
    que o recusa e derruba a fala justamente no pico, quando o fallback entra.
    """
    if mapping_json:
        try:
            mapping: dict[str, str] = json.loads(mapping_json)
        except (json.JSONDecodeError, TypeError):
            mapping = {}
        if mapping.get(voice_id):
            return mapping[voice_id]
    return padrao_da_voz or None


def _eleven() -> TTSEngine | None:
    from kvoice.engine.elevenlabs import get_elevenlabs_engine

    return get_elevenlabs_engine()


async def decide_engine(
    client_id: uuid.UUID,
    voice_id: str,
    elevenlabs_voice_id: str | None = None,
) -> RoutingDecision | None:
    """Decide qual engine usar para a requisição.

    `elevenlabs_voice_id` é a voz equivalente cadastrada na voz do k-voice; o mapa da
    regra do cliente tem prioridade sobre ela. Sem nenhum dos dois a ElevenLabs não é
    usada. Retorna None quando nenhum engine pode atender (o cliente recebe 503
    `capacity` e o plugin do LiveKit cai na ElevenLabs com a voz que ele conhece).
    """
    rule = await _buscar_regra(client_id)
    kvoice = get_engine()
    eleven = _eleven()

    mode = rule.mode if rule else RoutingMode.kvoice
    voz_eleven = _voz_elevenlabs(
        voice_id, rule.voice_mapping if rule else None, elevenlabs_voice_id
    )
    # ElevenLabs só serve a fala se estiver configurada e souber qual voz usar.
    eleven_utilizavel = eleven if voz_eleven is not None else None

    if mode == RoutingMode.elevenlabs:
        if eleven_utilizavel is None or voz_eleven is None:
            return None
        return RoutingDecision(
            engine=eleven_utilizavel,
            engine_name="elevenlabs",
            effective_voice_id=voz_eleven,
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
        if eleven_utilizavel is not None and voz_eleven is not None:
            return RoutingDecision(
                engine=eleven_utilizavel,
                engine_name="elevenlabs",
                effective_voice_id=voz_eleven,
                is_fallback=True,
                fallback_reason="capacity",
            )
        return None  # cheio e sem fallback

    # percentual sorteou ElevenLabs
    if eleven_utilizavel is not None and voz_eleven is not None:
        return RoutingDecision(
            engine=eleven_utilizavel,
            engine_name="elevenlabs",
            effective_voice_id=voz_eleven,
            is_fallback=False,
            fallback_reason=None,
        )

    # ElevenLabs indisponível ou sem voz equivalente → cai no k-voice se possível
    if kvoice is not None:
        cap = kvoice.capacity()
        if cap.queued < _ADMISSION_MAX_QUEUE:
            return RoutingDecision(
                engine=kvoice,
                engine_name=kvoice.name,
                effective_voice_id=voice_id,
                is_fallback=True,
                fallback_reason=(
                    "elevenlabs_unavailable" if eleven is None else "elevenlabs_voice_unmapped"
                ),
            )
    return None
