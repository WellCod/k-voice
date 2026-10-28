"""
Adaptador para chatterbox-tts (Resemble AI) com finetune pt-BR.

Instalar: uv pip install chatterbox-tts torchaudio
Requer: GPU recomendada (suporta CPU com device='cpu')

APIs verificadas em chatterbox-tts 0.1.x (out/2026):
  ChatterboxTTS.from_pretrained(device) -> model
  model.generate(text, audio_prompt_path?) -> torch.Tensor (waveform)
  model.sr -> int (sample rate)
  torchaudio.save(path, wav, sr) para salvar

Modelo multilingual pt-BR: ResembleAI/Chatterbox-Multilingual-pt-br
O from_pretrained carrega automaticamente do HuggingFace Hub se o pacote
tiver suporte ao model_id; confirmar na versão instalada.
"""

from __future__ import annotations

import time

import numpy as np

from bench.motores.base import ResultadoSintese


class ChatterboxMotor:
    nome = "chatterbox-ptbr"

    def __init__(
        self,
        device: str = "cuda",
        ref_audio: str | None = None,
    ) -> None:
        self._device = device
        self._ref_audio = ref_audio
        self._modelo: object = None
        self.taxa_amostragem = 24_000  # sobrescrito após carregar()

    def carregar(self) -> None:
        from chatterbox.tts import ChatterboxTTS  # type: ignore[import-untyped]

        self._modelo = ChatterboxTTS.from_pretrained(device=self._device)
        self.taxa_amostragem = int(self._modelo.sr)  # type: ignore[union-attr]

    def sintetizar(self, texto: str, frase_id: str) -> ResultadoSintese:
        if self._modelo is None:
            raise RuntimeError("Chame carregar() antes de sintetizar()")

        inicio = time.perf_counter()

        kwargs: dict[str, object] = {"text": texto}
        if self._ref_audio:
            kwargs["audio_prompt_path"] = self._ref_audio

        wav = self._modelo.generate(**kwargs)  # type: ignore[union-attr]
        duracao_ms = (time.perf_counter() - inicio) * 1000

        # wav é um tensor PyTorch shape (1, N) ou (N,); converte para numpy float32
        audio = wav.squeeze().cpu().numpy().astype(np.float32)  # type: ignore[union-attr]

        return ResultadoSintese(
            audio=audio,
            taxa_amostragem=self.taxa_amostragem,
            duracao_sintese_ms=duracao_ms,
            motor=self.nome,
            frase_id=frase_id,
        )

    def descarregar(self) -> None:
        self._modelo = None
