from __future__ import annotations

import io
import wave

import numpy as np


def pcm16_bytes_to_int16(data: bytes) -> np.ndarray:
    if len(data) % 2:
        data = data[:-1]
    return np.frombuffer(data, dtype=np.int16)


def pcm16_bytes_to_float32(data: bytes) -> np.ndarray:
    return pcm16_bytes_to_int16(data).astype(np.float32) / 32768.0


def float32_to_pcm16(audio: np.ndarray) -> np.ndarray:
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def float32_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    samples = np.asarray(audio, dtype=np.float32).squeeze()
    pcm = float32_to_pcm16(samples)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return buffer.getvalue()


def pcm16_bytes_to_wav_bytes(data: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(data)
    return buffer.getvalue()


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))

