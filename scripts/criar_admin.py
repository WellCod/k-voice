"""Cria o primeiro cliente com token de admin e uma voz preset num banco vazio.

Os endpoints /admin exigem um token de admin; este script resolve o primeiro.
Grava direto no banco de DATABASE_URL (rode `alembic upgrade head` antes).
O token aparece uma vez na saída e só o hash fica no banco.

Uso:
    uv run python scripts/criar_admin.py
    uv run python scripts/criar_admin.py --cliente "Bench GPU" --voz v_vivian --speaker vivian
"""

from __future__ import annotations

import argparse
import asyncio

from kvoice.api.auth import gerar_token, hash_token
from kvoice.db.models import ApiToken, Client, Voice, VoiceOrigin
from kvoice.db.session import init_db, session_factory
from kvoice.settings import get_settings


async def _criar(database_url: str, cliente: str, voz_id: str, speaker: str) -> str:
    init_db(database_url)
    async with session_factory()() as db:
        client = Client(name=cliente)
        db.add(client)
        await db.flush()
        raw = gerar_token()
        db.add(
            ApiToken(
                client_id=client.id,
                name="admin",
                token_hash=hash_token(raw),
                scopes="admin",
            )
        )
        if await db.get(Voice, voz_id) is None:
            db.add(
                Voice(
                    id=voz_id,
                    name=speaker.capitalize(),
                    language="pt-BR",
                    origin=VoiceOrigin.preset,
                    model_id=speaker,
                )
            )
        await db.commit()
    return raw


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cliente", default="admin")
    p.add_argument("--voz", default="v_vivian", help="id da voz preset criada se não existir")
    p.add_argument("--speaker", default="vivian", help="speaker do Qwen3 CustomVoice")
    args = p.parse_args()
    url = get_settings().database_url
    token = asyncio.run(_criar(url, args.cliente, args.voz, args.speaker))
    print(f"token de admin (guarde agora, não é exibido de novo):\n{token}")
    print(f"voz: {args.voz}")


if __name__ == "__main__":
    main()
