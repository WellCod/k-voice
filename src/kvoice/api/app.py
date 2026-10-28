from __future__ import annotations

import asyncio
import pathlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from kvoice.api.routers import admin, tts, voices
from kvoice.compat.elevenlabs import router as elevenlabs_compat
from kvoice.db.session import init_db
from kvoice.engine.registry import get_engine, set_engine
from kvoice.mcp.server import mcp
from kvoice.settings import get_settings

_STATIC = pathlib.Path(__file__).parent.parent / "static" / "demo"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    import logging

    log = logging.getLogger("kvoice.startup")
    settings = get_settings()
    init_db(settings.database_url)

    if get_engine() is None:
        if settings.qwen3_enabled:
            log.info("Carregando Qwen3-TTS (%s)…", settings.qwen3_model_id)
            try:
                from kvoice.engine.qwen3_tts import Qwen3TTSEngine

                engine = await asyncio.to_thread(
                    Qwen3TTSEngine.load,
                    settings.qwen3_model_id,
                    settings.qwen3_base_model_id,
                    settings.qwen3_speaker,
                )
                set_engine(engine)
                log.info("Qwen3-TTS carregado (speaker=%s)", settings.qwen3_speaker)
            except Exception:
                log.exception("Falha ao carregar Qwen3-TTS; usando engine stub")
                from kvoice.engine.stub import StubEngine

                set_engine(StubEngine())
        else:
            from kvoice.engine.stub import StubEngine

            set_engine(StubEngine())

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
    async def health() -> dict[str, object]:
        from kvoice.engine.registry import get_engine

        engine = get_engine()
        if engine is None:
            return {"status": "ok", "engine": None, "active": 0, "queued": 0, "rtf": None}
        cap = engine.capacity()
        return {
            "status": "ok",
            "engine": engine.name,
            "active": cap.active_streams,
            "queued": cap.queued,
            "rtf": cap.rtf_recent,
        }

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
