from __future__ import annotations

import pathlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from kvoice.api.routers import admin, tts, voices
from kvoice.compat.elevenlabs import router as elevenlabs_compat
from kvoice.db.session import init_db
from kvoice.mcp.server import mcp
from kvoice.settings import get_settings

_STATIC = pathlib.Path(__file__).parent.parent / "static" / "demo"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_db(get_settings().database_url)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="k-voice", lifespan=_lifespan)

    app.include_router(admin.router)
    app.include_router(voices.router)
    app.include_router(tts.router)
    app.include_router(elevenlabs_compat)
    app.mount("/mcp", mcp.streamable_http_app())
    if _STATIC.exists():
        app.mount("/demo", StaticFiles(directory=_STATIC, html=True), name="demo")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
