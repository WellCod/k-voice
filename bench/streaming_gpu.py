"""
Streaming real (faster-qwen3-tts) contra frase inteira no mesmo modelo e na mesma GPU.

Mede, por frase de bench/frases.yaml (normalizada como no servidor):
  - ttfa_ms: do pedido até o primeiro áudio. É o atraso que a pessoa ouve.
  - total_ms e audio_ms; rtf = total_ms / audio_ms (< 1 é mais rápido que tempo real).

Configurações:
  - streaming_cN: FasterQwen3Engine com chunk_size=N (um item por valor de --chunk-sizes)
  - frase_inteira: Qwen3TTSEngine no mesmo device, que devolve a frase toda de uma vez

Mede o motor direto, sem servidor, uma frase por vez. Concorrência e caminho completo
pelo WebSocket ficam com bench/carga_ws.py. Resultado em
bench/outputs/streaming_gpu_{ts}.jsonl com GPU, versões e data.

Uso (máquina com GPU NVIDIA):
  uv run --group bench python -m bench.streaming_gpu
  uv run --group bench python -m bench.streaming_gpu --chunk-sizes 4,8,12 --repeticoes 3
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import yaml

from kvoice.engine.types import SynthOptions, TTSEngine, Voice
from kvoice.normalize import normalize

_FRASES_YAML = ROOT / "bench" / "frases.yaml"
_SAIDA = ROOT / "bench" / "outputs"


@dataclass
class Medicao:
    config: str
    frase_id: str
    ttfa_ms: float
    total_ms: float
    audio_ms: float
    rtf: float
    gpu: str
    versoes: str
    ts: str


def _gpu_info() -> str:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "sem nvidia-smi"


def _versoes() -> str:
    pacotes = ["faster-qwen3-tts", "qwen-tts-hf", "torch", "transformers"]
    partes = []
    for p in pacotes:
        try:
            partes.append(f"{p}=={importlib.metadata.version(p)}")
        except importlib.metadata.PackageNotFoundError:
            partes.append(f"{p}=?")
    return " ".join(partes)


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def _texto(frase: str) -> Any:
    yield frase


async def _medir(engine: TTSEngine, texto: str, voz: Voice) -> tuple[float, float, float]:
    t0 = time.monotonic()
    ttfa = 0.0
    audio_ms = 0.0
    async for chunk in await engine.stream(_texto(texto), voz, SynthOptions()):
        if chunk.data:
            if ttfa == 0.0:
                ttfa = (time.monotonic() - t0) * 1000
            audio_ms += chunk.duration_ms
    total = (time.monotonic() - t0) * 1000
    return ttfa, total, audio_ms


def _imprimir(medicoes: list[Medicao]) -> None:
    configs = sorted({m.config for m in medicoes})
    print(f"\n{'config':<16} {'n':>3} {'ttfa p50':>9} {'ttfa p95':>9} {'rtf p50':>8}")
    for c in configs:
        ms = [m for m in medicoes if m.config == c]
        ttfa = np.array([m.ttfa_ms for m in ms])
        rtf = np.array([m.rtf for m in ms])
        print(
            f"{c:<16} {len(ms):>3} {np.percentile(ttfa, 50):>8.0f}ms "
            f"{np.percentile(ttfa, 95):>8.0f}ms {np.percentile(rtf, 50):>8.2f}"
        )


async def _rodar(args: argparse.Namespace) -> list[Medicao]:
    import torch

    if not torch.cuda.is_available():
        raise SystemExit("torch não enxerga CUDA: confira o driver com nvidia-smi")

    from kvoice.engine.faster_qwen3 import FasterQwen3Engine, _carregar
    from kvoice.engine.qwen3_tts import Qwen3TTSEngine

    frases = yaml.safe_load(args.frases.read_text(encoding="utf-8"))["frases"]
    if args.limite:
        frases = frases[: args.limite]
    voz = Voice(id="bench", name="bench", model_id=args.speaker)
    gpu, versoes = _gpu_info(), _versoes()
    print(f"GPU: {gpu}\n{versoes}\nfrases: {len(frases)} x {args.repeticoes} repetições")

    configs: list[tuple[str, TTSEngine]] = []
    t = time.monotonic()
    modelo = _carregar(args.modelo, args.device, "auto")
    print(f"faster-qwen3-tts carregado + warmup: {time.monotonic() - t:.1f}s")
    for cs in args.chunk_sizes:
        configs.append((f"streaming_c{cs}", FasterQwen3Engine(modelo, "", chunk_size=cs)))
    if not args.sem_baseline:
        t = time.monotonic()
        configs.append(("frase_inteira", Qwen3TTSEngine.load(args.modelo, "", device=args.device)))
        print(f"qwen_tts (frase inteira) carregado: {time.monotonic() - t:.1f}s")

    medicoes: list[Medicao] = []
    for nome, engine in configs:
        await _medir(engine, "Aquecendo o motor antes de medir.", voz)
        for _ in range(args.repeticoes):
            for f in frases:
                ttfa, total, audio = await _medir(engine, normalize(str(f["texto"])), voz)
                medicoes.append(
                    Medicao(
                        config=nome,
                        frase_id=str(f["id"]),
                        ttfa_ms=round(ttfa, 1),
                        total_ms=round(total, 1),
                        audio_ms=round(audio, 1),
                        rtf=round(total / audio, 3) if audio else 0.0,
                        gpu=gpu,
                        versoes=versoes,
                        ts=_ts(),
                    )
                )
        print(f"{nome}: ok")
    return medicoes


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--modelo", default="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    p.add_argument("--speaker", default="vivian")
    p.add_argument("--device", default="cuda")
    p.add_argument(
        "--chunk-sizes",
        default=[4, 8, 12],
        type=lambda s: [int(x) for x in s.split(",")],
        help="valores de chunk_size, separados por vírgula",
    )
    p.add_argument("--repeticoes", default=3, type=int)
    p.add_argument("--limite", default=0, type=int, help="usa só as N primeiras frases")
    p.add_argument("--sem-baseline", action="store_true", help="pula a medição de frase inteira")
    p.add_argument("--frases", default=_FRASES_YAML, type=Path)
    p.add_argument("--saida", default=_SAIDA, type=Path)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    medicoes = asyncio.run(_rodar(args))
    _imprimir(medicoes)
    args.saida.mkdir(parents=True, exist_ok=True)
    caminho = args.saida / f"streaming_gpu_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    with caminho.open("w", encoding="utf-8") as fh:
        for m in medicoes:
            fh.write(json.dumps(asdict(m), ensure_ascii=False) + "\n")
    print(f"\nresultado: {caminho}")


if __name__ == "__main__":
    main()
