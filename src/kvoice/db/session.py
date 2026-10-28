from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(database_url: str) -> None:
    global _factory
    engine = create_async_engine(database_url, pool_pre_ping=True)
    _factory = async_sessionmaker(engine, expire_on_commit=False)


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _factory is None:
        raise RuntimeError("Banco não inicializado. Chame init_db() no startup da aplicação.")
    return _factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with session_factory()() as session:
        yield session
