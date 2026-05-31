from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
MODELS_DIR = Path(os.getenv("ECHO_MODELS_DIR", PROJECT_ROOT / "backend" / "models"))


def _detect_profile() -> str:
    machine = platform.machine().lower()
    if platform.system().lower() == "linux" and machine in {"aarch64", "arm64", "armv7l"}:
        return "pi-fast"
    return "desktop"


DEVICE_PROFILE = os.getenv("ECHO_PROFILE", _detect_profile()).strip().lower()
PI_FAST_PROFILE = DEVICE_PROFILE in {"pi", "raspi", "raspberry-pi", "pi-fast", "raspi-fast"}


def _profile_default(desktop_value, pi_fast_value):
    return pi_fast_value if PI_FAST_PROFILE else desktop_value


DEFAULT_SYSTEM_PROMPT = (
    "You are Echo, a local voice assistant running on a Raspberry Pi. "
    "Reply in one or two short sentences. Avoid long lists unless asked."
    if PI_FAST_PROFILE
    else (
        "You are Echo, a local automotive voice assistant. "
        "Keep replies concise, conversational, and useful while driving. "
        "Ask one short follow-up only when needed."
    )
)


def _default_whisper_model() -> str:
    small = MODELS_DIR / "ggml-small.en.bin"
    return str(small if small.exists() else MODELS_DIR / "ggml-tiny.en.bin")


def _default_whisper_vad_model() -> str:
    return str(MODELS_DIR / "ggml-silero-v6.2.0.bin")


def _default_whisper_binary() -> str:
    suffix = "whisper-cli.exe" if platform.system().lower() == "windows" else "whisper-cli"
    candidates = [
        PROJECT_ROOT / "backend" / "bin" / "whisper" / "whisper-cli.exe",
        PROJECT_ROOT / "backend" / "bin" / "whisper" / "Release" / "whisper-cli.exe",
        PROJECT_ROOT / "backend" / "bin" / "whisper" / "whisper-cli",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return suffix


def _default_piper_model() -> str:
    return str(MODELS_DIR / "piper" / "en_US-lessac-medium.onnx")


def _default_piper_config() -> str:
    return str(MODELS_DIR / "piper" / "en_US-lessac-medium.onnx.json")


def _default_piper_male_model() -> str:
    return str(MODELS_DIR / "piper" / "en_US-ryan-medium.onnx")


def _default_piper_male_config() -> str:
    return str(MODELS_DIR / "piper" / "en_US-ryan-medium.onnx.json")


def _default_piper_binary() -> str:
    suffix = "piper.exe" if platform.system().lower() == "windows" else "piper"
    candidates = [
        PROJECT_ROOT / "backend" / "bin" / "piper" / "piper.exe",
        PROJECT_ROOT / "backend" / "bin" / "piper" / "piper" / "piper.exe",
        PROJECT_ROOT / "backend" / "bin" / "piper" / "piper",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return suffix


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


@dataclass(frozen=True)
class Settings:
    profile: str = DEVICE_PROFILE

    sample_rate: int = _env_int("ECHO_SAMPLE_RATE", 16000)
    frame_samples: int = _env_int("ECHO_FRAME_SAMPLES", 512)
    channels: int = 1

    wake_phrase: str = os.getenv("ECHO_WAKE_PHRASE", "Hey Jarvis")
    wake_model_name: str = os.getenv("ECHO_WAKE_MODEL_NAME", "hey_jarvis")
    wake_model_path: str | None = os.getenv("ECHO_WAKE_MODEL") or None
    wake_threshold: float = _env_float("ECHO_WAKE_THRESHOLD", 0.5)
    wake_frame_samples: int = _env_int("ECHO_WAKE_FRAME_SAMPLES", 1280)

    endpoint_rms_threshold: float = _env_float("ECHO_ENDPOINT_RMS_THRESHOLD", _profile_default(0.012, 0.016))
    endpoint_min_speech_ms: int = _env_int("ECHO_ENDPOINT_MIN_SPEECH_MS", _profile_default(120, 120))
    vad_threshold: float = _env_float("ECHO_VAD_THRESHOLD", 0.5)
    vad_min_silence_ms: int = _env_int("ECHO_VAD_MIN_SILENCE_MS", _profile_default(650, 480))
    vad_speech_pad_ms: int = _env_int("ECHO_VAD_SPEECH_PAD_MS", _profile_default(200, 120))
    vad_preroll_ms: int = _env_int("ECHO_VAD_PREROLL_MS", _profile_default(240, 180))
    vad_max_seconds: float = _env_float("ECHO_VAD_MAX_SECONDS", _profile_default(8.0, 5.5))
    wake_listen_timeout_seconds: float = _env_float("ECHO_WAKE_LISTEN_TIMEOUT", _profile_default(7.0, 5.5))

    whisper_binary: str = os.getenv("ECHO_WHISPER_CPP_BIN", os.getenv("ECHO_WHISPER_BIN", _default_whisper_binary()))
    stt_model: str = os.getenv("ECHO_WHISPER_MODEL", os.getenv("ECHO_STT_MODEL", _default_whisper_model()))
    whisper_language: str = os.getenv("ECHO_WHISPER_LANG", "en")
    whisper_threads: int = _env_int("ECHO_WHISPER_THREADS", _profile_default(0, 4))
    whisper_no_context: bool = _env_bool("ECHO_WHISPER_NO_CONTEXT", True)
    whisper_vad: bool = _env_bool("ECHO_WHISPER_VAD", True)
    whisper_vad_model: str = os.getenv(
        "ECHO_WHISPER_VAD_MODEL",
        os.getenv("ECHO_VAD_MODEL", _default_whisper_vad_model()),
    )
    whisper_vad_min_speech_ms: int = _env_int("ECHO_WHISPER_VAD_MIN_SPEECH_MS", 120)
    whisper_timeout_seconds: float = _env_float("ECHO_WHISPER_TIMEOUT", _profile_default(18.0, 12.0))

    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    ollama_chat_url: str = os.getenv("OLLAMA_CHAT_URL", "http://localhost:11434/api/chat")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
    # Tool-capable model used for command/intent decisions AND conversational
    # answers. 3B keeps latency low while still doing reliable tool calls.
    ollama_tool_model: str = os.getenv("OLLAMA_TOOL_MODEL", "qwen2.5:1.5b")
    llm_temperature: float = _env_float("ECHO_LLM_TEMPERATURE", 0.35)
    llm_num_predict: int = _env_int("ECHO_LLM_NUM_PREDICT", _profile_default(160, 72))
    llm_tts_flush_chars: int = _env_int("ECHO_LLM_TTS_FLUSH_CHARS", _profile_default(80, 60))
    ollama_keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", _profile_default("30m", "1h"))
    ollama_num_ctx: int | None = _env_int("OLLAMA_NUM_CTX", _profile_default(0, 1024)) or None
    ollama_num_thread: int | None = _env_int("OLLAMA_NUM_THREAD", _profile_default(0, 4)) or None
    system_prompt: str = os.getenv("ECHO_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)

    piper_binary: str = os.getenv("ECHO_PIPER_BIN", _default_piper_binary())
    piper_model: str = os.getenv("ECHO_PIPER_MODEL", os.getenv("ECHO_TTS_MODEL", _default_piper_model()))
    piper_config: str | None = os.getenv("ECHO_PIPER_CONFIG", _default_piper_config()) or None
    piper_speaker: str | None = os.getenv("ECHO_PIPER_SPEAKER") or None
    piper_noise_scale: float | None = (
        _env_float("ECHO_PIPER_NOISE_SCALE", 0.0) if os.getenv("ECHO_PIPER_NOISE_SCALE") else None
    )
    piper_noise_w: float | None = _env_float("ECHO_PIPER_NOISE_W", 0.0) if os.getenv("ECHO_PIPER_NOISE_W") else None
    tts_model: str = piper_model
    tts_voice: str = os.getenv("ECHO_TTS_VOICE", piper_speaker or "default")
    tts_language: str = os.getenv("ECHO_TTS_LANG", "en")
    tts_steps: int = _env_int("ECHO_TTS_STEPS", 1)
    tts_speed: float = _env_float("ECHO_TTS_SPEED", _profile_default(1.08, 1.14))
    tts_max_chunk_length: int = _env_int("ECHO_TTS_MAX_CHUNK_LENGTH", _profile_default(110, 90))
    tts_silence_duration: float = _env_float("ECHO_TTS_SILENCE_DURATION", _profile_default(0.08, 0.03))
    piper_timeout_seconds: float = _env_float("ECHO_PIPER_TIMEOUT", _profile_default(18.0, 12.0))

    # Male/female Piper voices (female defaults to the existing model).
    piper_model_female: str = os.getenv("ECHO_PIPER_MODEL_FEMALE", _default_piper_model())
    piper_config_female: str = os.getenv("ECHO_PIPER_CONFIG_FEMALE", _default_piper_config())
    piper_model_male: str = os.getenv("ECHO_PIPER_MODEL_MALE", _default_piper_male_model())
    piper_config_male: str = os.getenv("ECHO_PIPER_CONFIG_MALE", _default_piper_male_config())
    voice_profile: str = os.getenv("ECHO_VOICE_PROFILE", "female")

    # Command / car-assistant settings.
    contacts_path: str = os.getenv("ECHO_CONTACTS", str(PROJECT_ROOT / "contacts.json"))
    car_info_path: str = os.getenv("ECHO_CAR_INFO", str(PROJECT_ROOT / "car_info.md"))
    default_city: str = os.getenv("ECHO_DEFAULT_CITY", "Pune")
    radio_stream_url: str = os.getenv("ECHO_RADIO_URL", "")
    commands_enabled: bool = _env_bool("ECHO_COMMANDS_ENABLED", True)

    # Premium-feel settings.
    greeting_text: str = os.getenv("ECHO_GREETING", "Hi, how can I help?")
    wake_greeting: bool = _env_bool("ECHO_WAKE_GREETING", True)
    history_turns: int = _env_int("ECHO_HISTORY_TURNS", 6)
    friendly_error: str = os.getenv(
        "ECHO_FRIENDLY_ERROR", "Sorry, I couldn't do that right now."
    )

    allow_text_bypass: bool = _env_bool("ECHO_ALLOW_TEXT_BYPASS", True)
    realtime_preload: bool = _env_bool("ECHO_REALTIME_PRELOAD", True)


settings = Settings()
