"""
Teste de carga ponta a ponta — chamadas SIP simuladas.

Simula N chamadas VoIP simultâneas chegando via SIP → LiveKit → k-voice.
Cada chamada realiza T turnos de TTS; o texto de cada turno chega em
tokens (palavra a palavra) como saída de um LLM, com flush em fronteiras
de sentença.

Métricas validadas (docs/operacao.md):
  - TTFA p95 ≤ 350 ms
  - Falas sem fallback ≥ 99,5% (fallback ElevenLabs ≤ 0,5% em modo kvoice)
  - Cancelamento p95 ≤ 50 ms

Pré-requisitos:
  - servidor k-voice rodando com motor carregado
  - token com escopo tts:stream e voz cadastrada

Uso:
  uv run --group bench python -m bench.carga_sip \\
      --url ws://localhost:8000 --token SEU_TOKEN --voz v_ana \\
      --chamadas 10 --turnos 3 --concorrencias 4,8,16
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import websockets
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

_FRASES_YAML = ROOT / "bench" / "frases.yaml"
_SAIDA = ROOT / "bench" / "outputs"

# Gate da Fase 2 — docs/operacao.md
_GATE_TTFA_P95_MS = 350.0
_GATE_FALLBACK_MAX_PCT = 0.005  # 0,5%
_GATE_CANCEL_P95_MS = 50.0

# Delay entre palavras (ms) — simula LLM a ~40 tokens/s
_DELAY_PALAVRA_MS = 25

_KVOICE_ENGINE = "qwen3-tts"


@dataclass
class Medicao:
    tipo: str  # "turno" | "cancel"
    chamada_id: int
    turno: int
    frase_id: str
    engine: str
    ttfa_ms: float
    hardware: str
    ts: str


def _gpu_info() -> str:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "cpu"


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _percentis(valores: list[float]) -> dict[str, float]:
    a = np.array(valores)
    return {
        "p50": float(np.percentile(a, 50)),
        "p95": float(np.percentile(a, 95)),
        "p99": float(np.percentile(a, 99)),
        "max": float(a.max()),
        "n": len(valores),
    }


async def _turno(
    url: str,
    token: str,
    voice_id: str,
    frase: dict[str, str],
    chamada_id: int,
    turno_idx: int,
    hardware: str,
) -> Medicao:
    """Um turno de TTS: texto chega palavra a palavra com flush em fronteiras de sentença."""
    ws_url = f"{url}/v1/tts/stream?token={token}"
    texto = str(frase["texto"])
    frase_id = str(frase["id"])
    palavras = texto.split()

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"type": "start", "voice_id": voice_id}))

        # aguarda confirmação e extrai engine name (k-voice ou elevenlabs)
        engine = "unknown"
        while True:
            raw = await ws.recv()
            if isinstance(raw, str):
                msg = json.loads(raw)
                if msg.get("type") == "started":
                    engine = str(msg.get("engine", "unknown"))
                    break

        t0 = time.monotonic()

        # envia tokens palavra a palavra, flush em ponto/exclamação/interrogação
        for palavra in palavras:
            await ws.send(json.dumps({"type": "text", "text": palavra + " "}))
            if palavra.rstrip().endswith((".", "!", "?")):
                await ws.send(json.dumps({"type": "text", "text": "", "flush": True}))
            await asyncio.sleep(_DELAY_PALAVRA_MS / 1000)

        await ws.send(json.dumps({"type": "end"}))

        ttfa_ms = 0.0
        primeiro_audio = True
        async for raw in ws:
            if isinstance(raw, bytes) and primeiro_audio:
                ttfa_ms = (time.monotonic() - t0) * 1000
                primeiro_audio = False
            elif isinstance(raw, str):
                if json.loads(raw).get("type") in ("done", "error"):
                    break

    return Medicao(
        tipo="turno",
        chamada_id=chamada_id,
        turno=turno_idx,
        frase_id=frase_id,
        engine=engine,
        ttfa_ms=round(ttfa_ms, 2),
        hardware=hardware,
        ts=_ts(),
    )


async def _cancel_turno(
    url: str,
    token: str,
    voice_id: str,
    frase: dict[str, str],
    chamada_id: int,
    hardware: str,
) -> Medicao:
    """Mede latência de cancelamento: envia texto, aguarda 1º chunk, cancela."""
    ws_url = f"{url}/v1/tts/stream?token={token}"
    texto = str(frase["texto"])

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"type": "start", "voice_id": voice_id}))

        engine = "unknown"
        while True:
            raw = await ws.recv()
            if isinstance(raw, str) and json.loads(raw).get("type") == "started":
                engine = str(json.loads(raw).get("engine", "unknown"))
                break

        await ws.send(json.dumps({"type": "text", "text": texto, "flush": True}))

        # aguarda primeiro chunk de áudio
        async for raw in ws:
            if isinstance(raw, bytes):
                break

        t0 = time.monotonic()
        await ws.send(json.dumps({"type": "cancel"}))
        try:
            async for _ in ws:
                pass
        except Exception:
            pass
        cancel_ms = (time.monotonic() - t0) * 1000

    return Medicao(
        tipo="cancel",
        chamada_id=chamada_id,
        turno=0,
        frase_id=str(frase["id"]),
        engine=engine,
        ttfa_ms=round(cancel_ms, 2),
        hardware=hardware,
        ts=_ts(),
    )


async def _simular_chamada(
    url: str,
    token: str,
    voice_id: str,
    frases: list[dict[str, str]],
    n_turnos: int,
    hardware: str,
    chamada_id: int,
) -> list[Medicao]:
    medicoes: list[Medicao] = []
    for t in range(n_turnos):
        frase = frases[(chamada_id * n_turnos + t) % len(frases)]
        try:
            m = await _turno(url, token, voice_id, frase, chamada_id, t, hardware)
            medicoes.append(m)
        except Exception as exc:
            print(f"  [ERRO chamada={chamada_id} turno={t}] {exc}")
    return medicoes


def _relatorio(medicoes: list[Medicao]) -> bool:
    turnos = [m for m in medicoes if m.tipo == "turno"]
    cancels = [m for m in medicoes if m.tipo == "cancel"]

    if not turnos:
        print("Nenhuma medição de turno disponível.")
        return False

    ttfa_vals = [m.ttfa_ms for m in turnos]
    p = _percentis(ttfa_vals)

    engines: dict[str, int] = {}
    for m in turnos:
        engines[m.engine] = engines.get(m.engine, 0) + 1

    total = len(turnos)
    n_fallback = total - engines.get(_KVOICE_ENGINE, 0)
    fallback_pct = n_fallback / total if total > 0 else 0.0

    print(f"\n{'=' * 60}")
    print(f"Chamadas simuladas — {total} turnos totais")
    print(f"{'=' * 60}")
    print("\nTTFA por turno:")
    print(f"  p50 = {p['p50']:.0f} ms")
    print(f"  p95 = {p['p95']:.0f} ms  (gate ≤ {_GATE_TTFA_P95_MS:.0f} ms)")
    print(f"  p99 = {p['p99']:.0f} ms")
    print(f"  max = {p['max']:.0f} ms")
    print("\nDistribuição de engines:")
    for eng, cnt in sorted(engines.items()):
        print(f"  {eng}: {cnt} ({cnt / total * 100:.1f}%)")
    pct_str = f"{fallback_pct * 100:.2f}%  (gate ≤ {_GATE_FALLBACK_MAX_PCT * 100:.1f}%)"
    print(f"\nTaxa de fallback: {pct_str}")

    gate_ttfa = p["p95"] <= _GATE_TTFA_P95_MS
    gate_fallback = fallback_pct <= _GATE_FALLBACK_MAX_PCT
    gate_ok = gate_ttfa and gate_fallback

    if cancels:
        cancel_vals = [m.ttfa_ms for m in cancels]
        cp = _percentis(cancel_vals)
        gate_cancel = cp["p95"] <= _GATE_CANCEL_P95_MS
        gate_ok = gate_ok and gate_cancel
        print(f"\nCancelamento p95 = {cp['p95']:.0f} ms  (gate ≤ {_GATE_CANCEL_P95_MS:.0f} ms)")
        print(f"  {'OK' if gate_cancel else 'FAIL'}")

    print(f"\n{'=' * 60}")
    print(f"TTFA:     {'OK' if gate_ttfa else 'FAIL'}")
    print(f"Fallback: {'OK' if gate_fallback else 'FAIL'}")
    print(f"GATE:     {'OK ✓' if gate_ok else 'FAIL ✗'}")
    print(f"{'=' * 60}\n")

    return gate_ok


def _salvar_jsonl(medicoes: list[Medicao], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as f:
        for m in medicoes:
            f.write(json.dumps(asdict(m), ensure_ascii=False) + "\n")
    print(f"Salvo: {caminho} ({len(medicoes)} medições)")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--url", default="ws://localhost:8000")
    p.add_argument("--token", required=True)
    p.add_argument("--voz", required=True)
    p.add_argument(
        "--chamadas",
        type=int,
        default=10,
        help="Número de chamadas simultâneas (default: 10)",
    )
    p.add_argument(
        "--turnos",
        type=int,
        default=3,
        help="Turnos de TTS por chamada (default: 3)",
    )
    p.add_argument(
        "--concorrencias",
        default="4,8,16",
        help="Níveis de chamadas simultâneas para varrer (default: 4,8,16)",
    )
    p.add_argument("--com-cancel", action="store_true", help="Inclui teste de cancelamento")
    p.add_argument("--frases", default=_FRASES_YAML, type=Path)
    p.add_argument("--saida", default=_SAIDA, type=Path)
    return p.parse_args()


async def _run_nivel(
    url: str,
    token: str,
    voice_id: str,
    frases: list[dict[str, str]],
    n_chamadas: int,
    n_turnos: int,
    hardware: str,
    com_cancel: bool,
) -> list[Medicao]:
    print(f"\n  [{n_chamadas} chamadas × {n_turnos} turnos] iniciando ...", flush=True)
    tarefas = [
        _simular_chamada(url, token, voice_id, frases, n_turnos, hardware, i)
        for i in range(n_chamadas)
    ]
    resultados = await asyncio.gather(*tarefas)
    medicoes: list[Medicao] = [m for chamada in resultados for m in chamada]

    if com_cancel and frases:
        cancel = await _cancel_turno(url, token, voice_id, frases[0], n_chamadas, hardware)
        medicoes.append(cancel)

    n_ok = sum(1 for m in medicoes if m.tipo == "turno")
    print(f"  Concluído: {n_ok}/{n_chamadas * n_turnos} turnos", flush=True)
    return medicoes


async def _main(args: argparse.Namespace) -> bool:
    with args.frases.open(encoding="utf-8") as f:
        frases: list[dict[str, str]] = yaml.safe_load(f)["frases"]

    hardware = _gpu_info()
    concorrencias = [int(c) for c in args.concorrencias.split(",")]

    print(f"Hardware  : {hardware}")
    print(f"Servidor  : {args.url}")
    print(f"Níveis    : {concorrencias} chamadas simultâneas × {args.turnos} turnos")

    todas: list[Medicao] = []
    gate_geral = True

    for n in concorrencias:
        medicoes = await _run_nivel(
            args.url,
            args.token,
            args.voz,
            frases,
            n,
            args.turnos,
            hardware,
            args.com_cancel,
        )
        todas.extend(medicoes)
        ok = _relatorio(medicoes)
        gate_geral = gate_geral and ok

    ts = time.strftime("%Y%m%d_%H%M%S")
    _salvar_jsonl(todas, args.saida / f"carga_sip_{ts}.jsonl")

    return gate_geral


def main() -> None:
    args = _parse_args()
    ok = asyncio.run(_main(args))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
