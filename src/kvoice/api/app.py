from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from kvoice.api.routers import admin, voices
from kvoice.db.session import init_db
from kvoice.settings import get_settings


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_db(get_settings().database_url)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="k-voice", lifespan=_lifespan)

    app.include_router(admin.router)
    app.include_router(voices.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
