from kvoice.engine.types import Audio, AudioChunk, Capacity, SynthOptions, TTSEngine, Voice


def test_voice_defaults() -> None:
    v = Voice(id="v_ana", name="Ana")
    assert v.ref_audio is None
    assert v.ref_text is None
    assert v.style_prompt is None


def test_voice_imutavel() -> None:
    v = Voice(id="v_ana", name="Ana")
    try:
        v.id = "outro"  # type: ignore[misc]
        raise AssertionError("deveria ser imutável")
    except (AttributeError, TypeError):
        pass


def test_synth_options_defaults() -> None:
    o = SynthOptions()
    assert o.speed == 1.0
    assert o.style == "neutro"
    assert o.format == "pcm_24000"


def test_audio_chunk_campos() -> None:
    chunk = AudioChunk(data=b"\x00\x01", sample_rate=24000, duration_ms=0.042)
    assert len(chunk.data) == 2
    assert chunk.sample_rate == 24000


def test_audio_campos() -> None:
    audio = Audio(data=b"\x00" * 100, sample_rate=24000, duration_ms=2.08, ttfa_ms=142.5)
    assert audio.ttfa_ms == 142.5


def test_capacity_mutavel() -> None:
    c = Capacity(active_streams=2, queued=0, rtf_recent=0.3)
    c.active_streams = 3
    assert c.active_streams == 3


def test_tts_engine_e_protocol() -> None:
    from typing import Protocol

    assert issubclass(TTSEngine, Protocol)
