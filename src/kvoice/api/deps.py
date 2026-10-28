from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kvoice.api.auth import hash_token
from kvoice.db.models import ApiToken, Client, UsageEvent
from kvoice.db.session import get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _autenticar(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> tuple[Client, ApiToken]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token ausente")
    raw = authorization.removeprefix("Bearer ")
    token_hash = hash_token(raw)
    result = await db.execute(
        select(ApiToken)
        .join(Client, ApiToken.client_id == Client.id)
        .where(
            ApiToken.token_hash == token_hash,
            ApiToken.is_active.is_(True),
            Client.is_active.is_(True),
        )
        .options(selectinload(ApiToken.client))
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    return record.client, record


AuthDep = Annotated[tuple[Client, ApiToken], Depends(_autenticar)]


def _exigir_scope(scope: str):  # type: ignore[no-untyped-def]
    async def _check(auth: AuthDep) -> tuple[Client, ApiToken]:
        _, token = auth
        if not token.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Escopo '{scope}' necessário",
            )
        return auth

    return _check


async def registrar_uso(
    db: AsyncSession,
    *,
    request_id: uuid.UUID,
    client_id: uuid.UUID,
    voice_id: str,
    model: str,
    characters: int,
    audio_ms: float,
    ttfa_ms: float,
    total_ms: float,
    engine: str,
    fallback: bool = False,
    fallback_reason: str | None = None,
) -> None:
    db.add(
        UsageEvent(
            request_id=request_id,
            client_id=client_id,
            voice_id=voice_id,
            model=model,
            characters=characters,
            audio_ms=audio_ms,
            ttfa_ms=ttfa_ms,
            total_ms=total_ms,
            engine=engine,
            fallback=fallback,
            fallback_reason=fallback_reason,
        )
    )
    await db.commit()
