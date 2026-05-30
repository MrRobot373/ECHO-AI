import numpy as np

from backend.config import Settings
from backend.pipeline.audio import float32_to_pcm16, float32_to_wav_bytes
from backend.pipeline.vad import WhisperCppVadGate


def test_float32_to_wav_bytes_has_wav_header():
    data = float32_to_wav_bytes([0.0, 0.1, -0.1], 16000)
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"


def test_endpoint_gate_returns_audio_after_silence():
    settings = Settings(
        endpoint_rms_threshold=0.01,
        endpoint_min_speech_ms=32,
        vad_min_silence_ms=64,
        vad_preroll_ms=32,
    )
    gate = WhisperCppVadGate(settings)
    voiced = float32_to_pcm16(np.full(settings.frame_samples, 0.04, dtype=np.float32)).tobytes()
    silence = float32_to_pcm16(np.zeros(settings.frame_samples, dtype=np.float32)).tobytes()

    events = [gate.accept(voiced) for _ in range(3)]
    assert any(event.speech_started for event in events)

    end = None
    for _ in range(4):
        event = gate.accept(silence)
        if event.speech_ended:
            end = event
            break

    assert end is not None
    assert end.audio is not None
    assert end.audio.size > 0
