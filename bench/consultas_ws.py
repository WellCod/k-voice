"""Custo das consultas ao banco antes do primeiro áudio no WebSocket.

Cada fala no WebSocket faz, em sequência, antes do "started": autenticação do token,
busca da voz, regra de roteamento do cliente e dicionário de pronúncia. Este bench
mede cada uma e a soma, no banco de DATABASE_URL, para decidir se um cache em memória
vale a pena antes de escrever o cache.

Cria um cliente, um token, uma voz e uma entrada de dicionário temporários e apaga
tudo no fim.

Uso:
  uv run python -m bench.consultas_ws --n 300
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import delete

from kvoice.api.auth import gerar_token, hash_token
from kvoice.api.deps import autenticar_token
from kvoice.api.routers.tts import _buscar_voz
from kvoice.api.routing import _buscar_regra
from kvoice.db.models import ApiToken, Client, PronunciationEntry, Voice, VoiceOrigin
from kvoice.db.session import init_db, session_factory
from kvoice.normalize import load_dict
from kvoice.settings import get_settings

_SAIDA = Path(__file__).parent / "outputs" / "consultas_ws"


def _percentil(valores: list[float], p: float) -> float:
    ordenados = sorted(valores)
    k = max(0, min(len(ordenados) - 1, round(p / 100 * (len(ordenados) - 1))))
    return ordenados[k]


def _resumo(ms: list[float]) -> dict[str, float]:
    return {
        "p50": round(statistics.median(ms), 2),
        "p95": round(_percentil(ms, 95), 2),
        "p99": round(_percentil(ms, 99), 2),
        "max": round(max(ms), 2),
    }


async def _medir(n: int, fn: Callable[[], Awaitable[Any]]) -> list[float]:
    for _ in range(5):  # aquece conexão e cache de statement
        await fn()
    tempos: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        await fn()
        tempos.append((time.perf_counter() - t0) * 1000)
    return tempos


def _init_sem_pre_ping(url: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from kvoice.db import session

    session._factory = async_sessionmaker(create_async_engine(url), expire_on_commit=False)


async def _rodar(n: int, pre_ping: bool) -> dict[str, Any]:
    url = get_settings().database_url
    if pre_ping:
        init_db(url)  # igual ao servidor
    else:
        _init_sem_pre_ping(url)
    sufixo = uuid.uuid4().hex[:8]
    raw = gerar_token()
    voz_id = f"bench-consultas-{sufixo}"
    async with session_factory()() as db:
        cliente = Client(name=f"bench consultas {sufixo}")
        db.add(cliente)
        await db.flush()
        db.add(
            ApiToken(
                client_id=cliente.id,
                name="bench",
                token_hash=hash_token(raw),
                scopes="tts:stream",
            )
        )
        db.add(Voice(id=voz_id, name="Bench", origin=VoiceOrigin.preset))
        db.add(PronunciationEntry(client_id=cliente.id, term="Klubi", expansion="clúbi"))
        await db.commit()
        cliente_id = cliente.id

    try:

        async def _sequencia() -> None:
            await autenticar_token(raw)
            await _buscar_voz(voz_id)
            await _buscar_regra(cliente_id)
            await load_dict(cliente_id)

        async def _sequencia_paralela() -> None:
            # A voz, a regra e o dicionário só dependem do cliente: podem ir juntos.
            await autenticar_token(raw)
            await asyncio.gather(
                _buscar_voz(voz_id), _buscar_regra(cliente_id), load_dict(cliente_id)
            )

        etapas: dict[str, Callable[[], Awaitable[Any]]] = {
            "autenticar_token": lambda: autenticar_token(raw),
            "buscar_voz": lambda: _buscar_voz(voz_id),
            "buscar_regra": lambda: _buscar_regra(cliente_id),
            "load_dict": lambda: load_dict(cliente_id),
            "sequencia_completa": _sequencia,
            "sequencia_paralela": _sequencia_paralela,
        }
        resultado = {nome: _resumo(await _medir(n, fn)) for nome, fn in etapas.items()}
    finally:
        async with session_factory()() as db:
            await db.execute(
                delete(PronunciationEntry).where(PronunciationEntry.client_id == cliente_id)
            )
            await db.execute(delete(ApiToken).where(ApiToken.client_id == cliente_id))
            await db.execute(delete(Voice).where(Voice.id == voz_id))
            await db.execute(delete(Client).where(Client.id == cliente_id))
            await db.commit()

    return {
        "n": n,
        "data": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "maquina": f"{platform.processor() or platform.machine()} · {platform.system()}",
        "banco": url.split("@")[-1].split("?")[0],
        "pool_pre_ping": pre_ping,
        "ms": resultado,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=300)
    p.add_argument(
        "--sem-pre-ping",
        action="store_true",
        help="engine sem pool_pre_ping (o servidor usa pre_ping)",
    )
    args = p.parse_args()
    resultado = asyncio.run(_rodar(args.n, pre_ping=not args.sem_pre_ping))
    ping = "com" if resultado["pool_pre_ping"] else "sem"
    cabecalho = f"{'etapa':22} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}"
    print(f"{cabecalho}  (ms, n={args.n}, {ping} pre_ping)")
    for nome, r in resultado["ms"].items():
        print(f"{nome:22} {r['p50']:8.2f} {r['p95']:8.2f} {r['p99']:8.2f} {r['max']:8.2f}")
    _SAIDA.mkdir(parents=True, exist_ok=True)
    arquivo = _SAIDA / f"resultado-{time.strftime('%Y%m%d-%H%M%S')}.json"
    arquivo.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nresultado: {arquivo}")


if __name__ == "__main__":
    main()
