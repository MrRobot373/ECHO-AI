from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from io import BytesIO
from pathlib import Path
from threading import Lock

from backend.config import Settings
from backend.pipeline.errors import ComponentUnavailable


class PiperTts:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._binary: str | None = None
        self._load_error: str | None = None
        self._load_lock = Lock()
        self._synthesis_lock = Lock()
        self._model_path = settings.piper_model
        self._config_path = settings.piper_config
        self.set_voice_profile(getattr(settings, "voice_profile", "female"))

    def set_voice_profile(self, profile: str) -> None:
        """Switch the active Piper voice between 'female' and 'male'."""
        if str(profile).lower() == "male":
            self._model_path = self.settings.piper_model_male
            self._config_path = self.settings.piper_config_male
        else:
            self._model_path = self.settings.piper_model_female
            self._config_path = self.settings.piper_config_female

    def _resolve_binary(self) -> str:
        configured = self.settings.piper_binary.strip()
        configured_path = Path(configured)
        if configured_path.exists():
            return str(configured_path)

        found = shutil.which(configured)
        if found:
            return found

        for candidate in ("piper.exe", "piper"):
            found = shutil.which(candidate)
            if found:
                return found

        raise ComponentUnavailable(
            "Piper was not found. Set ECHO_PIPER_BIN to piper.exe or add piper to PATH."
        )

    def _ensure_ready(self) -> None:
        if self._binary is not None:
            return
        with self._load_lock:
            if self._binary is not None:
                return
            if self._load_error:
                raise ComponentUnavailable(self._load_error)

            try:
                binary = self._resolve_binary()
                model_path = Path(self._model_path)
                if not model_path.exists():
                    raise ComponentUnavailable(
                        f"Piper model was not found: {model_path}. Set ECHO_PIPER_MODEL to a .onnx voice."
                    )

                config_path = Path(self._config_path) if self._config_path else None
                if config_path and not config_path.exists():
                    raise ComponentUnavailable(
                        f"Piper config was not found: {config_path}. Set ECHO_PIPER_CONFIG to the model .json."
                    )

                self._binary = binary
            except ComponentUnavailable as exc:
                self._load_error = str(exc)
                raise

    def warm_up(self) -> None:
        self._ensure_ready()

    @property
    def available_voices(self) -> list[str]:
        return ["female", "male"]

    @property
    def available_languages(self) -> list[str]:
        return [self.settings.tts_language]

    def _build_command(self, output_path: Path, *, voice: str | None, speed: float | None) -> list[str]:
        self._ensure_ready()
        assert self._binary is not None

        if not Path(self._model_path).exists():
            raise ComponentUnavailable(
                f"Piper voice not found: {self._model_path}. "
                "Download the male/female voice or run scripts/setup_windows.ps1."
            )

        command = [
            self._binary,
            "--model",
            self._model_path,
            "--output_file",
            str(output_path),
        ]

        if self._config_path:
            command.extend(["--config", self._config_path])

        speaker = self.settings.piper_speaker
        if voice and voice != "default":
            speaker = voice
        if speaker:
            command.extend(["--speaker", str(speaker)])

        effective_speed = speed if speed is not None else self.settings.tts_speed
        if effective_speed > 0:
            command.extend(["--length_scale", f"{1.0 / effective_speed:.3f}"])

        if self.settings.piper_noise_scale is not None:
            command.extend(["--noise_scale", str(self.settings.piper_noise_scale)])
        if self.settings.piper_noise_w is not None:
            command.extend(["--noise_w", str(self.settings.piper_noise_w)])

        return command

    def synthesize_wav(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
        total_steps: int | None = None,
        speed: float | None = None,
        max_chunk_length: int | None = None,
        silence_duration: float | None = None,
    ) -> tuple[bytes, int, float]:
        self._ensure_ready()
        del language, total_steps, max_chunk_length, silence_duration

        with self._synthesis_lock:
            with tempfile.TemporaryDirectory(prefix="echo-piper-") as temp_dir:
                output_path = Path(temp_dir) / "speech.wav"
                completed = subprocess.run(
                    self._build_command(output_path, voice=voice, speed=speed),
                    input=text.strip() + "\n",
                    capture_output=True,
                    text=True,
                    timeout=self.settings.piper_timeout_seconds,
                    check=False,
                )
                if completed.returncode != 0:
                    detail = (completed.stderr or completed.stdout).strip()
                    if len(detail) > 700:
                        detail = detail[-700:]
                    raise ComponentUnavailable(f"Piper synthesis failed: {detail}")
                if not output_path.exists():
                    raise ComponentUnavailable("Piper did not produce a WAV file.")

                wav_bytes = output_path.read_bytes()

        sample_rate, duration_seconds = self._inspect_wav(wav_bytes)
        return wav_bytes, sample_rate, duration_seconds

    def _inspect_wav(self, wav_bytes: bytes) -> tuple[int, float]:
        with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
        duration = frame_count / sample_rate if sample_rate else 0.0
        return sample_rate, duration
