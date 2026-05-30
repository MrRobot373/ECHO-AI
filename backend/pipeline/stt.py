from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from threading import Lock

import numpy as np

from backend.config import Settings
from backend.pipeline.audio import float32_to_wav_bytes
from backend.pipeline.errors import ComponentUnavailable


_TIMESTAMP_RE = re.compile(r"\[[^\]]*-->\s*[^\]]*\]")
_WHITESPACE_RE = re.compile(r"\s+")


class WhisperCppStt:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._binary: str | None = None
        self._load_error: str | None = None
        self._load_lock = Lock()

    def _resolve_binary(self) -> str:
        configured = self.settings.whisper_binary.strip()
        configured_path = Path(configured)
        if configured_path.exists():
            return str(configured_path)

        found = shutil.which(configured)
        if found:
            return found

        for candidate in ("whisper-cli.exe", "main.exe", "whisper-cli", "main"):
            found = shutil.which(candidate)
            if found:
                return found

        raise ComponentUnavailable(
            "whisper.cpp was not found. Set ECHO_WHISPER_CPP_BIN to whisper-cli.exe "
            "or add whisper-cli to PATH."
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
                model_path = Path(self.settings.stt_model)
                if not model_path.exists():
                    raise ComponentUnavailable(
                        f"whisper.cpp model was not found: {model_path}. "
                        "Set ECHO_WHISPER_MODEL to a ggml Whisper model."
                    )

                if self.settings.whisper_vad:
                    vad_model = Path(self.settings.whisper_vad_model)
                    if not vad_model.exists():
                        raise ComponentUnavailable(
                            f"whisper.cpp VAD model was not found: {vad_model}. "
                            "Set ECHO_WHISPER_VAD_MODEL or disable ECHO_WHISPER_VAD=0."
                        )

                self._binary = binary
            except ComponentUnavailable as exc:
                self._load_error = str(exc)
                raise

    def warm_up(self) -> None:
        self._ensure_ready()

    def _build_command(self, wav_path: Path, output_prefix: Path, *, use_vad: bool) -> list[str]:
        self._ensure_ready()
        assert self._binary is not None

        command = [
            self._binary,
            "-m",
            self.settings.stt_model,
            "-f",
            str(wav_path),
            "-otxt",
            "-of",
            str(output_prefix),
            "-nt",
            "-l",
            self.settings.whisper_language,
        ]

        if self.settings.whisper_threads > 0:
            command.extend(["-t", str(self.settings.whisper_threads)])

        if self.settings.whisper_no_context:
            command.extend(["-mc", "0"])

        if use_vad:
            command.extend(
                [
                    "--vad",
                    "-vm",
                    self.settings.whisper_vad_model,
                    "--vad-threshold",
                    str(self.settings.vad_threshold),
                    "--vad-min-speech-duration-ms",
                    str(self.settings.whisper_vad_min_speech_ms),
                    "--vad-min-silence-duration-ms",
                    str(self.settings.vad_min_silence_ms),
                    "--vad-speech-pad-ms",
                    str(self.settings.vad_speech_pad_ms),
                ]
            )

        return command

    def transcribe(self, audio: np.ndarray) -> str:
        self._ensure_ready()
        samples = np.asarray(audio, dtype=np.float32).squeeze()
        if samples.size < int(self.settings.sample_rate * 0.08):
            return ""

        text = self._transcribe_once(samples, use_vad=self.settings.whisper_vad)
        if text or not self.settings.whisper_vad:
            return text
        return self._transcribe_once(samples, use_vad=False)

    def _transcribe_once(self, samples: np.ndarray, *, use_vad: bool) -> str:
        with tempfile.TemporaryDirectory(prefix="echo-whisper-") as temp_dir:
            temp_path = Path(temp_dir)
            wav_path = temp_path / "input.wav"
            output_prefix = temp_path / "transcript"
            wav_path.write_bytes(float32_to_wav_bytes(samples, self.settings.sample_rate))

            completed = subprocess.run(
                self._build_command(wav_path, output_prefix, use_vad=use_vad),
                capture_output=True,
                text=True,
                timeout=self.settings.whisper_timeout_seconds,
                check=False,
            )

            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                if len(detail) > 700:
                    detail = detail[-700:]
                raise ComponentUnavailable(f"whisper.cpp transcription failed: {detail}")

            txt_path = output_prefix.with_suffix(".txt")
            if txt_path.exists():
                raw_text = txt_path.read_text(encoding="utf-8", errors="ignore")
            else:
                if "unknown argument" in completed.stderr or "usage:" in completed.stderr:
                    detail = completed.stderr.strip()
                    if len(detail) > 700:
                        detail = detail[:700]
                    raise ComponentUnavailable(f"whisper.cpp command failed: {detail}")
                raw_text = completed.stdout

        return self._clean_text(raw_text)

    def _clean_text(self, raw_text: str) -> str:
        text = _TIMESTAMP_RE.sub(" ", raw_text)
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("whisper_") or stripped.startswith("system_info:"):
                continue
            lines.append(stripped)
        return _WHITESPACE_RE.sub(" ", " ".join(lines)).strip()
