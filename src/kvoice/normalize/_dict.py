"""Carregamento e aplicação de dicionário de pronúncia do banco de dados.

Entradas globais (client_id=None) valem para todos os clientes.
Entradas por cliente sobrepõem globais para o mesmo termo literal.
Entradas de regex são aplicadas em sequência, após os literais.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import or_, select

from kvoice.db.models import PronunciationEntry
from kvoice.db.session import session_factory

PronEntry = tuple[str, str, bool]  # (term, expansion, is_regex)

_log = logging.getLogger(__name__)


async def load_dict(client_id: uuid.UUID) -> list[PronEntry]:
    """Carrega entradas globais + do cliente, com deduplicação para literais."""
    async with session_factory()() as db:
        result = await db.execute(
            select(PronunciationEntry)
            .where(
                or_(
                    PronunciationEntry.client_id == client_id,
                    PronunciationEntry.client_id.is_(None),
                )
            )
            .order_by(PronunciationEntry.client_id.nulls_first())
        )
        entries = list(result.scalars().all())

    plain: dict[str, str] = {}
    regex: list[PronEntry] = []
    for e in entries:
        if e.is_regex:
            regex.append((e.term, e.expansion, True))
        else:
            plain[e.term] = e.expansion  # cliente sobrepõe global

    return [(t, exp, False) for t, exp in plain.items()] + regex


def apply_dict(text: str, entries: list[PronEntry]) -> str:
    """Aplica literais primeiro, depois regex, na ordem da lista."""
    for term, expansion, is_regex in entries:
        if not is_regex:
            text = text.replace(term, expansion)
            continue
        try:
            text = re.sub(term, expansion, text)
        except (re.error, IndexError):
            # Entrada antiga gravada antes da validação: pula ela, não derruba a fala.
            _log.warning("regex do dicionário ignorada: %r", term)
    return text
