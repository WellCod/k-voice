"""
Degrada áudio de síntese para as condições de escuta do teste cego.

Condição telefone (sufixo _tel):
  1. Passa-banda Butterworth 4ª ordem — 300–3400 Hz
  2. Resample para 8 kHz
  3. μ-law encode + decode (quantização 8-bit)
  4. Normalização de loudness para −16 LUFS

Condição WebRTC / Opus (sufixo _opus, requer ffmpeg no PATH):
  1. Encode para Opus 32 kbps 48 kHz
  2. Decode de volta para WAV PCM
  3. Normalização de loudness para −16 LUFS

Uso:
  uv run python -m bench.degradar --entrada bench/outputs --motores elevenlabs,qwen3-tts-0.6b
  uv run python -m bench.degradar --entrada bench/outputs --motores todos --sem-opus
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from math import gcd
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import numpy.typing as npt
import pyloudnorm as pyln
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt
from tqdm import tqdm

_LUFS_ALVO = -16.0
_SR_TEL = 8_000


def _bandpass(audio: npt.NDArray[np.float32], sr: int) -> npt.NDArray[np.float32]:
    """Passa-banda Butterworth 4ª ordem — 300–3400 Hz."""
    nyq = sr / 2.0
    low = 300.0 / nyq
    high = min(3400.0 / nyq, 0.999)
    sos = butter(4, [low, high], btype="band", output="sos")
    return sosfilt(sos, audio).astype(np.float32)


def _resample(audio: npt.NDArray[np.float32], sr_in: int, sr_out: int) -> npt.NDArray[np.float32]:
    if sr_in == sr_out:
        return audio
    g = gcd(sr_in, sr_out)
    return resample_poly(audio, sr_out // g, sr_in // g).astype(np.float32)


def _ulaw_round_trip(audio: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """Simula quantização μ-law de 8 bits (255 níveis)."""
    mu = 255.0
    x = np.clip(audio, -1.0, 1.0)
    encoded = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    quantized = np.round((encoded + 1.0) / 2.0 * mu).clip(0, mu).astype(np.uint8)
    y = quantized.astype(np.float32) / mu * 2.0 - 1.0
    return (np.sign(y) * (1.0 / mu) * (np.power(1.0 + mu, np.abs(y)) - 1.0)).astype(np.float32)


def _normalize_lufs(
    audio: npt.NDArray[np.float32], sr: int, alvo: float = _LUFS_ALVO
) -> npt.NDArray[np.float32]:
    meter = pyln.Meter(sr)
    loudness = meter.integrated_loudness(audio.astype(np.float64))
    if not np.isfinite(loudness):
        return audio
    normalizado = pyln.normalize.loudness(audio.astype(np.float64), loudness, alvo)
    return np.clip(normalizado, -1.0, 1.0).astype(np.float32)


def degradar_telefone(
    audio: npt.NDArray[np.float32], sr: int
) -> tuple[npt.NDArray[np.float32], int]:
    """Passa-banda → 8 kHz → μ-law round-trip → −16 LUFS."""
    audio = _bandpass(audio, sr)
    audio = _resample(audio, sr, _SR_TEL)
    audio = _ulaw_round_trip(audio)
    audio = _normalize_lufs(audio, _SR_TEL)
    return audio, _SR_TEL


def degradar_opus(
    audio: npt.NDArray[np.float32], sr: int, ffmpeg: str = "ffmpeg"
) -> tuple[npt.NDArray[np.float32], int]:
    """Encode Opus 32 kbps → decode → −16 LUFS. Requer ffmpeg no PATH."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sf.write(str(d / "in.wav"), audio, sr, subtype="PCM_16")
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(d / "in.wav"),
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                "-ar",
                "48000",
                str(d / "tmp.ogg"),
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            [ffmpeg, "-y", "-i", str(d / "tmp.ogg"), str(d / "out.wav")],
            capture_output=True,
            check=True,
        )
        out, sr_out = sf.read(str(d / "out.wav"), dtype="float32")

    return _normalize_lufs(out, sr_out), sr_out


def _processar_diretorio(
    entrada: Path,
    saida: Path,
    modo: str,
    ffmpeg: str = "ffmpeg",
) -> None:
    wavs = sorted(entrada.glob("*.wav"))
    if not wavs:
        return
    saida.mkdir(parents=True, exist_ok=True)
    for wav in tqdm(wavs, desc=f"{entrada.name} → {saida.name}", unit="frase"):
        audio, sr = sf.read(str(wav), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        try:
            if modo == "tel":
                audio_out, sr_out = degradar_telefone(audio, sr)
            else:
                audio_out, sr_out = degradar_opus(audio, sr, ffmpeg)
            sf.write(str(saida / wav.name), audio_out, sr_out, subtype="PCM_16")
        except Exception as e:
            tqdm.write(f"  [ERRO] {wav.name}: {e}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--entrada", default=ROOT / "bench" / "outputs", type=Path)
    p.add_argument(
        "--motores",
        default="todos",
        help="Nomes dos motores separados por vírgula (ou 'todos')",
    )
    p.add_argument("--sem-opus", action="store_true", help="Pula a condição Opus/WebRTC")
    p.add_argument("--ffmpeg", default="ffmpeg", help="Caminho do binário ffmpeg")
    args = p.parse_args()

    if args.motores == "todos":
        motores = [
            d.name
            for d in args.entrada.iterdir()
            if d.is_dir() and not d.name.endswith(("_tel", "_opus"))
        ]
    else:
        motores = args.motores.split(",")

    print(f"Motores: {motores}")
    print(f"Entrada: {args.entrada}")
    print()

    for motor in motores:
        dir_in = args.entrada / motor
        if not dir_in.exists():
            print(f"  [PULADO] {dir_in} não existe")
            continue
        _processar_diretorio(dir_in, args.entrada / f"{motor}_tel", "tel")
        if not args.sem_opus:
            try:
                _processar_diretorio(dir_in, args.entrada / f"{motor}_opus", "opus", args.ffmpeg)
            except FileNotFoundError:
                print("  [PULADO] ffmpeg não encontrado — use --sem-opus para pular Opus")


if __name__ == "__main__":
    main()
