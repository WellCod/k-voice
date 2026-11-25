"""Conversão de PCM bruto para formatos de entrega (OGG Opus, MP3, WAV)."""

from __future__ import annotations

import io
import shutil
import subprocess
import wave


def _ffmpeg_bin() -> str:
    """Caminho do ffmpeg: o do PATH ou, no Windows, o instalado pelo winget."""
    no_path = shutil.which("ffmpeg")
    if no_path:
        return no_path
    # fallback para instalação via winget no Windows
    import glob
    import os

    padrao_winget = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\ffmpeg.exe"
    )
    encontrados = glob.glob(padrao_winget, recursive=True)
    if encontrados:
        return encontrados[0]
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
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as arquivo_wav:
        arquivo_wav.setnchannels(1)
        arquivo_wav.setsampwidth(2)
        arquivo_wav.setframerate(sample_rate)
        arquivo_wav.writeframes(pcm_data)
    return buffer.getvalue()


def preprocess_ref_audio(audio_bytes: bytes, ext: str) -> tuple[bytes, float]:
    """Normaliza loudness, remove silêncio e converte áudio de referência para WAV 16 kHz mono.

    Retorna (wav_bytes, duration_seconds).
    Levanta RuntimeError se ffmpeg falhar.
    """
    # Contêineres que o ffmpeg não detecta sozinho lendo de pipe.
    _EXT_FMT: dict[str, list[str]] = {
        "webm": ["-f", "webm"],
        "m4a": ["-f", "mp4"],
        "ogg": ["-f", "ogg"],
    }
    args_formato_entrada = _EXT_FMT.get(ext, [])
    # silenceremove só corta o começo: inverte, corta de novo e desinverte para tirar o
    # silêncio do fim. O loudnorm vem por último para medir só a fala.
    filtros_ffmpeg = (
        "silenceremove=start_periods=1:start_silence=0.3:start_threshold=-50dB,"
        "areverse,"
        "silenceremove=start_periods=1:start_silence=0.3:start_threshold=-50dB,"
        "areverse,"
        "loudnorm=I=-16:TP=-1.5:LRA=11"
    )
    comando = [
        _ffmpeg_bin(),
        "-y",
        *args_formato_entrada,
        "-i",
        "pipe:0",
        "-af",
        filtros_ffmpeg,
        "-ar",
        "16000",
        "-ac",
        "1",
        "-f",
        "s16le",
        "pipe:1",
    ]
    resultado = subprocess.run(comando, input=audio_bytes, capture_output=True, timeout=120)
    if resultado.returncode != 0:
        raise RuntimeError(f"ffmpeg preprocess: {resultado.stderr.decode(errors='replace')[:400]}")
    # PCM cru: WAV num pipe sai com o tamanho do bloco de dados em 0xFFFFFFFF, e a duração
    # lida do cabeçalho dava ~134 mil segundos para qualquer áudio.
    pcm = resultado.stdout
    return _to_wav(pcm, 16_000), pcm_duration_ms(pcm, 16_000) / 1000


def _ffmpeg(pcm_data: bytes, sample_rate: int, extra_args: list[str]) -> bytes:
    """Passa PCM 16-bit LE mono pelo ffmpeg com os argumentos de saída dados."""
    comando = [
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
    resultado = subprocess.run(comando, input=pcm_data, capture_output=True, timeout=60)
    if resultado.returncode != 0:
        raise RuntimeError(f"ffmpeg: {resultado.stderr.decode(errors='replace')[:300]}")
    return resultado.stdout
