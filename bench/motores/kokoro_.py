"""
Adaptador para kokoro (TTS leve, roda em CPU).

Instalar: uv pip install kokoro
Requer: espeak-ng instalado no sistema para G2P

APIs verificadas em kokoro 0.9.x (out/2026):
  KPipeline(lang_code='p') -> pipeline  ('p' = português brasileiro)
  pipeline(text, voice, speed) -> generator de (graphemes, phonemes, audio_np)

Vozes pt-BR disponíveis (verificar com list(KPipeline.list_voices()) na versão instalada):
  pf_dora  — feminina
  pm_santa — masculino
"""

from __future__ import annotations

import time

import numpy as np

from bench.motores.base import ResultadoSintese


class KokoroMotor:
    nome = "kokoro-82m"
    taxa_amostragem = 24_000

    def __init__(
        self,
        voz: str = "pf_dora",
        velocidade: float = 1.0,
    ) -> None:
        self._voz = voz
        self._velocidade = velocidade
        self._pipeline: object = None

    def carregar(self) -> None:
        from kokoro import KPipeline  # type: ignore[import-untyped]

        self._pipeline = KPipeline(lang_code="p")

    def sintetizar(self, texto: str, frase_id: str) -> ResultadoSintese:
        if self._pipeline is None:
            raise RuntimeError("Chame carregar() antes de sintetizar()")

        inicio = time.perf_counter()

        chunks = []
        for _, _, audio in self._pipeline(  # type: ignore[call-overload]
            texto,
            voice=self._voz,
            speed=self._velocidade,
        ):
            chunks.append(audio)

        duracao_ms = (time.perf_counter() - inicio) * 1000

        audio = np.concatenate(chunks).astype(np.float32)

        return ResultadoSintese(
            audio=audio,
            taxa_amostragem=self.taxa_amostragem,
            duracao_sintese_ms=duracao_ms,
            motor=self.nome,
            frase_id=frase_id,
        )

    def descarregar(self) -> None:
        self._pipeline = None
