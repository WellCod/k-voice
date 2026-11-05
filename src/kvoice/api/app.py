from __future__ import annotations

import asyncio
import logging
import pathlib
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from kvoice.api.routers import admin, tts, voices
from kvoice.compat.elevenlabs import router as elevenlabs_compat
from kvoice.db.session import init_db
from kvoice.engine.registry import get_engine, set_engine
from kvoice.engine.types import TTSEngine
from kvoice.mcp.server import mcp
from kvoice.settings import get_settings

_STATIC = pathlib.Path(__file__).parent.parent / "static" / "demo"
_RE_TOKEN_QUERY = re.compile(r"(token=)[^&\s\"']+")


def _ocultar(valor: object) -> object:
    return _RE_TOKEN_QUERY.sub(r"\g<1>***", valor) if isinstance(valor, str) else valor


class _OcultaToken(logging.Filter):
    """O WebSocket recebe o token na query string, que o uvicorn registra no log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_ocultar(a) for a in record.args)
        if isinstance(record.msg, str):
            record.msg = _RE_TOKEN_QUERY.sub(r"\g<1>***", record.msg)
        return True


def _instalar_filtro_token() -> None:
    for nome in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(nome)
        if not any(isinstance(f, _OcultaToken) for f in logger.filters):
            logger.addFilter(_OcultaToken())


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log = logging.getLogger("kvoice.startup")
    settings = get_settings()
    init_db(settings.database_url)

    if get_engine() is None:
        if settings.qwen3_enabled:
            log.info("Carregando Qwen3-TTS (%s)…", settings.qwen3_model_id)
            try:
                engine: TTSEngine
                if settings.qwen3_device.startswith("cuda"):
                    # GPU: streaming real dentro da frase (faster-qwen3-tts, CUDA graphs)
                    from kvoice.engine.faster_qwen3 import FasterQwen3Engine

                    engine = await asyncio.to_thread(
                        FasterQwen3Engine.load,
                        settings.qwen3_model_id,
                        settings.qwen3_base_model_id,
                        settings.qwen3_speaker,
                        settings.qwen3_device,
                        settings.qwen3_dtype,
                        settings.qwen3_chunk_size,
                    )
                else:
                    # CPU (dev): síntese frase a frase
                    from kvoice.engine.qwen3_tts import Qwen3TTSEngine

                    engine = await asyncio.to_thread(
                        Qwen3TTSEngine.load,
                        settings.qwen3_model_id,
                        settings.qwen3_base_model_id,
                        settings.qwen3_speaker,
                        settings.qwen3_device,
                        settings.qwen3_dtype,
                    )
                set_engine(engine)
                log.info(
                    "Qwen3-TTS carregado (%s, speaker=%s, device=%s)",
                    type(engine).__name__,
                    settings.qwen3_speaker,
                    settings.qwen3_device,
                )
            except Exception:
                log.exception("Falha ao carregar Qwen3-TTS; usando engine stub")
                from kvoice.engine.stub import StubEngine

                set_engine(StubEngine())
        else:
            from kvoice.engine.stub import StubEngine

            set_engine(StubEngine())

    yield


def create_app() -> FastAPI:
    _instalar_filtro_token()
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
