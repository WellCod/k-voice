"""Conversão de PCM bruto para formatos de entrega (OGG Opus, MP3, WAV)."""

from __future__ import annotations

import io
import shutil
import subprocess
import wave


def _ffmpeg_bin() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    # fallback para instalação via winget no Windows
    import glob
    import os

    pattern = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\ffmpeg.exe"
    )
    matches = glob.glob(pattern, recursive=True)
    if matches:
        return matches[0]
    return "ffmpeg"


_CONTENT_TYPES: dict[str, str] = {
    "ogg_opus": "audio/ogg; codecs=opus",
    "mp3_44100": "audio/mpeg",
    "wav_24000": "audio/wav",
}

# -ar/-ac/-c:a/-f aplicados ao stream de saída (pipe:1)
_FFMPEG_ARGS: dict[str, list[str]] = {
    "ogg_opus": ["-ar", "48000", "-ac", "1", "-c:a", "libopus", "-f", "ogg"],
    "mp3_44100": ["-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-f", "mp3"],
}


def encode(pcm_data: bytes, sample_rate: int, fmt: str) -> tuple[bytes, str]:
    """Converte PCM 16-bit LE mono para o formato pedido."""
    if fmt == "wav_24000":
        return _to_wav(pcm_data, sample_rate), _CONTENT_TYPES[fmt]
    return _ffmpeg(pcm_data, sample_rate, _FFMPEG_ARGS[fmt]), _CONTENT_TYPES[fmt]


def pcm_duration_ms(pcm_data: bytes, sample_rate: int) -> float:
    """Duração em milissegundos de PCM 16-bit LE mono."""
    return (len(pcm_data) // 2) / sample_rate * 1000


def _to_wav(pcm_data: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _ffmpeg(pcm_data: bytes, sample_rate: int, extra_args: list[str]) -> bytes:
    cmd = [
        _ffmpeg_bin(),
        "-y",
        "-f",
        "s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-i",
        "pipe:0",
        *extra_args,
        "pipe:1",
    ]
    result = subprocess.run(cmd, input=pcm_data, capture_output=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg: {result.stderr.decode(errors='replace')[:300]}")
    return result.stdout
