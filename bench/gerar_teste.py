"""
Gera bench/teste_cego/dados.js a partir dos áudios degradados.

Para cada par (motor_ref, motor_candidato) × frase, cria itens de:
  - ABX: A = ref, B = candidato, X = um dos dois (aleatorizado por seed)
  - MOS: áudio individual de cada motor
  - Preferência: A = ref, B = candidato (lado aleatorizado)

Uso:
  uv run python -m bench.gerar_teste --motor-ref elevenlabs --condicao tel
  uv run python -m bench.gerar_teste --motor-ref elevenlabs --condicao tel --seed 42
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import yaml

_DADOS_JS = ROOT / "bench" / "teste_cego" / "dados.js"
_FRASES_YAML = ROOT / "bench" / "frases.yaml"
_OUTPUTS = ROOT / "bench" / "outputs"


def _carregar_frases(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8") as f:
        return yaml.safe_load(f)["frases"]


def _rel(caminho: Path) -> str:
    """Caminho relativo a partir de bench/teste_cego/."""
    return "../" + str(caminho.relative_to(ROOT / "bench")).replace("\\", "/")


def gerar_manifesto(
    motor_ref: str,
    condicao: str,
    seed: int,
    saida: Path,
    outputs: Path,
    frases_yaml: Path,
) -> None:
    rng = random.Random(seed)
    frases = _carregar_frases(frases_yaml)

    dir_ref = outputs / f"{motor_ref}_{condicao}"
    candidatos = sorted(
        d.name.replace(f"_{condicao}", "")
        for d in outputs.iterdir()
        if d.is_dir() and d.name.endswith(f"_{condicao}") and not d.name.startswith(motor_ref)
    )

    if not candidatos:
        print(f"Nenhum candidato encontrado em {outputs} para condição '{condicao}'.")
        return

    testes_abx: list[dict[str, object]] = []
    testes_mos: list[dict[str, object]] = []
    testes_pref: list[dict[str, object]] = []

    for candidato in candidatos:
        dir_cand = outputs / f"{candidato}_{condicao}"
        for frase in frases:
            fid = frase["id"]
            wav_ref = dir_ref / f"{fid}.wav"
            wav_cand = dir_cand / f"{fid}.wav"
            if not wav_ref.exists() or not wav_cand.exists():
                continue

            # ABX
            x_eh_ref = rng.random() < 0.5
            testes_abx.append(
                {
                    "id": f"abx_{candidato}_{fid}",
                    "frase_id": fid,
                    "texto": str(frase["texto"]).strip(),
                    "categoria": frase.get("categoria", ""),
                    "motor_ref": motor_ref,
                    "motor_candidato": candidato,
                    "audio_a": _rel(wav_ref),
                    "audio_b": _rel(wav_cand),
                    "audio_x": _rel(wav_ref if x_eh_ref else wav_cand),
                    "x_eh_ref": x_eh_ref,
                }
            )

            # MOS ref (uma vez por frase, não por candidato)
            if candidato == candidatos[0]:
                testes_mos.append(
                    {
                        "id": f"mos_{motor_ref}_{fid}",
                        "frase_id": fid,
                        "texto": str(frase["texto"]).strip(),
                        "motor": motor_ref,
                        "audio": _rel(wav_ref),
                    }
                )

            # MOS candidato
            testes_mos.append(
                {
                    "id": f"mos_{candidato}_{fid}",
                    "frase_id": fid,
                    "texto": str(frase["texto"]).strip(),
                    "motor": candidato,
                    "audio": _rel(wav_cand),
                }
            )

            # Preferência (lados aleatorizados)
            a_eh_ref = rng.random() < 0.5
            testes_pref.append(
                {
                    "id": f"pref_{candidato}_{fid}",
                    "frase_id": fid,
                    "texto": str(frase["texto"]).strip(),
                    "motor_ref": motor_ref,
                    "motor_candidato": candidato,
                    "audio_a": _rel(wav_ref if a_eh_ref else wav_cand),
                    "audio_b": _rel(wav_cand if a_eh_ref else wav_ref),
                    "a_eh_ref": a_eh_ref,
                }
            )

    rng.shuffle(testes_abx)
    rng.shuffle(testes_mos)
    rng.shuffle(testes_pref)

    manifesto = {
        "motor_ref": motor_ref,
        "candidatos": candidatos,
        "condicao": condicao,
        "seed": seed,
        "testes_abx": testes_abx,
        "testes_mos": testes_mos,
        "testes_pref": testes_pref,
    }

    saida.parent.mkdir(parents=True, exist_ok=True)
    js = "// Gerado por bench/gerar_teste.py — não editar manualmente.\n"
    js += "const MANIFEST = " + json.dumps(manifesto, ensure_ascii=False, indent=2) + ";\n"
    saida.write_text(js, encoding="utf-8")

    print(f"Gerado: {saida}")
    print(f"  ABX       : {len(testes_abx)} itens")
    print(f"  MOS       : {len(testes_mos)} itens")
    print(f"  Preferência: {len(testes_pref)} itens")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--motor-ref", default="elevenlabs", help="Motor de referência")
    p.add_argument("--condicao", default="tel", choices=["tel", "opus"])
    p.add_argument("--seed", type=int, default=42, help="Seed para aleatorização do X e lados")
    p.add_argument("--saida", default=_DADOS_JS, type=Path)
    p.add_argument("--outputs", default=_OUTPUTS, type=Path)
    p.add_argument("--frases", default=_FRASES_YAML, type=Path)
    args = p.parse_args()

    gerar_manifesto(
        motor_ref=args.motor_ref,
        condicao=args.condicao,
        seed=args.seed,
        saida=args.saida,
        outputs=args.outputs,
        frases_yaml=args.frases,
    )


if __name__ == "__main__":
    main()
