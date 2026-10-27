"""Plugin LiveKit Agents para o k-voice TTS."""

from __future__ import annotations

from kvoice.livekit.tts import TTS, ChunkedStream, SynthesizeStream

__all__ = ["TTS", "ChunkedStream", "SynthesizeStream", "create_tts"]


def create_tts(
    *,
    base_url: str = "ws://localhost:8000",
    token: str,
    voice_id: str,
    elevenlabs_api_key: str | None = None,
    elevenlabs_voice_id: str | None = None,
) -> object:
    """Cria TTS com fallback opcional para ElevenLabs via FallbackAdapter.

    Se elevenlabs_api_key e elevenlabs_voice_id forem fornecidos, retorna
    FallbackAdapter([k-voice, ElevenLabs]); caso contrário retorna o TTS
    k-voice direto.

    Requer livekit-plugins-elevenlabs instalado para o fallback.
    """
    from livekit.agents import tts as agents_tts  # type: ignore[import-untyped]

    kvoice: TTS = TTS(base_url=base_url, token=token, voice_id=voice_id)

    if elevenlabs_api_key and elevenlabs_voice_id:
        from livekit.plugins.elevenlabs import TTS as ElevenLabsTTS  # type: ignore[import-untyped]

        eleven = ElevenLabsTTS(
            api_key=elevenlabs_api_key,
            voice_id=elevenlabs_voice_id,
        )
        return agents_tts.FallbackAdapter([kvoice, eleven])

    return kvoice
