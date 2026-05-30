from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

import numpy as np

from backend.config import Settings
from backend.pipeline.audio import pcm16_bytes_to_int16
from backend.pipeline.errors import ComponentUnavailable


@dataclass(frozen=True)
class WakeResult:
    detected: bool
    score: float
    label: str


class WakeWordDetector:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self._buffer = np.empty(0, dtype=np.int16)
        self._load_error: str | None = None
        self._load_lock = Lock()

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            if self._load_error:
                raise ComponentUnavailable(self._load_error)

            try:
                from openwakeword.model import Model
                from openwakeword import utils
            except Exception as exc:  # pragma: no cover - depends on local install
                self._load_error = (
                    "OpenWakeWord is not installed. Run scripts/setup_windows.ps1 "
                    "or install backend/requirements.txt."
                )
                raise ComponentUnavailable(self._load_error) from exc

            try:
                utils.download_models()
                if self.settings.wake_model_path:
                    self._model = Model(wakeword_models=[self.settings.wake_model_path])
                else:
                    self._model = Model()
            except Exception as exc:  # pragma: no cover - depends on model runtime
                self._load_error = f"OpenWakeWord failed to load: {exc}"
                raise ComponentUnavailable(self._load_error) from exc

    def warm_up(self) -> None:
        self._load()

    def reset(self) -> None:
        self._buffer = np.empty(0, dtype=np.int16)

    def predict(self, pcm_bytes: bytes) -> WakeResult:
        self._load()
        self._buffer = np.concatenate([self._buffer, pcm16_bytes_to_int16(pcm_bytes)])

        best_score = 0.0
        best_label = self.settings.wake_model_name
        frame_size = self.settings.wake_frame_samples

        while self._buffer.size >= frame_size:
            frame = self._buffer[:frame_size]
            self._buffer = self._buffer[frame_size:]
            predictions = self._model.predict(frame)
            label, score = self._select_score(predictions)
            if score > best_score:
                best_score = score
                best_label = label

        return WakeResult(
            detected=best_score >= self.settings.wake_threshold,
            score=best_score,
            label=best_label,
        )

    def _select_score(self, predictions: dict[str, float]) -> tuple[str, float]:
        if not predictions:
            return self.settings.wake_model_name, 0.0

        target_variants = {
            self.settings.wake_model_name,
            self.settings.wake_model_name.replace("_", " "),
            self.settings.wake_model_name.replace(" ", "_"),
        }
        normalized = {key.lower().replace("-", "_"): key for key in predictions}
        for target in target_variants:
            key = normalized.get(target.lower().replace("-", "_"))
            if key is not None:
                return key, float(predictions[key])
            target_norm = target.lower().replace("-", "_")
            for prediction_key in predictions:
                if target_norm in prediction_key.lower().replace("-", "_"):
                    return prediction_key, float(predictions[prediction_key])

        key = max(predictions, key=predictions.get)
        return key, float(predictions[key])
