"""Testes de integração com Postgres via testcontainers."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio

testcontainers = pytest.importorskip("testcontainers")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from testcontainers.community.postgres import PostgresContainer  # noqa: E402

from kvoice.api.auth import gerar_token, hash_token  # noqa: E402
from kvoice.db.models import ApiToken, Base, Client, Voice, VoiceOrigin  # noqa: E402

_PG_IMAGE = "postgres:16-alpine"

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(scope="module")
def pg() -> Any:
    with PostgresContainer(_PG_IMAGE) as c:
        yield c


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def engine(pg: Any) -> Any:
    url = (
        pg.get_connection_url()
        .replace("psycopg2", "asyncpg")
        .replace("postgresql://", "postgresql+asyncpg://")
    )
    eng = create_async_engine(url)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture(loop_scope="module")
async def db(engine: Any) -> Any:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


async def test_criar_client(db: AsyncSession) -> None:
    client = Client(name="Empresa Teste")
    db.add(client)
    await db.commit()
    await db.refresh(client)
    assert isinstance(client.id, uuid.UUID)
    assert client.name == "Empresa Teste"
    assert client.is_active is True


async def test_criar_token_e_verificar_hash(db: AsyncSession) -> None:
    client = Client(name="Cliente Token")
    db.add(client)
    await db.flush()

    raw = gerar_token()
    token = ApiToken(
        client_id=client.id,
        name="token-teste",
        token_hash=hash_token(raw),
        scopes="tts:stream,voices:read",
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    assert token.has_scope("tts:stream")
    assert token.has_scope("voices:read")
    assert not token.has_scope("admin")
    assert token.scopes_list == ["tts:stream", "voices:read"]


async def test_admin_scope_acessa_tudo(db: AsyncSession) -> None:
    client = Client(name="Admin Cliente")
    db.add(client)
    await db.flush()
    token = ApiToken(
        client_id=client.id,
        name="admin-token",
        token_hash=hash_token(gerar_token()),
        scopes="admin",
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    assert token.has_scope("tts:stream")
    assert token.has_scope("voices:write")
    assert token.has_scope("admin")


async def test_criar_voice(db: AsyncSession) -> None:
    voice = Voice(
        id="v_ana",
        name="Ana",
        language="pt-BR",
        origin=VoiceOrigin.preset,
        model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    )
    db.add(voice)
    await db.commit()
    await db.refresh(voice)

    assert voice.id == "v_ana"
    assert voice.origin == VoiceOrigin.preset
    assert voice.is_active is True


async def test_ping_db(db: AsyncSession) -> None:
    result = await db.execute(text("SELECT 1"))
    assert result.scalar() == 1
