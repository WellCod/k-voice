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


async def test_autenticacao_compat_e_mcp_carrega_cliente(engine: Any, db: AsyncSession) -> None:
    from kvoice.compat.elevenlabs import _autenticar as autenticar_compat
    from kvoice.db.session import init_db
    from kvoice.mcp.server import _validar_token

    client = Client(name="Cliente Compat")
    db.add(client)
    await db.flush()
    raw = gerar_token()
    db.add(
        ApiToken(
            client_id=client.id,
            name="compat",
            token_hash=hash_token(raw),
            scopes="tts:batch",
        )
    )
    await db.commit()

    init_db(engine.url.render_as_string(hide_password=False))

    c, t = await autenticar_compat(raw, None)
    assert c.id == client.id
    assert t.has_scope("tts:batch")

    resultado = await _validar_token(raw)
    assert resultado is not None
    assert resultado[0].id == client.id


async def test_criar_admin_gera_token_que_autentica(engine: Any) -> None:
    import importlib.util
    import pathlib

    from kvoice.api.deps import autenticar_token

    caminho = pathlib.Path(__file__).parents[2] / "scripts" / "criar_admin.py"
    spec = importlib.util.spec_from_file_location("criar_admin", caminho)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    url = engine.url.render_as_string(hide_password=False)
    raw = await mod._criar(url, "Admin Bench", "v_bench", "serena")
    raw2 = await mod._criar(url, "Admin Bench 2", "v_bench", "serena")  # voz já existe

    for token in (raw, raw2):
        auth = await autenticar_token(token)
        assert auth is not None
        assert auth[1].has_scope("tts:stream")

    from kvoice.db.session import session_factory

    async with session_factory()() as db:
        voz = await db.get(Voice, "v_bench")
    assert voz is not None
    assert voz.model_id == "serena"
    assert voz.origin == VoiceOrigin.preset


async def test_listagem_de_vozes_so_traz_catalogo_e_as_do_cliente(db: AsyncSession) -> None:
    from sqlalchemy import select

    a, b = Client(name="A"), Client(name="B")
    db.add_all([a, b])
    await db.flush()
    db.add_all(
        [
            Voice(id="v_global", name="Global", origin=VoiceOrigin.preset),
            Voice(id="v_de_a", name="De A", origin=VoiceOrigin.clone, client_id=a.id),
            Voice(id="v_de_b", name="De B", origin=VoiceOrigin.clone, client_id=b.id),
        ]
    )
    await db.commit()

    async def ids(client_id: uuid.UUID, admin: bool = False) -> set[str]:
        # O banco é compartilhado entre os testes: olha só as vozes criadas aqui.
        res = await db.execute(
            select(Voice.id).where(
                Voice.id.in_(["v_global", "v_de_a", "v_de_b"]),
                Voice.filtro_visivel(client_id, admin),
            )
        )
        return set(res.scalars().all())

    assert await ids(a.id) == {"v_global", "v_de_a"}
    assert await ids(b.id) == {"v_global", "v_de_b"}
    assert await ids(a.id, admin=True) == {"v_global", "v_de_a", "v_de_b"}


async def test_patch_troca_e_remove_o_dono_da_voz(db: AsyncSession) -> None:
    from fastapi import HTTPException

    from kvoice.api.routers.admin import atualizar_voz
    from kvoice.api.schemas import VoicePatch

    cliente = Client(name="Dono")
    db.add(cliente)
    await db.flush()
    db.add(Voice(id="v_dono_patch", name="Patch", origin=VoiceOrigin.clone))
    await db.commit()

    voz = await atualizar_voz(
        "v_dono_patch", VoicePatch.model_validate({"client_id": str(cliente.id)}), db
    )
    assert voz.client_id == cliente.id
    voz = await atualizar_voz("v_dono_patch", VoicePatch(style_prompt="x"), db)
    assert voz.client_id == cliente.id
    voz = await atualizar_voz("v_dono_patch", VoicePatch.model_validate({"client_id": None}), db)
    assert voz.client_id is None
    with pytest.raises(HTTPException) as erro:
        await atualizar_voz(
            "v_dono_patch", VoicePatch.model_validate({"client_id": str(uuid.uuid4())}), db
        )
    assert erro.value.status_code == 404
