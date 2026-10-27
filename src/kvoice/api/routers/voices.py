from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from kvoice.api.deps import DbSession, _exigir_scope
from kvoice.api.schemas import VoiceResponse
from kvoice.db.models import Voice

router = APIRouter(prefix="/v1/voices", tags=["voices"])
_leitura = Depends(_exigir_scope("voices:read"))


@router.get("", response_model=list[VoiceResponse], dependencies=[_leitura])
async def listar_vozes(db: DbSession) -> list[Voice]:
    result = await db.execute(select(Voice).where(Voice.is_active.is_(True)).order_by(Voice.name))
    return list(result.scalars().all())


@router.get("/{voice_id}", response_model=VoiceResponse, dependencies=[_leitura])
async def obter_voz(voice_id: str, db: DbSession) -> Voice:
    voice = await db.get(Voice, voice_id)
    if voice is None or not voice.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voz não encontrada")
    return voice
