"""
Pronúncia medida por transcrição automática (ASR round-trip).

Sintetiza cada frase de bench/frases.yaml, transcreve o áudio com o Whisper
(faster-whisper) e compara a transcrição com o texto que o motor deveria falar.
O resultado é uma taxa de erro por frase, que aponta onde o motor erra: siglas,
números, anglicismos, nomes.

Comparação: os dois lados passam pela normalização do k-voice e por uma forma
canônica (minúsculas, sem acento, sem pontuação). Assim "R$ 10" escrito pelo ASR
e "dez reais" esperado contam como iguais, e só sobra diferença de fala.

O ASR também erra. Os números servem para comparar motores, modelos e versões
no mesmo ASR, e para ordenar as piores frases; não são verdade absoluta.

Fontes de áudio:
  --motor qwen3-cpu | qwen3-gpu | stub   sintetiza com o motor do servidor
  --audios DIR                           usa {frase_id}.wav prontos (ex.: bench/sintetizar)

Saída: bench/outputs/pronuncia/<rotulo>/ com os WAV, resultado.jsonl e resumo.json.

Uso:
  uv run --group bench python -m bench.pronuncia --motor qwen3-cpu --limite 5
  uv run --group bench python -m bench.pronuncia --motor qwen3-gpu \\
      --modelo-tts Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
  uv run --group bench python -m bench.pronuncia --audios bench/outputs/elevenlabs \\
      --rotulo elevenlabs
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import platform
import re
import sys
import time
import unicodedata
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

_FRASES_YAML = ROOT / "bench" / "frases.yaml"
_SAIDA = ROOT / "bench" / "outputs" / "pronuncia"
_RE_NAO_PALAVRA = re.compile(r"[^\w\s]")
_RE_DIGITOS_LONGOS = re.compile(r"\d{10,}")


# -----------------------------------------------------------------------
# Comparação (funções puras, testadas em tests/bench/test_pronuncia.py)
# -----------------------------------------------------------------------


def canonico(texto: str) -> str:
    """Normaliza como o servidor e reduz a palavras sem acento nem pontuação.

    O ASR às vezes junta um documento numa sequência só ("23456780000199"). Essas
    sequências viram dígitos falados antes de normalizar, que é como se falam.
    """
    from kvoice.normalize import normalize
    from kvoice.normalize._num import digitos_separados

    t = _RE_DIGITOS_LONGOS.sub(lambda m: f" {digitos_separados(m.group(0))} ", texto)
    t = normalize(t).lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _RE_NAO_PALAVRA.sub(" ", t).replace("_", " ")
    return " ".join(t.split())


def distancia(a: list[str], b: list[str]) -> int:
    """Distância de Levenshtein entre sequências (substituição, inserção, remoção)."""
    anterior = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        atual = [i]
        for j, y in enumerate(b, 1):
            atual.append(min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + (x != y)))
        anterior = atual
    return anterior[-1]


def taxa_erro(referencia: list[str], hipotese: list[str]) -> float:
    if not referencia:
        return 0.0 if not hipotese else 1.0
    return distancia(referencia, hipotese) / len(referencia)


def palavras_divergentes(referencia: list[str], hipotese: list[str]) -> list[str]:
    """Palavras esperadas que não aparecem na transcrição, na ordem: pistas do erro."""
    sobra = list(hipotese)
    faltando = []
    for p in referencia:
        if p in sobra:
            sobra.remove(p)
        else:
            faltando.append(p)
    return faltando


# -----------------------------------------------------------------------
# Medição
# -----------------------------------------------------------------------


@dataclass
class Resultado:
    frase_id: str
    categoria: str
    texto: str
    esperado: str
    transcrito: str
    wer: float
    cer: float
    faltando: list[str]
    sintese_s: float
    audio_s: float


def _versao(pacote: str) -> str:
    try:
        return importlib.metadata.version(pacote)
    except importlib.metadata.PackageNotFoundError:
        return "?"


def _gravar_wav(caminho: Path, pcm: bytes, taxa: int) -> None:
    with wave.open(str(caminho), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(taxa)
        wf.writeframes(pcm)


def _carregar_motor(nome: str, modelo_tts: str, speaker: str) -> Any:
    if nome == "stub":
        from kvoice.engine.stub import StubEngine

        return StubEngine()
    if nome == "qwen3-cpu":
        from kvoice.engine.qwen3_tts import Qwen3TTSEngine

        return Qwen3TTSEngine.load(modelo_tts, "", speaker, device="cpu")
    if nome == "qwen3-gpu":
        from kvoice.engine.faster_qwen3 import FasterQwen3Engine

        return FasterQwen3Engine.load(modelo_tts, "", speaker, device="cuda")
    raise SystemExit(f"motor desconhecido: {nome}")


async def _sintetizar(motor: Any, texto: str, voz: Any) -> tuple[bytes, int, float]:
    from kvoice.engine.types import SynthOptions
    from kvoice.normalize import normalize

    t0 = time.monotonic()
    audio = await motor.synthesize(normalize(texto), voz, SynthOptions())
    return audio.data, audio.sample_rate, time.monotonic() - t0


def _transcritor(modelo: str, device: str) -> Any:
    from faster_whisper import WhisperModel

    compute = "int8" if device == "cpu" else "float16"
    return WhisperModel(modelo, device=device, compute_type=compute)


def _audio_16k(wav: Path) -> Any:
    """WAV em float32 mono a 16 kHz, o formato que o Whisper recebe como array.

    Decodifica aqui em vez de passar o caminho: o faster-whisper 1.2.1 abre arquivo pelo
    PyAV com um argumento que o av 19 não aceita mais.
    """
    from math import gcd

    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    dados, taxa = sf.read(str(wav), dtype="float32", always_2d=False)
    if dados.ndim > 1:
        dados = dados.mean(axis=1)
    if taxa != 16_000:
        g = gcd(16_000, taxa)
        dados = resample_poly(dados, 16_000 // g, taxa // g)
    return np.asarray(dados, dtype=np.float32)


def _transcrever(asr: Any, wav: Path) -> str:
    segmentos, _info = asr.transcribe(
        _audio_16k(wav),
        language="pt",
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    return " ".join(s.text.strip() for s in segmentos)


def _resumo(resultados: list[Resultado], meta: dict[str, Any]) -> dict[str, Any]:
    def media(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    categorias: dict[str, list[Resultado]] = {}
    for r in resultados:
        categorias.setdefault(r.categoria, []).append(r)
    piores = sorted(resultados, key=lambda r: (r.wer, r.cer), reverse=True)
    return {
        **meta,
        "frases": len(resultados),
        "wer_medio": media([r.wer for r in resultados]),
        "cer_medio": media([r.cer for r in resultados]),
        "frases_sem_erro": sum(1 for r in resultados if r.wer == 0),
        "por_categoria": {
            c: {"n": len(rs), "wer": media([r.wer for r in rs]), "cer": media([r.cer for r in rs])}
            for c, rs in sorted(categorias.items(), key=lambda kv: -media([r.wer for r in kv[1]]))
        },
        "piores": [
            {
                "id": r.frase_id,
                "wer": round(r.wer, 3),
                "faltando": r.faltando,
                "transcrito": r.transcrito,
            }
            for r in piores[:10]
            if r.wer > 0
        ],
    }


def _imprimir(resumo: dict[str, Any]) -> None:
    print(
        f"\n{resumo['rotulo']}: {resumo['frases']} frases, WER médio {resumo['wer_medio']:.1%}, "
        f"CER médio {resumo['cer_medio']:.1%}, {resumo['frases_sem_erro']} sem erro"
    )
    print(f"\n{'categoria':<24} {'n':>3} {'WER':>7} {'CER':>7}")
    for c, v in resumo["por_categoria"].items():
        print(f"{c:<24} {v['n']:>3} {v['wer']:>7.1%} {v['cer']:>7.1%}")
    if resumo["piores"]:
        print("\npiores frases:")
        for p in resumo["piores"]:
            print(f"  {p['id']:<26} WER {p['wer']:.0%}  faltou: {' '.join(p['faltando'][:8])}")
            print(f"  {'':<26} ouviu: {p['transcrito']}")


async def _rodar(args: argparse.Namespace) -> None:
    import yaml

    from kvoice.engine.types import Voice

    frases = yaml.safe_load(args.frases.read_text(encoding="utf-8"))["frases"]
    if args.categoria:
        frases = [f for f in frases if str(f.get("categoria", "")).startswith(args.categoria)]
    if args.limite:
        frases = frases[: args.limite]

    rotulo = args.rotulo or (args.motor if not args.audios else args.audios.name)
    saida = args.saida / rotulo
    saida.mkdir(parents=True, exist_ok=True)

    motor = None
    if not args.audios:
        t = time.monotonic()
        motor = _carregar_motor(args.motor, args.modelo_tts, args.speaker)
        print(f"motor {args.motor} carregado em {time.monotonic() - t:.1f}s")
    voz = Voice(id="bench", name="bench", model_id=args.speaker)

    t = time.monotonic()
    asr = _transcritor(args.asr, args.asr_device)
    print(f"ASR {args.asr} ({args.asr_device}) carregado em {time.monotonic() - t:.1f}s")

    resultados: list[Resultado] = []
    erros: list[dict[str, str]] = []
    jsonl = (saida / "resultado.jsonl").open("w", encoding="utf-8")
    for n, f in enumerate(frases, 1):
        fid, texto = str(f["id"]), str(f["texto"])
        sintese_s = 0.0
        try:
            if args.audios:
                wav = args.audios / f"{fid}.wav"
                if not wav.exists():
                    print(f"  [{n}/{len(frases)}] {fid}: sem áudio, pulada")
                    continue
            elif args.reaproveitar and (saida / f"{fid}.wav").exists():
                wav = saida / f"{fid}.wav"
            else:
                pcm, taxa, sintese_s = await _sintetizar(motor, texto, voz)
                wav = saida / f"{fid}.wav"
                _gravar_wav(wav, pcm, taxa)
            with wave.open(str(wav), "rb") as wf:
                audio_s = wf.getnframes() / wf.getframerate()
            transcrito = _transcrever(asr, wav)
            ref, hip = canonico(texto).split(), canonico(transcrito).split()
        except Exception as exc:
            # Uma frase com erro (no motor, no ASR ou no normalizador) não derruba a medição.
            erros.append({"id": fid, "erro": f"{type(exc).__name__}: {exc}"})
            print(f"  [{n}/{len(frases)}] {fid}: ERRO {type(exc).__name__}: {exc}")
            continue
        r = Resultado(
            frase_id=fid,
            categoria=str(f.get("categoria", "")),
            texto=texto,
            esperado=" ".join(ref),
            transcrito=transcrito,
            wer=taxa_erro(ref, hip),
            cer=taxa_erro(list(" ".join(ref)), list(" ".join(hip))),
            faltando=palavras_divergentes(ref, hip),
            sintese_s=round(sintese_s, 2),
            audio_s=round(audio_s, 2),
        )
        resultados.append(r)
        jsonl.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
        jsonl.flush()
        print(f"  [{n}/{len(frases)}] {fid}: WER {r.wer:.0%} (síntese {sintese_s:.1f}s)")
    jsonl.close()

    meta = {
        "rotulo": rotulo,
        "motor": args.motor if not args.audios else f"audios:{args.audios}",
        "modelo_tts": None if args.audios else args.modelo_tts,
        "speaker": args.speaker,
        "asr": args.asr,
        "data": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "maquina": f"{platform.processor() or platform.machine()} · {platform.system()}",
        "versoes": {
            p: _versao(p)
            for p in (
                "kvoice",
                "faster-qwen3-tts",
                "qwen-tts-hf",
                "torch",
                "transformers",
                "faster-whisper",
                "ctranslate2",
            )
        },
    }
    resumo = {**_resumo(resultados, meta), "erros": erros}
    (saida / "resumo.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _imprimir(resumo)
    for e in erros:
        print(f"ERRO {e['id']}: {e['erro']}")
    print(f"\nresultado: {saida}")
    if erros:
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--motor", default="qwen3-cpu", choices=["qwen3-cpu", "qwen3-gpu", "stub"])
    p.add_argument("--audios", type=Path, default=None, help="pasta com {frase_id}.wav prontos")
    p.add_argument("--modelo-tts", default="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    p.add_argument("--speaker", default="vivian")
    p.add_argument("--asr", default="large-v3", help="modelo do faster-whisper (medium, large-v3)")
    p.add_argument("--asr-device", default="cpu")
    p.add_argument("--categoria", default="", help="prefixo de categoria, ex.: normalizacao")
    p.add_argument("--limite", type=int, default=0)
    p.add_argument("--rotulo", default="", help="nome da pasta de saída")
    p.add_argument(
        "--reaproveitar",
        action="store_true",
        help="usa o WAV já sintetizado na pasta de saída em vez de sintetizar de novo",
    )
    p.add_argument("--frases", type=Path, default=_FRASES_YAML)
    p.add_argument("--saida", type=Path, default=_SAIDA)
    return p.parse_args()


def main() -> None:
    asyncio.run(_rodar(_parse_args()))


if __name__ == "__main__":
    main()
