from __future__ import annotations

from kvoice.engine.types import TTSEngine

_engine: TTSEngine | None = None
_ADMISSION_MAX_QUEUE = 8


def set_engine(engine: TTSEngine) -> None:
    global _engine
    _engine = engine


def clear_engine() -> None:
    global _engine
    _engine = None


def get_engine() -> TTSEngine | None:
    return _engine


def can_admit() -> bool:
    """True se um novo stream pode iniciar sem exceder o orçamento de fila."""
    if _engine is None:
        return False
    return _engine.capacity().queued < _ADMISSION_MAX_QUEUE
