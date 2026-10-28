#!/usr/bin/env python3
"""
Benchmark de síntese offline: gera áudio de cada frase em cada motor.

Uso:
    uv run python -m bench.sintetizar --motores qwen,elevenlabs
    uv run python -m bench.sintetizar --motores todos --ref-audio bench/referencias/voz.wav

Saída:
    bench/outputs/<motor>/<frase_id>.wav   — áudio em 24 kHz PCM 16-bit
    bench/outputs/meta.jsonl               — uma linha por síntese, JSON
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import soundfile as sf
import yaml
from tqdm import tqdm

from bench.motores import MOTORES_DISPONIVEIS, ResultadoSintese, carregar_motor


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--motores",
        default="todos",
        help="Motores separados por vírgula (qwen, kokoro, chatterbox, elevenlabs) ou 'todos'",
    )
    p.add_argument(
        "--saida",
        default=ROOT / "bench" / "outputs",
        type=Path,
        metavar="DIR",
        help="Diretório de saída (default: bench/outputs)",
    )
    p.add_argument(
        "--frases",
        default=ROOT / "bench" / "frases.yaml",
        type=Path,
        metavar="YAML",
        help="Frases de benchmark (default: bench/frases.yaml)",
    )
    p.add_argument(
        "--ref-audio",
        default=None,
        type=Path,
        metavar="WAV",
        help="Áudio de referência para clonagem de voz (~10 s, com consentimento registrado)",
    )
    p.add_argument(
        "--ref-texto",
        default=None,
        metavar="TEXTO",
        help="Transcrição exata do áudio de referência",
    )
    p.add_argument(
        "--voz-elevenlabs",
        default="21m00Tcm4TlvDq8ikWAM",
        metavar="ID",
        help="voice_id da ElevenLabs usado como referência",
    )
    p.add_argument(
        "--modelo-elevenlabs",
        default="eleven_flash_v2_5",
        metavar="ID",
        help="Modelo da ElevenLabs (default: eleven_flash_v2_5)",
    )
    return p.parse_args()


def _carregar_frases(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8") as f:
        dados = yaml.safe_load(f)
    frases: list[dict[str, str]] = dados["frases"]
    return frases


def _salvar_wav(audio: np.ndarray, taxa: int, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(caminho), audio, taxa, subtype="PCM_16")


def _kwargs_motor(nome: str, args: argparse.Namespace) -> dict[str, object]:
    ref_audio = str(args.ref_audio) if args.ref_audio else None
    return {
        "qwen": {"ref_audio": ref_audio, "ref_texto": args.ref_texto},
        "kokoro": {},
        "chatterbox": {"ref_audio": ref_audio},
        "elevenlabs": {
            "voice_id": args.voz_elevenlabs,
            "model_id": args.modelo_elevenlabs,
        },
    }.get(nome, {})


def main() -> None:
    args = _parse_args()

    nomes = MOTORES_DISPONIVEIS if args.motores == "todos" else args.motores.split(",")
    frases = _carregar_frases(args.frases)

    args.saida.mkdir(parents=True, exist_ok=True)
    meta_path = args.saida / "meta.jsonl"

    print(f"Frases : {len(frases)}")
    print(f"Motores: {nomes}")
    print(f"Saída  : {args.saida}")
    print()

    with meta_path.open("a", encoding="utf-8") as meta_f:
        for nome in nomes:
            print(f"=== {nome} ===")
            try:
                motor = carregar_motor(nome, **_kwargs_motor(nome, args))
                motor.carregar()  # type: ignore[union-attr]
            except ImportError as e:
                print(f"  [PULADO] dependência não instalada: {e}\n")
                continue
            except Exception as e:
                print(f"  [ERRO ao carregar] {e}\n")
                continue

            erros = 0
            for frase in tqdm(frases, desc=nome, unit="frase"):
                frase_id = frase["id"]
                texto = str(frase["texto"]).strip()
                wav_path = args.saida / nome / f"{frase_id}.wav"

                try:
                    r: ResultadoSintese = motor.sintetizar(texto, frase_id)  # type: ignore[union-attr]
                    _salvar_wav(r.audio, r.taxa_amostragem, wav_path)
                    linha = {
                        "motor": r.motor,
                        "frase_id": r.frase_id,
                        "categoria": frase.get("categoria", ""),
                        "chars": len(texto),
                        "duracao_sintese_ms": round(r.duracao_sintese_ms, 1),
                        "duracao_audio_ms": round(r.duracao_audio_ms, 1),
                        "rtf": round(r.rtf, 4),
                        "taxa_amostragem": r.taxa_amostragem,
                        "wav": str(wav_path),
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                    meta_f.write(json.dumps(linha, ensure_ascii=False) + "\n")
                    meta_f.flush()
                except Exception as e:
                    erros += 1
                    tqdm.write(f"  [ERRO] {frase_id}: {e}")

            motor.descarregar()  # type: ignore[union-attr]
            print(f"  Concluído. Erros: {erros}/{len(frases)}\n")

    print(f"Metadados em: {meta_path}")


if __name__ == "__main__":
    main()
