from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from kvoice.api.deps import AuthDep, DbSession, _exigir_scope
from kvoice.api.schemas import VoiceResponse
from kvoice.db.models import Voice

router = APIRouter(prefix="/v1/voices", tags=["voices"])
_leitura = Depends(_exigir_scope("voices:read"))


@router.get("", response_model=list[VoiceResponse], dependencies=[_leitura])
async def listar_vozes(db: DbSession, auth: AuthDep) -> list[Voice]:
    client, token = auth
    result = await db.execute(
        select(Voice)
        .where(
            Voice.is_active.is_(True),
            Voice.filtro_visivel(client.id, token.has_scope("admin")),
        )
        .order_by(Voice.name)
    )
    return list(result.scalars().all())


@router.get("/{voice_id}", response_model=VoiceResponse, dependencies=[_leitura])
async def obter_voz(voice_id: str, db: DbSession, auth: AuthDep) -> Voice:
    client, token = auth
    voice = await db.get(Voice, voice_id)
    # Voz de outro cliente responde 404, como se não existisse.
    if voice is None or not voice.visivel_para(client.id, token.has_scope("admin")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voz não encontrada")
    return voice
