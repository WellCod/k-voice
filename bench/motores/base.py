from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass
class ResultadoSintese:
    audio: npt.NDArray[np.float32]  # float32 normalizado em [-1, 1]
    taxa_amostragem: int
    duracao_sintese_ms: float
    motor: str
    frase_id: str

    @property
    def duracao_audio_ms(self) -> float:
        return len(self.audio) / self.taxa_amostragem * 1000

    @property
    def rtf(self) -> float:
        """Real-time factor: < 1 significa mais rápido que o tempo real."""
        return self.duracao_sintese_ms / max(self.duracao_audio_ms, 1.0)
