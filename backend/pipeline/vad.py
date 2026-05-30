from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from backend.config import Settings
from backend.pipeline.audio import pcm16_bytes_to_float32, rms


@dataclass(frozen=True)
class VadEvent:
    speech_started: bool = False
    speech_ended: bool = False
    audio: np.ndarray | None = None


class WhisperCppVadGate:
    """Low-cost endpointing before whisper.cpp performs model-based VAD."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._collecting = False
        self._frames: list[np.ndarray] = []
        self._preroll: deque[np.ndarray] = deque(maxlen=self._frame_count(settings.vad_preroll_ms))
        self._speech_samples = 0
        self._silence_samples = 0
        self._voiced_samples = 0

    def _frame_count(self, duration_ms: int) -> int:
        samples = int(self.settings.sample_rate * duration_ms / 1000)
        return max(1, samples // self.settings.frame_samples)

    def warm_up(self) -> None:
        return

    def reset(self) -> None:
        self._collecting = False
        self._frames = []
        self._preroll.clear()
        self._speech_samples = 0
        self._silence_samples = 0
        self._voiced_samples = 0

    def accept(self, pcm_bytes: bytes) -> VadEvent:
        frame = pcm16_bytes_to_float32(pcm_bytes)
        self._preroll.append(frame)

        is_voiced = rms(frame) >= self.settings.endpoint_rms_threshold
        frame_samples = frame.size

        if not self._collecting:
            if is_voiced:
                self._voiced_samples += frame_samples
            else:
                self._voiced_samples = 0

            min_speech_samples = int(self.settings.sample_rate * self.settings.endpoint_min_speech_ms / 1000)
            if self._voiced_samples >= min_speech_samples:
                self._collecting = True
                self._frames = list(self._preroll)
                self._speech_samples = sum(part.size for part in self._frames)
                self._silence_samples = 0
                return VadEvent(speech_started=True)
            return VadEvent()

        self._frames.append(frame)
        self._speech_samples += frame_samples

        if is_voiced:
            self._silence_samples = 0
        else:
            self._silence_samples += frame_samples

        max_samples = int(self.settings.vad_max_seconds * self.settings.sample_rate)
        min_silence_samples = int(self.settings.vad_min_silence_ms * self.settings.sample_rate / 1000)
        if self._silence_samples >= min_silence_samples or self._speech_samples >= max_samples:
            audio = np.concatenate(self._frames) if self._frames else np.empty(0)
            self._collecting = False
            self._frames = []
            self._speech_samples = 0
            self._silence_samples = 0
            self._voiced_samples = 0
            return VadEvent(speech_ended=True, audio=audio)

        return VadEvent()
