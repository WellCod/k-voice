"""
Adaptadores de medição de TTFA com streaming nativo.

Cada classe envolve o modelo carregado do motor correspondente e retorna
(ttfa_ms, duracao_sintese_ms, duracao_audio_ms) a partir da API de streaming.

TTFA = do envio do primeiro pedaço de texto até o primeiro byte de áudio
reproduzível (não cabeçalho). Definição de docs/teste-cego.md.

Para Qwen3-TTS: usa generate_voice_clone_streaming / generate_voice_design
com streaming, que emitem o primeiro chunk antes do texto terminar.

Para ElevenLabs: usa text_to_speech.stream, que emite chunks de PCM
progressivamente antes de gerar o áudio completo.

Uso interno de bench/latencia.py — não instanciar diretamente.
"""

from __future__ import annotations

import time

import numpy as np


def medir_ttfa_qwen(
    modelo: object,
    texto: str,
    instrucao_voz: str,
    ref_audio: str | None = None,
    ref_texto: str | None = None,
    taxa: int = 24_000,
) -> tuple[float, float, float]:
    """
    Retorna (ttfa_ms, duracao_sintese_ms, duracao_audio_ms).

    APIs verificadas em faster-qwen3-tts 0.4.x — generate_voice_clone_streaming e
    generate_voice_design retornam (audio_chunk, sr, timing) por iteração.
    chunk_size=8 ≈ 667 ms de áudio por chunk, padrão da lib.
    """
    t_inicio = time.perf_counter()
    ttfa_ms: float | None = None
    total_amostras = 0

    if ref_audio and ref_texto:
        iterador = modelo.generate_voice_clone_streaming(  # type: ignore[union-attr]
            text=texto,
            language="Portuguese",
            ref_audio=ref_audio,
            ref_text=ref_texto,
            chunk_size=8,
        )
    else:
        iterador = modelo.generate_voice_design_streaming(  # type: ignore[union-attr]
            text=texto,
            language="Portuguese",
            instruct=instrucao_voz,
            chunk_size=8,
        )

    for audio_chunk, sr, _ in iterador:
        chunk_np = np.asarray(audio_chunk)
        if ttfa_ms is None and chunk_np.size > 0:
            ttfa_ms = (time.perf_counter() - t_inicio) * 1000
        total_amostras += int(chunk_np.size)
        taxa = int(sr)

    duracao_sintese_ms = (time.perf_counter() - t_inicio) * 1000
    duracao_audio_ms = total_amostras / taxa * 1000

    return (ttfa_ms or duracao_sintese_ms), duracao_sintese_ms, duracao_audio_ms


def medir_ttfa_elevenlabs(
    client: object,
    texto: str,
    voice_id: str,
    model_id: str,
    taxa: int = 24_000,
) -> tuple[float, float, float]:
    """
    Retorna (ttfa_ms, duracao_sintese_ms, duracao_audio_ms).

    Usa text_to_speech.stream com output_format=pcm_24000 (PCM 16-bit signed
    little-endian, 24 kHz). O primeiro chunk com bytes não-nulos marca o TTFA.
    """
    t_inicio = time.perf_counter()
    ttfa_ms: float | None = None
    total_bytes = 0

    for chunk in client.text_to_speech.stream(  # type: ignore[union-attr]
        text=texto,
        voice_id=voice_id,
        model_id=model_id,
        output_format="pcm_24000",
    ):
        if isinstance(chunk, bytes) and len(chunk) > 0:
            if ttfa_ms is None:
                ttfa_ms = (time.perf_counter() - t_inicio) * 1000
            total_bytes += len(chunk)

    duracao_sintese_ms = (time.perf_counter() - t_inicio) * 1000
    # PCM 16-bit = 2 bytes por amostra
    duracao_audio_ms = total_bytes / 2 / taxa * 1000

    return (ttfa_ms or duracao_sintese_ms), duracao_sintese_ms, duracao_audio_ms
