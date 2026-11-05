"""Cifra os áudios de referência gravados sem cifra antes da REFERENCE_AUDIO_KEY.

Percorre data/references e reescreve cifrado todo WAV em claro. Idempotente:
arquivos já cifrados são pulados. Rodar com a mesma chave que o servidor usa.

Uso:
    uv run python scripts/cifrar_referencias.py [--dir data/references]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from kvoice.referencias import cifrar, exigir_chave

_PADRAO = Path(__file__).parent.parent / "data" / "references"


def cifrar_pasta(pasta: Path) -> tuple[int, int]:
    exigir_chave()
    cifrados = pulados = 0
    for arquivo in sorted(pasta.rglob("*.wav")):
        dados = arquivo.read_bytes()
        if not dados.startswith(b"RIFF"):
            pulados += 1
            continue
        arquivo.write_bytes(cifrar(dados))
        cifrados += 1
    return cifrados, pulados


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dir", default=_PADRAO, type=Path)
    args = p.parse_args()
    cifrados, pulados = cifrar_pasta(args.dir)
    print(f"cifrados: {cifrados}, já cifrados: {pulados}")


if __name__ == "__main__":
    main()
