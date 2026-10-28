"""
Teste de carga do endpoint WebSocket de streaming.

Mede TTFA (tempo até o primeiro chunk de áudio) e latência de cancelamento
com N conexões WebSocket simultâneas contra o servidor k-voice em execução.
Valida o gate da Fase 1: TTFA p95 ≤ 350 ms, cancelamento < 50 ms.

Pré-requisitos:
  - servidor k-voice rodando (uv run uvicorn kvoice.api.app:app)
  - engine carregada (set_engine chamado via lifespan ou script externo)
  - token válido com escopo tts:stream e voz cadastrada

Uso:
  uv run --group bench python -m bench.carga_ws \\
      --url ws://localhost:8000 --token SEU_TOKEN --voz v_ana
  uv run --group bench python -m bench.carga_ws \\
      --concorrencias 1,4,8,16,32 --repeticoes 5
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
_CONCORRENCIAS_PADRAO = [1, 4, 8, 16, 32]
_REPETICOES_PADRAO = 3
_GATE_TTFA_P95_MS = 350.0
_GATE_CANCEL_MS = 50.0


@dataclass
class Medicao:
    tipo: str  # "ttfa" ou "cancel"
    concorrencia: int
    valor_ms: float
    frase_id: str
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


async def _medir_ttfa(
    url: str,
    token: str,
    voice_id: str,
    frase: dict[str, str],
    concorrencia: int,
    barreira: asyncio.Barrier,
    hardware: str,
) -> Medicao:
    ws_url = f"{url}/v1/tts/stream?token={token}"
    texto = str(frase["texto"])
    frase_id = str(frase["id"])

    async with websockets.connect(ws_url) as ws:
        await barreira.wait()
        t0 = time.monotonic()

        await ws.send(json.dumps({"type": "start", "voice_id": voice_id}))

        # drena até "started"
        while True:
            raw = await ws.recv()
            if isinstance(raw, str):
                msg = json.loads(raw)
                if msg.get("type") == "started":
                    break

        # envia texto em pedaços de 4 palavras simulando tokens de LLM
        palavras = texto.split()
        i = 0
        while i < len(palavras):
            chunk = " ".join(palavras[i : i + 4])
            await ws.send(json.dumps({"type": "text", "text": chunk}))
            await asyncio.sleep(0)  # cede o loop entre chunks
            i += 4
        await ws.send(json.dumps({"type": "end"}))

        ttfa_ms = 0.0
        primeiro = True
        async for raw in ws:
            if isinstance(raw, bytes) and primeiro:
                ttfa_ms = (time.monotonic() - t0) * 1000
                primeiro = False
            elif isinstance(raw, str):
                msg = json.loads(raw)
                if msg.get("type") == "done":
                    break

    return Medicao(
        tipo="ttfa",
        concorrencia=concorrencia,
        valor_ms=round(ttfa_ms, 2),
        frase_id=frase_id,
        hardware=hardware,
        ts=_ts(),
    )


async def _medir_cancel(
    url: str,
    token: str,
    voice_id: str,
    frase: dict[str, str],
    hardware: str,
    repeticoes: int,
) -> list[Medicao]:
    ws_url = f"{url}/v1/tts/stream?token={token}"
    texto = str(frase["texto"])
    frase_id = str(frase["id"])
    medicoes: list[Medicao] = []

    for _ in range(repeticoes):
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({"type": "start", "voice_id": voice_id}))

            while True:
                raw = await ws.recv()
                if isinstance(raw, str) and json.loads(raw).get("type") == "started":
                    break

            await ws.send(json.dumps({"type": "text", "text": texto, "flush": True}))

            # aguarda o primeiro chunk antes de cancelar
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

        medicoes.append(
            Medicao(
                tipo="cancel",
                concorrencia=1,
                valor_ms=round(cancel_ms, 2),
                frase_id=frase_id,
                hardware=hardware,
                ts=_ts(),
            )
        )

    return medicoes


async def _benchmark_concorrencia(
    url: str,
    token: str,
    voice_id: str,
    frases: list[dict[str, str]],
    n: int,
    repeticoes: int,
    hardware: str,
) -> list[Medicao]:
    medicoes: list[Medicao] = []
    amostra = (frases * (n // len(frases) + 1))[:n]

    for rep in range(repeticoes):
        barreira: asyncio.Barrier = asyncio.Barrier(n)
        tarefas = [_medir_ttfa(url, token, voice_id, f, n, barreira, hardware) for f in amostra]
        resultados = await asyncio.gather(*tarefas, return_exceptions=True)
        for r in resultados:
            if isinstance(r, Medicao):
                medicoes.append(r)
            else:
                print(f"  [ERRO rep={rep}] {r}")

    return medicoes


def _imprimir_tabela(
    ttfa_por_conc: dict[int, list[Medicao]],
    cancels: list[Medicao],
) -> bool:
    cabecalho = f"\n{'Tipo':<10} {'Conc':>5} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}"
    print(cabecalho + f" {'n':>4} {'gate':>6}")
    print("-" * 65)

    gate_ok = True

    for conc in sorted(ttfa_por_conc):
        vals = [m.valor_ms for m in ttfa_por_conc[conc]]
        if not vals:
            continue
        p = _percentis(vals)
        passou = p["p95"] <= _GATE_TTFA_P95_MS
        gate_ok = gate_ok and passou
        flag = "OK" if passou else "FAIL"
        print(
            f"{'TTFA':<10} {conc:>5}"
            f" {p['p50']:>7.0f}ms {p['p95']:>7.0f}ms {p['p99']:>7.0f}ms"
            f" {p['max']:>7.0f}ms {p['n']:>4} {flag:>6}"
        )

    if cancels:
        vals = [m.valor_ms for m in cancels]
        p = _percentis(vals)
        passou = p["p95"] <= _GATE_CANCEL_MS
        gate_ok = gate_ok and passou
        flag = "OK" if passou else "FAIL"
        print(
            f"{'cancel':<10} {'1':>5}"
            f" {p['p50']:>7.0f}ms {p['p95']:>7.0f}ms {p['p99']:>7.0f}ms"
            f" {p['max']:>7.0f}ms {p['n']:>4} {flag:>6}"
        )

    print()
    status = "GATE OK" if gate_ok else "GATE FAIL"
    print(
        f"Critérios: TTFA p95 ≤ {_GATE_TTFA_P95_MS:.0f} ms, "
        f"cancel p95 ≤ {_GATE_CANCEL_MS:.0f} ms  →  {status}"
    )
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
    p.add_argument("--url", default="ws://localhost:8000", help="URL base do servidor")
    p.add_argument("--token", required=True, help="Token com escopo tts:stream")
    p.add_argument("--voz", required=True, help="ID da voz cadastrada")
    p.add_argument(
        "--concorrencias",
        default=",".join(str(c) for c in _CONCORRENCIAS_PADRAO),
        help="Níveis de concorrência (default: 1,4,8,16,32)",
    )
    p.add_argument(
        "--repeticoes",
        type=int,
        default=_REPETICOES_PADRAO,
        help=f"Repetições por nível (default: {_REPETICOES_PADRAO})",
    )
    p.add_argument("--sem-cancel", action="store_true", help="Pula teste de cancelamento")
    p.add_argument("--frases", default=_FRASES_YAML, type=Path)
    p.add_argument("--saida", default=_SAIDA, type=Path)
    return p.parse_args()


async def _main(args: argparse.Namespace) -> bool:
    with args.frases.open(encoding="utf-8") as f:
        frases: list[dict[str, str]] = yaml.safe_load(f)["frases"]

    hardware = _gpu_info()
    concorrencias = [int(c) for c in args.concorrencias.split(",")]

    print(f"Hardware    : {hardware}")
    print(f"Servidor    : {args.url}")
    print(f"Concorrência: {concorrencias} (x{args.repeticoes} repetições)")
    print()

    ttfa_por_conc: dict[int, list[Medicao]] = {}
    todas: list[Medicao] = []

    for n in concorrencias:
        print(f"  TTFA concorrência={n} ...", end=" ", flush=True)
        medicoes = await _benchmark_concorrencia(
            args.url, args.token, args.voz, frases, n, args.repeticoes, hardware
        )
        ttfa_por_conc[n] = medicoes
        todas.extend(medicoes)
        if medicoes:
            vals = [m.valor_ms for m in medicoes]
            p = _percentis(vals)
            print(f"p50={p['p50']:.0f}ms p95={p['p95']:.0f}ms")
        else:
            print("sem medições")

    cancels: list[Medicao] = []
    if not args.sem_cancel:
        print("  Cancel ...", end=" ", flush=True)
        cancels = await _medir_cancel(
            args.url, args.token, args.voz, frases[0], hardware, args.repeticoes
        )
        todas.extend(cancels)
        if cancels:
            vals = [m.valor_ms for m in cancels]
            p = _percentis(vals)
            print(f"p50={p['p50']:.0f}ms p95={p['p95']:.0f}ms")

    gate_ok = _imprimir_tabela(ttfa_por_conc, cancels)

    ts = time.strftime("%Y%m%d_%H%M%S")
    _salvar_jsonl(todas, args.saida / f"carga_ws_{ts}.jsonl")

    return gate_ok


def main() -> None:
    args = _parse_args()
    ok = asyncio.run(_main(args))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
