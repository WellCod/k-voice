from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kvoice.api.auth import hash_token
from kvoice.cache_consultas import em_cache
from kvoice.db.models import ApiToken, Client, UsageEvent
from kvoice.db.session import get_session, session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
_log = logging.getLogger(__name__)


def _consulta_token(raw: str) -> Select[ApiToken]:
    return _consulta_token_por_hash(hash_token(raw))


def _consulta_token_por_hash(token_hash: str) -> Select[ApiToken]:
    return (
        select(ApiToken)
        .join(Client, ApiToken.client_id == Client.id)
        .where(
            ApiToken.token_hash == token_hash,
            ApiToken.is_active.is_(True),
            Client.is_active.is_(True),
        )
        .options(selectinload(ApiToken.client))
    )


async def autenticar_token(raw: str) -> tuple[Client, ApiToken] | None:
    """Valida o token fora de uma dependência do FastAPI (WebSocket, compat, MCP)."""
    # A chave do cache é o hash: o token em texto não fica guardado na memória.
    return await _autenticar_por_hash(hash_token(raw))


@em_cache
async def _autenticar_por_hash(token_hash: str) -> tuple[Client, ApiToken] | None:
    async with session_factory()() as db:
        record = (await db.execute(_consulta_token_por_hash(token_hash))).scalar_one_or_none()
    if record is None:
        return None
    return record.client, record


async def _autenticar(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> tuple[Client, ApiToken]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token ausente")
    raw = authorization.removeprefix("Bearer ")
    record = (await db.execute(_consulta_token(raw))).scalar_one_or_none()
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


async def gravar_uso(
    *,
    request_id: uuid.UUID,
    client_id: uuid.UUID,
    voice_id: str,
    engine_name: str,
    characters: int,
    audio_ms: float,
    ttfa_ms: float,
    total_ms: float,
    fallback: bool = False,
    fallback_reason: str | None = None,
) -> None:
    """Grava a medição numa sessão própria; falha vira log, nunca erro para o cliente."""
    try:
        async with session_factory()() as db:
            await registrar_uso(
                db,
                request_id=request_id,
                client_id=client_id,
                voice_id=voice_id,
                model=engine_name,
                characters=characters,
                audio_ms=audio_ms,
                ttfa_ms=ttfa_ms,
                total_ms=total_ms,
                engine=engine_name,
                fallback=fallback,
                fallback_reason=fallback_reason,
            )
    except Exception:
        _log.exception("falha ao gravar uso (request_id=%s)", request_id)


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
