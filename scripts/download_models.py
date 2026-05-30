from __future__ import annotations

import importlib
import os
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import MODELS_DIR, settings


WHISPER_MODEL_URL = os.getenv(
    "ECHO_WHISPER_MODEL_URL",
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin",
)
WHISPER_VAD_MODEL_URL = os.getenv(
    "ECHO_WHISPER_VAD_MODEL_URL",
    "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin",
)
PIPER_MODEL_URL = os.getenv(
    "ECHO_PIPER_MODEL_URL",
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
)
PIPER_CONFIG_URL = os.getenv(
    "ECHO_PIPER_CONFIG_URL",
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
)


def run_step(name: str, func) -> None:
    print(f"[setup] {name}")
    try:
        func()
    except Exception as exc:
        print(f"[setup] skipped {name}: {exc}")


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        print(f"[setup] exists {destination}")
        return
    print(f"[setup] downloading {url}")
    urllib.request.urlretrieve(url, destination)


def download_openwakeword() -> None:
    utils = importlib.import_module("openwakeword.utils")
    utils.download_models()


def download_whisper_models() -> None:
    download_file(WHISPER_MODEL_URL, MODELS_DIR / "ggml-tiny.en.bin")
    download_file(WHISPER_VAD_MODEL_URL, MODELS_DIR / "ggml-silero-v6.2.0.bin")


def download_piper_voice() -> None:
    voice_dir = MODELS_DIR / "piper"
    download_file(PIPER_MODEL_URL, voice_dir / "en_US-lessac-medium.onnx")
    download_file(PIPER_CONFIG_URL, voice_dir / "en_US-lessac-medium.onnx.json")


def check_binaries() -> None:
    whisper = os.getenv("ECHO_WHISPER_CPP_BIN", settings.whisper_binary)
    piper = os.getenv("ECHO_PIPER_BIN", settings.piper_binary)
    if not shutil.which(whisper) and not Path(whisper).exists():
        print("[setup] whisper-cli not found; set ECHO_WHISPER_CPP_BIN before running the server.")
    if not shutil.which(piper) and not Path(piper).exists():
        print("[setup] piper not found; set ECHO_PIPER_BIN before running the server.")


def main() -> int:
    run_step("OpenWakeWord models", download_openwakeword)
    run_step("whisper.cpp STT and VAD models", download_whisper_models)
    run_step("Piper default voice", download_piper_voice)
    run_step("external binaries", check_binaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
