from bench.motores.base import ResultadoSintese

MOTORES_DISPONIVEIS = ["qwen", "kokoro", "chatterbox", "elevenlabs"]

__all__ = ["ResultadoSintese", "MOTORES_DISPONIVEIS", "carregar_motor"]


def carregar_motor(nome: str, **kwargs: object) -> object:
    """Importa e instancia o motor pelo nome. ImportError se a dependência não estiver instalada."""
    if nome == "qwen":
        from bench.motores.qwen import QwenMotor

        return QwenMotor(**kwargs)
    if nome == "kokoro":
        from bench.motores.kokoro_ import KokoroMotor

        return KokoroMotor(**kwargs)
    if nome == "chatterbox":
        from bench.motores.chatterbox import ChatterboxMotor

        return ChatterboxMotor(**kwargs)
    if nome == "elevenlabs":
        from bench.motores.elevenlabs_ import ElevenLabsMotor

        return ElevenLabsMotor(**kwargs)
    raise ValueError(f"Motor desconhecido: {nome!r}. Disponíveis: {MOTORES_DISPONIVEIS}")
