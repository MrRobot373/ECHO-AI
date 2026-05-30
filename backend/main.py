from __future__ import annotations

import importlib.util
import asyncio
import json
import shutil
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import FRONTEND_DIR, settings
from backend.pipeline.orchestrator import VoiceOrchestrator, get_shared_components


app = FastAPI(title="Echo AI", version="0.1.0")


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _has_binary_or_path(value: str) -> bool:
    path = Path(value)
    return path.exists() or shutil.which(value) is not None


def _has_file(value: str | None) -> bool:
    return bool(value) and Path(value).exists()


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "profile": settings.profile,
        "sample_rate": settings.sample_rate,
        "frame_samples": settings.frame_samples,
        "wake_phrase": settings.wake_phrase,
        "wake_model": settings.wake_model_name,
        "ollama": {
            "model": settings.ollama_model,
            "num_predict": settings.llm_num_predict,
            "num_ctx": settings.ollama_num_ctx,
            "num_thread": settings.ollama_num_thread,
            "keep_alive": settings.ollama_keep_alive,
        },
        "ollama_model": settings.ollama_model,
        "stt": {
            "engine": "whisper.cpp",
            "binary": settings.whisper_binary,
            "binary_found": _has_binary_or_path(settings.whisper_binary),
            "model": settings.stt_model,
            "model_found": _has_file(settings.stt_model),
            "language": settings.whisper_language,
            "vad": settings.whisper_vad,
            "vad_model": settings.whisper_vad_model,
            "vad_model_found": _has_file(settings.whisper_vad_model),
        },
        "tts": {
            "engine": "piper",
            "binary": settings.piper_binary,
            "binary_found": _has_binary_or_path(settings.piper_binary),
            "model": settings.piper_model,
            "model_found": _has_file(settings.piper_model),
            "config": settings.piper_config,
            "config_found": _has_file(settings.piper_config),
            "voice": settings.tts_voice,
            "language": settings.tts_language,
            "speed": settings.tts_speed,
            "max_chunk_length": settings.tts_max_chunk_length,
            "silence_duration": settings.tts_silence_duration,
        },
        "components": {
            "openwakeword": _has_module("openwakeword"),
            "whisper_cpp": _has_binary_or_path(settings.whisper_binary),
            "whisper_model": _has_file(settings.stt_model),
            "whisper_vad_model": _has_file(settings.whisper_vad_model),
            "piper": _has_binary_or_path(settings.piper_binary),
            "piper_model": _has_file(settings.piper_model),
        },
    }


@app.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send_event(event: dict) -> None:
        async with send_lock:
            await websocket.send_json(event)

    orchestrator = VoiceOrchestrator(settings, send_event, get_shared_components(settings))
    await orchestrator.start()

    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await orchestrator.accept_audio(message["bytes"])
            elif message.get("text") is not None:
                try:
                    payload = json.loads(message["text"])
                except json.JSONDecodeError:
                    payload = {"type": "text", "text": message["text"]}
                await orchestrator.handle_control(payload)
            elif message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await orchestrator.close()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
