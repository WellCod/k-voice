"""
Benchmark de latência e concorrência em síntese de voz.

Mede TTFA (tempo até o primeiro áudio) e RTF por motor e nível de concorrência.
Para motores com streaming nativo (Qwen3-TTS, ElevenLabs) usa a API de streaming
para TTFA real; nos demais, TTFA = tempo total de síntese (pior caso).

Concorrência: N threads lançadas simultaneamente com threading.Barrier.
Para GPU, threads concorrentes competem pela mesma GPU — mede como o TTFA
degrada com a carga. Para ElevenLabs (rede), mede latência de I/O paralelo.

TTFA = do envio do texto até o primeiro byte de áudio reproduzível (docs/teste-cego.md).
Texto chega em pedaços de 3–8 palavras simulando saída de LLM; para motores sem
streaming incremental, o texto completo é enviado de uma vez (caso real da Fase 0).

Resultados salvos em bench/outputs/latencia_{motor}_{ts}.jsonl com hardware, versão e data.
Compare o resultado do Qwen3-TTS com o da ElevenLabs a partir da mesma região do LiveKit.

Uso:
  uv run python -m bench.latencia --motores qwen,elevenlabs
  uv run python -m bench.latencia --motores todos --concorrencias 1,4,8,16,32 --repeticoes 5
  uv run python -m bench.latencia --motores qwen --ref-audio bench/referencias/voz.wav
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import yaml
from tqdm import tqdm

from bench.motores import MOTORES_DISPONIVEIS, carregar_motor

_CONCORRENCIAS_PADRAO = [1, 4, 8, 16, 32]
_REPETICOES_PADRAO = 3
_FRASES_YAML = ROOT / "bench" / "frases.yaml"
_SAIDA = ROOT / "bench" / "outputs"


# -----------------------------------------------------------------------
# Dataclass de medição
# -----------------------------------------------------------------------


@dataclass
class Medicao:
    motor: str
    frase_id: str
    concorrencia: int
    ttfa_ms: float
    duracao_sintese_ms: float
    duracao_audio_ms: float
    rtf: float
    modo_ttfa: str  # "streaming" ou "total"
    hardware: str
    ts: str


# -----------------------------------------------------------------------
# Utilitários
# -----------------------------------------------------------------------


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


def _chunkar_texto(texto: str, min_palavras: int = 3, max_palavras: int = 8) -> list[str]:
    """Divide texto em grupos de 3–8 palavras (simula tokens de LLM)."""
    import random

    rng = random.Random(0)
    palavras = texto.split()
    chunks: list[str] = []
    i = 0
    while i < len(palavras):
        n = rng.randint(min_palavras, max_palavras)
        chunk = " ".join(palavras[i : i + n])
        if chunk:
            chunks.append(chunk)
        i += n
    return chunks


def _percentis(valores: list[float]) -> dict[str, float]:
    a = np.array(valores)
    return {
        "p50": float(np.percentile(a, 50)),
        "p95": float(np.percentile(a, 95)),
        "p99": float(np.percentile(a, 99)),
        "max": float(a.max()),
        "min": float(a.min()),
        "n": len(valores),
    }


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# -----------------------------------------------------------------------
# Medição de um único stream
# -----------------------------------------------------------------------


def _medir_um(
    motor: object,
    frase: dict[str, str],
    concorrencia: int,
    hardware: str,
    usar_streaming: bool,
    kwargs_streaming: dict[str, object],
) -> Medicao:
    texto = str(frase["texto"]).strip()
    frase_id = frase["id"]

    if usar_streaming:
        nome = str(getattr(motor, "nome", "?"))
        if nome.startswith("qwen"):
            from bench.motores.streaming import medir_ttfa_qwen

            ttfa_ms, dur_ms, dur_audio_ms = medir_ttfa_qwen(
                modelo=motor._modelo,  # type: ignore[union-attr]
                texto=texto,
                instrucao_voz=str(kwargs_streaming.get("instrucao_voz", "")),
                ref_audio=str(v) if (v := kwargs_streaming.get("ref_audio")) else None,
                ref_texto=str(v) if (v := kwargs_streaming.get("ref_texto")) else None,
            )
            modo = "streaming"
        elif nome == "elevenlabs":
            from bench.motores.streaming import medir_ttfa_elevenlabs

            ttfa_ms, dur_ms, dur_audio_ms = medir_ttfa_elevenlabs(
                client=motor._client,  # type: ignore[union-attr]
                texto=texto,
                voice_id=str(kwargs_streaming.get("voice_id", "")),
                model_id=str(kwargs_streaming.get("model_id", "")),
            )
            modo = "streaming"
        else:
            usar_streaming = False  # fallback para total

    if not usar_streaming:
        t = time.perf_counter()
        resultado = motor.sintetizar(texto, frase_id)  # type: ignore[union-attr]
        dur_ms = (time.perf_counter() - t) * 1000
        ttfa_ms = dur_ms
        dur_audio_ms = resultado.duracao_audio_ms
        modo = "total"

    rtf = dur_ms / max(dur_audio_ms, 1.0)

    return Medicao(
        motor=str(getattr(motor, "nome", "?")),
        frase_id=frase_id,
        concorrencia=concorrencia,
        ttfa_ms=round(ttfa_ms, 2),
        duracao_sintese_ms=round(dur_ms, 2),
        duracao_audio_ms=round(dur_audio_ms, 2),
        rtf=round(rtf, 4),
        modo_ttfa=modo,
        hardware=hardware,
        ts=_ts(),
    )


# -----------------------------------------------------------------------
# Benchmark por nível de concorrência
# -----------------------------------------------------------------------


def _benchmark_concorrencia(
    motor: object,
    frases: list[dict[str, str]],
    n: int,
    repeticoes: int,
    hardware: str,
    usar_streaming: bool,
    kwargs_streaming: dict[str, object],
) -> list[Medicao]:
    medicoes: list[Medicao] = []
    amostra = (frases * (n // len(frases) + 1))[:n]

    for _ in range(repeticoes):
        barreira = threading.Barrier(n)

        def _fazer_tarefa(b: threading.Barrier) -> object:
            def _executar(frase: dict[str, str]) -> Medicao:
                b.wait()  # todos os threads começam juntos
                return _medir_um(motor, frase, n, hardware, usar_streaming, kwargs_streaming)

            return _executar

        tarefa = _fazer_tarefa(barreira)

        with ThreadPoolExecutor(max_workers=n) as ex:
            futuros = [ex.submit(tarefa, f) for f in amostra]
            for fut in as_completed(futuros):
                try:
                    medicoes.append(fut.result())
                except Exception as e:
                    tqdm.write(f"  [ERRO] concorrencia={n}: {e}")

    return medicoes


# -----------------------------------------------------------------------
# Saída
# -----------------------------------------------------------------------


def _imprimir_tabela(resultados: dict[str, dict[int, list[Medicao]]]) -> None:
    print(
        f"\n{'Motor':<26} {'Conc':>5} {'Modo':<10} {'TTFA p50':>9}"
        f" {'TTFA p95':>9} {'RTF p50':>8} {'RTF p95':>8} {'n':>4}"
    )
    print("-" * 85)
    for motor_nome in sorted(resultados):
        for conc in sorted(resultados[motor_nome]):
            medicoes = resultados[motor_nome][conc]
            if not medicoes:
                continue
            ttfas = [m.ttfa_ms for m in medicoes]
            rtfs = [m.rtf for m in medicoes]
            pt = _percentis(ttfas)
            pr = _percentis(rtfs)
            modo = medicoes[0].modo_ttfa
            print(
                f"{motor_nome:<26} {conc:>5} {modo:<10}"
                f" {pt['p50']:>8.0f}ms {pt['p95']:>8.0f}ms"
                f" {pr['p50']:>8.3f} {pr['p95']:>8.3f} {pt['n']:>4}"
            )
    print()


def _salvar_jsonl(medicoes: list[Medicao], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as f:
        for m in medicoes:
            f.write(json.dumps(asdict(m), ensure_ascii=False) + "\n")
    print(f"Salvo: {caminho} ({len(medicoes)} medições)")


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--motores",
        default="todos",
        help="Motores separados por vírgula ou 'todos'",
    )
    p.add_argument(
        "--concorrencias",
        default=",".join(str(c) for c in _CONCORRENCIAS_PADRAO),
        help="Níveis de concorrência separados por vírgula (default: 1,4,8,16,32)",
    )
    p.add_argument(
        "--repeticoes",
        type=int,
        default=_REPETICOES_PADRAO,
        help=f"Repetições por nível de concorrência (default: {_REPETICOES_PADRAO})",
    )
    p.add_argument("--frases", default=_FRASES_YAML, type=Path)
    p.add_argument("--saida", default=_SAIDA, type=Path)
    p.add_argument("--ref-audio", default=None, type=Path)
    p.add_argument("--ref-texto", default=None)
    p.add_argument("--voz-elevenlabs", default="21m00Tcm4TlvDq8ikWAM")
    p.add_argument("--modelo-elevenlabs", default="eleven_flash_v2_5")
    p.add_argument(
        "--sem-streaming",
        action="store_true",
        help="Desativa medição de TTFA via streaming (usa tempo total)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    nomes = MOTORES_DISPONIVEIS if args.motores == "todos" else args.motores.split(",")
    concorrencias = [int(c) for c in args.concorrencias.split(",")]

    with _FRASES_YAML.open(encoding="utf-8") as f:
        frases: list[dict[str, str]] = yaml.safe_load(f)["frases"]

    hardware = _gpu_info()
    print(f"Hardware : {hardware}")
    print(f"Motores  : {nomes}")
    print(f"Conc.    : {concorrencias} (x{args.repeticoes} repetições)")
    print()

    kwargs_por_motor: dict[str, dict[str, object]] = {
        "qwen": {
            "instrucao_voz": "Voz feminina, clara, português brasileiro.",
            "ref_audio": str(args.ref_audio) if args.ref_audio else None,
            "ref_texto": args.ref_texto,
        },
        "elevenlabs": {
            "voice_id": args.voz_elevenlabs,
            "model_id": args.modelo_elevenlabs,
        },
    }

    resultados: dict[str, dict[int, list[Medicao]]] = {}
    todas_medicoes: list[Medicao] = []

    for nome in nomes:
        print(f"=== Motor: {nome} ===")
        try:
            kw_motor: dict[str, object] = (
                {"ref_audio": str(args.ref_audio) if args.ref_audio else None}
                if nome == "qwen"
                else {}
            )
            motor = carregar_motor(nome, **kw_motor)
            motor.carregar()  # type: ignore[union-attr]
        except ImportError as e:
            print(f"  [PULADO] dependência ausente: {e}\n")
            continue
        except Exception as e:
            print(f"  [ERRO ao carregar] {e}\n")
            continue

        usar_streaming = not args.sem_streaming and nome in ("qwen", "elevenlabs")
        resultados[nome] = {}

        for n in concorrencias:
            print(f"  concorrência={n} ...", end=" ", flush=True)
            medicoes = _benchmark_concorrencia(
                motor=motor,
                frases=frases,
                n=n,
                repeticoes=args.repeticoes,
                hardware=hardware,
                usar_streaming=usar_streaming,
                kwargs_streaming=kwargs_por_motor.get(nome, {}),
            )
            resultados[nome][n] = medicoes
            todas_medicoes.extend(medicoes)
            if medicoes:
                ttfas = [m.ttfa_ms for m in medicoes]
                p50 = np.percentile(ttfas, 50)
                p95 = np.percentile(ttfas, 95)
                print(f"TTFA p50={p50:.0f}ms p95={p95:.0f}ms")
            else:
                print("sem medições")

        motor.descarregar()  # type: ignore[union-attr]
        print()

    _imprimir_tabela(resultados)

    ts = time.strftime("%Y%m%d_%H%M%S")
    for nome in resultados:
        motor_medicoes = [m for m in todas_medicoes if m.motor.startswith(nome[:4])]
        if motor_medicoes:
            _salvar_jsonl(
                motor_medicoes,
                args.saida / f"latencia_{nome}_{ts}.jsonl",
            )


if __name__ == "__main__":
    main()
