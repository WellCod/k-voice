"""
Adaptador para faster-qwen3-tts (Qwen3-TTS com CUDA graphs).

Instalar: uv pip install faster-qwen3-tts
Requer: GPU NVIDIA com CUDA, PyTorch >= 2.5

APIs verificadas em faster-qwen3-tts 0.4.x (out/2026):
  FasterQwen3TTS.from_pretrained(model_id) -> model
  model.generate_voice_clone(text, language, ref_audio, ref_text) -> (chunks, sr)
  model.generate_voice_design(text, language, instruct) -> (chunks, sr)
"""

from __future__ import annotations

import time

import numpy as np

from bench.motores.base import ResultadoSintese

# Instrução padrão de voz para generate_voice_design quando não há referência.
# Ajustar conforme a voz-alvo do teste cego.
_INSTRUCAO_PADRAO = (
    "Voz feminina, adulta, tom neutro e profissional, dicção clara, português brasileiro."
)


class QwenMotor:
    nome = "qwen3-tts-0.6b"
    taxa_amostragem = 24_000

    def __init__(
        self,
        modelo_id: str = "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        instrucao_voz: str = _INSTRUCAO_PADRAO,
        ref_audio: str | None = None,
        ref_texto: str | None = None,
    ) -> None:
        self._modelo_id = modelo_id
        self._instrucao_voz = instrucao_voz
        self._ref_audio = ref_audio
        self._ref_texto = ref_texto
        self._modelo: object = None

    def carregar(self) -> None:
        from faster_qwen3_tts import FasterQwen3TTS  # type: ignore[import-untyped]

        self._modelo = FasterQwen3TTS.from_pretrained(self._modelo_id)

    def sintetizar(self, texto: str, frase_id: str) -> ResultadoSintese:
        if self._modelo is None:
            raise RuntimeError("Chame carregar() antes de sintetizar()")

        inicio = time.perf_counter()

        if self._ref_audio and self._ref_texto:
            chunks, sr = self._modelo.generate_voice_clone(  # type: ignore[union-attr]
                text=texto,
                language="Portuguese",
                ref_audio=self._ref_audio,
                ref_text=self._ref_texto,
            )
        else:
            chunks, sr = self._modelo.generate_voice_design(  # type: ignore[union-attr]
                text=texto,
                language="Portuguese",
                instruct=self._instrucao_voz,
            )

        duracao_ms = (time.perf_counter() - inicio) * 1000

        audio = np.concatenate(chunks).astype(np.float32)
        if audio.max() > 1.0 or audio.min() < -1.0:
            audio = audio / 32768.0

        return ResultadoSintese(
            audio=audio,
            taxa_amostragem=int(sr),
            duracao_sintese_ms=duracao_ms,
            motor=self.nome,
            frase_id=frase_id,
        )

    def descarregar(self) -> None:
        self._modelo = None
