"""
Análise estatística das respostas do teste cego.

Lê o CSV exportado pela página HTML e calcula:
  ABX   — taxa de acerto por motor + teste binomial (H0: p=0.5)
           Gate: não rejeitar H0 (p > 0.05) → ouvintes não distinguem
  MOS   — média e IC 95% por motor
  Pref  — percentual de preferência pelo candidato

Uso:
  uv run python -m bench.analisar bench/teste_cego/respostas.csv
  uv run python -m bench.analisar bench/teste_cego/respostas.csv --condicao tel
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats


def _ler_csv(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _analisar_abx(linhas: list[dict[str, str]], condicao: str | None) -> None:
    por_motor: dict[str, list[int]] = defaultdict(list)
    for r in linhas:
        if r["tipo"] != "abx":
            continue
        if condicao and r.get("audio_condicao") != condicao:
            continue
        motor = r["motor_candidato"]
        por_motor[motor].append(int(r["correto"]))

    if not por_motor:
        return

    print("=== ABX ===")
    header = f"{'Motor':<28} {'n':>5} {'acertos':>8} {'%':>7} {'p-valor':>9}  {'Gate'}"
    print(header)
    print("-" * len(header))
    for motor in sorted(por_motor):
        resultados = por_motor[motor]
        n = len(resultados)
        k = sum(resultados)
        taxa = k / n * 100
        result = stats.binomtest(k, n, p=0.5, alternative="greater")
        gate = "OK (não distingue)" if result.pvalue > 0.05 else "FALHOU"
        print(f"{motor:<28} {n:>5} {k:>8} {taxa:>6.1f}%  {result.pvalue:>8.3f}  {gate}")
    print()


def _analisar_mos(linhas: list[dict[str, str]], condicao: str | None) -> None:
    por_motor: dict[str, list[float]] = defaultdict(list)
    for r in linhas:
        if r["tipo"] != "mos":
            continue
        if condicao and r.get("audio_condicao") != condicao:
            continue
        por_motor[r["motor"]].append(float(r["resposta"]))

    if not por_motor:
        return

    print("=== MOS ===")
    header = f"{'Motor':<28} {'n':>5} {'média':>7} {'IC 95%':>10}"
    print(header)
    print("-" * len(header))
    for motor in sorted(por_motor):
        vals = np.array(por_motor[motor])
        n = len(vals)
        media = vals.mean()
        margem = stats.t.ppf(0.975, df=n - 1) * stats.sem(vals) if n > 1 else float("nan")
        print(f"{motor:<28} {n:>5} {media:>7.2f}  ±{margem:.2f}")
    print()


def _analisar_preferencia(linhas: list[dict[str, str]], condicao: str | None) -> None:
    por_par: dict[str, list[str]] = defaultdict(list)
    for r in linhas:
        if r["tipo"] != "preferencia":
            continue
        if condicao and r.get("audio_condicao") != condicao:
            continue
        par = f"{r.get('motor_ref', '?')} vs {r['motor_candidato']}"
        por_par[par].append(r["resposta"])

    if not por_par:
        return

    print("=== Preferência ===")
    for par in sorted(por_par):
        respostas = por_par[par]
        n = len(respostas)
        cand = respostas.count("candidato")
        pct = cand / n * 100 if n else 0
        gate = "OK (≥ 40%)" if pct >= 40 else "FALHOU"
        print(f"{par}")
        print(
            f"  n={n}  candidato={cand} ({pct:.1f}%)  ref={n - cand} ({100 - pct:.1f}%)  → {gate}"
        )
    print()


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("csv", type=Path, help="CSV de respostas exportado pela página de teste")
    p.add_argument("--condicao", choices=["tel", "opus"], default=None)
    args = p.parse_args()

    linhas = _ler_csv(args.csv)
    desc = f"condição={args.condicao}" if args.condicao else "todas as condições"
    print(f"\nAnálise: {args.csv} ({len(linhas)} respostas, {desc})\n")

    _analisar_abx(linhas, args.condicao)
    _analisar_mos(linhas, args.condicao)
    _analisar_preferencia(linhas, args.condicao)


if __name__ == "__main__":
    main()
