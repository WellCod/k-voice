"""
Adaptador para ElevenLabs (referência do teste cego).

Instalar: uv pip install elevenlabs  (já incluso no grupo bench)
Requer: variável de ambiente ELEVENLABS_API_KEY

APIs verificadas em elevenlabs 1.x (out/2026):
  ElevenLabs(api_key) -> client
  client.text_to_speech.convert(text, voice_id, model_id, output_format) -> bytes
    output_format='pcm_24000' -> PCM 16-bit signed, 24 kHz, mono

Vozes usadas como referência (inventário em docs/paridade-elevenlabs.md):
  Configurar via --voz-elevenlabs na CLI do benchmark.
"""

from __future__ import annotations

import os
import time

import numpy as np

from bench.motores.base import ResultadoSintese

_TAXA = 24_000
_FORMATO_PCM = "pcm_24000"


class ElevenLabsMotor:
    nome = "elevenlabs"
    taxa_amostragem = _TAXA

    def __init__(
        self,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",  # Rachel — multilingual
        model_id: str = "eleven_flash_v2_5",
        api_key: str | None = None,
    ) -> None:
        self._voice_id = voice_id
        self._model_id = model_id
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._client: object = None

    def carregar(self) -> None:
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY não definida")
        from elevenlabs.client import ElevenLabs  # type: ignore[import-untyped]

        self._client = ElevenLabs(api_key=self._api_key)

    def sintetizar(self, texto: str, frase_id: str) -> ResultadoSintese:
        if self._client is None:
            raise RuntimeError("Chame carregar() antes de sintetizar()")

        inicio = time.perf_counter()

        pcm_bytes = b"".join(
            self._client.text_to_speech.convert(  # type: ignore[union-attr]
                text=texto,
                voice_id=self._voice_id,
                model_id=self._model_id,
                output_format=_FORMATO_PCM,
            )
        )
        duracao_ms = (time.perf_counter() - inicio) * 1000

        # PCM 16-bit signed little-endian → float32 normalizado em [-1, 1]
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        return ResultadoSintese(
            audio=audio,
            taxa_amostragem=self.taxa_amostragem,
            duracao_sintese_ms=duracao_ms,
            motor=self.nome,
            frase_id=frase_id,
        )

    def descarregar(self) -> None:
        self._client = None
