from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import Lock

import numpy as np

from backend.commands.permissions import PermissionStore
from backend.commands.router import route as route_command
from backend.config import Settings
from backend.pipeline.errors import ComponentUnavailable
from backend.pipeline.llm import OllamaClient, pop_complete_sentences
from backend.pipeline.audio import rms
from backend.pipeline.stt import WhisperCppStt
from backend.pipeline.tts import PiperTts
from backend.pipeline.vad import WhisperCppVadGate
from backend.pipeline.wake_word import WakeWordDetector


SendEvent = Callable[[dict], Awaitable[None]]
logger = logging.getLogger(__name__)


@dataclass
class RealtimeComponents:
    wake_word: WakeWordDetector
    vad: WhisperCppVadGate
    stt: WhisperCppStt
    llm: OllamaClient
    tts: PiperTts


_shared_components: RealtimeComponents | None = None
_shared_components_lock = Lock()


def get_shared_components(settings: Settings) -> RealtimeComponents:
    global _shared_components
    with _shared_components_lock:
        if _shared_components is None:
            _shared_components = RealtimeComponents(
                wake_word=WakeWordDetector(settings),
                vad=WhisperCppVadGate(settings),
                stt=WhisperCppStt(settings),
                llm=OllamaClient(settings),
                tts=PiperTts(settings),
            )
        return _shared_components


class VoiceOrchestrator:
    def __init__(self, settings: Settings, send_event: SendEvent, components: RealtimeComponents | None = None):
        self.settings = settings
        self.send_event = send_event
        if components is None:
            components = RealtimeComponents(
                wake_word=WakeWordDetector(settings),
                vad=WhisperCppVadGate(settings),
                stt=WhisperCppStt(settings),
                llm=OllamaClient(settings),
                tts=PiperTts(settings),
            )
        self.wake_word = components.wake_word
        self.vad = components.vad
        self.stt = components.stt
        self.llm = components.llm
        self.tts = components.tts
        self.state = "starting"
        self.permissions = PermissionStore()
        self.voice_profile = settings.voice_profile
        self.history: list[dict] = []
        self._greeting_audio: tuple[bytes, int, float] | None = None
        self._greeting_mute_until = 0.0
        self.tts_voice = settings.tts_voice
        self.tts_language = settings.tts_language
        self.tts_steps = settings.tts_steps
        self.tts_speed = settings.tts_speed
        self.tts_max_chunk_length = settings.tts_max_chunk_length
        self.tts_silence_duration = settings.tts_silence_duration
        self._last_wake_update = 0.0
        self._listening_started_at = 0.0
        self._processing_task: asyncio.Task | None = None
        self._warm_task: asyncio.Task | None = None

    async def start(self) -> None:
        self.wake_word.reset()
        self.vad.reset()
        await self.send_event(
            {
                "type": "hello",
                "sample_rate": self.settings.sample_rate,
                "frame_samples": self.settings.frame_samples,
                "profile": self.settings.profile,
                "wake_phrase": self.settings.wake_phrase,
                "wake_model": self.settings.wake_model_name,
                "stt_engine": "whisper.cpp",
                "vad_engine": "whisper.cpp",
                "ollama_model": self.settings.ollama_model,
                "tts_engine": "piper",
                "tts_voice": self.tts_voice,
                "tts_language": self.tts_language,
                "tts_steps": self.tts_steps,
                "tts_speed": self.tts_speed,
            }
        )
        await self._set_state("sleeping")
        if self.settings.realtime_preload:
            self._warm_task = asyncio.create_task(self._warm_up())

    async def close(self) -> None:
        if self._warm_task and not self._warm_task.done():
            self._warm_task.cancel()
            try:
                await self._warm_task
            except asyncio.CancelledError:
                pass
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

    async def _warm_up(self) -> None:
        components = [
            ("wake_word", self.wake_word.warm_up),
            ("endpoint", self.vad.warm_up),
            ("whisper.cpp", self.stt.warm_up),
            ("piper", self.tts.warm_up),
        ]
        await self.send_event({"type": "warmup", "state": "starting"})
        try:
            for name, warm_up in components:
                await self.send_event({"type": "warmup", "state": "loading", "component": name})
                await asyncio.to_thread(warm_up)
            await self.send_event({"type": "warmup", "state": "loading", "component": "ollama"})
            await self.llm.warm_up()
            if self.settings.commands_enabled:
                await self.send_event({"type": "warmup", "state": "loading", "component": "assistant model"})
                await self.llm.warm_up_tool_model()
            await self._send_tts_config()
            if self.settings.wake_greeting:
                await asyncio.to_thread(self._build_greeting_audio)
            await self.send_event({"type": "warmup", "state": "ready"})
        except asyncio.CancelledError:
            raise
        except ComponentUnavailable as exc:
            await self.send_event({"type": "warmup", "state": "degraded", "message": str(exc)})
        except Exception as exc:
            await self.send_event({"type": "warmup", "state": "degraded", "message": f"Warm-up failed: {exc}"})

    async def handle_control(self, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "text" and self.settings.allow_text_bypass:
            text = str(message.get("text", "")).strip()
            if text:
                await self._start_processing_task(self._respond_to_text(text, from_voice=False))
        elif message_type == "reset":
            self.vad.reset()
            self.wake_word.reset()
            self.history.clear()
            await self._set_state("sleeping")
        elif message_type == "settings":
            if "permissions" in message:
                self.permissions.update(message["permissions"])
            if "voice_profile" in message:
                self._set_voice_profile(message["voice_profile"])
            if any(key in message for key in ("voice", "language", "steps", "speed")):
                await self._apply_settings(message)

    def _set_voice_profile(self, profile: str) -> None:
        profile = "male" if str(profile).lower() == "male" else "female"
        self.voice_profile = profile
        self._greeting_audio = None  # re-synthesize greeting in the new voice
        try:
            self.tts.set_voice_profile(profile)
        except Exception as exc:  # noqa: BLE001
            logger.warning("voice profile switch failed: %s", exc)

    async def accept_audio(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes or self.state in {"processing", "error"}:
            return

        try:
            if self.state == "sleeping":
                result = self.wake_word.predict(pcm_bytes)
                now = time.monotonic()
                if now - self._last_wake_update > 0.35:
                    self._last_wake_update = now
                    await self.send_event(
                        {
                            "type": "wake_level",
                            "score": round(result.score, 3),
                            "label": result.label,
                        }
                    )
                if result.detected:
                    self.vad.reset()
                    self._listening_started_at = now
                    await self.send_event(
                        {"type": "wake", "detected": True, "score": result.score, "label": result.label}
                    )
                    await self._set_state("listening")
                    if self.settings.wake_greeting:
                        await self._play_greeting()
                        self._listening_started_at = time.monotonic()
                return

            if self.state == "listening":
                # ignore mic while the greeting clip is still playing (avoid self-capture)
                if time.monotonic() < self._greeting_mute_until:
                    return
                if time.monotonic() - self._listening_started_at > self.settings.wake_listen_timeout_seconds:
                    self.vad.reset()
                    await self._set_state("sleeping")
                    return

                event = self.vad.accept(pcm_bytes)
                if event.speech_started:
                    await self.send_event({"type": "speech", "active": True})
                if event.speech_ended and event.audio is not None:
                    await self.send_event({"type": "speech", "active": False})
                    await self._start_processing_task(self._process_speech(event.audio))
        except ComponentUnavailable as exc:
            await self._component_error(str(exc))
        except Exception as exc:
            await self._component_error(f"Voice pipeline error: {exc}")

    async def _start_processing_task(self, coro) -> None:
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
        self._processing_task = asyncio.create_task(coro)

    async def _process_speech(self, audio: np.ndarray) -> None:
        await self._set_state("processing")
        try:
            duration = audio.size / self.settings.sample_rate if self.settings.sample_rate else 0.0
            level = rms(audio)
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            logger.info("speech segment captured: duration=%.2fs rms=%.4f peak=%.4f", duration, level, peak)
            text = await asyncio.to_thread(self.stt.transcribe, audio)
            if not text:
                await self.send_event(
                    {
                        "type": "notice",
                        "message": f"No speech detected. Captured {duration:.1f}s, level {level:.3f}.",
                    }
                )
                self.vad.reset()
                self._listening_started_at = time.monotonic()
                await self._set_state("listening")
                return
            logger.info("speech transcribed: chars=%d", len(text))
            await self._respond_to_text(text, from_voice=True)
        except ComponentUnavailable as exc:
            await self._component_error(str(exc))
        except Exception as exc:
            await self._component_error(f"Speech processing error: {exc}")

    async def _run_command(self, text: str) -> bool:
        """Run a command or answer conversationally. Returns True if handled."""
        spoken = await route_command(text, self.llm, self.settings, self.permissions, self.history)
        if not spoken:
            return False
        await self.send_event({"type": "assistant_start"})
        await self.send_event({"type": "transcript_delta", "role": "assistant", "text": spoken})
        for chunk in self._split_tts_text(spoken):
            await self._speak(chunk)
        await self.send_event({"type": "transcript", "role": "assistant", "text": spoken, "final": True})
        self._remember(text, spoken)
        self.vad.reset()
        self.wake_word.reset()
        await self._set_state("sleeping")
        return True

    def _remember(self, user_text: str, assistant_text: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": assistant_text})
        limit = max(0, self.settings.history_turns) * 2
        if limit and len(self.history) > limit:
            self.history = self.history[-limit:]

    def _build_greeting_audio(self) -> tuple[bytes, int, float] | None:
        """Synthesize and cache the wake greeting clip (called off the loop)."""
        try:
            self._greeting_audio = self.tts.synthesize_wav(
                self.settings.greeting_text,
                voice=self.tts_voice,
                speed=self.tts_speed,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("greeting synth skipped: %s", exc)
            self._greeting_audio = None
        return self._greeting_audio

    async def _play_greeting(self) -> None:
        text = self.settings.greeting_text
        audio = self._greeting_audio or await asyncio.to_thread(self._build_greeting_audio)
        await self.send_event({"type": "assistant_start"})
        await self.send_event({"type": "transcript", "role": "assistant", "text": text, "final": True})
        if not audio:
            return
        wav_bytes, sample_rate, duration = audio
        await self.send_event(
            {
                "type": "audio",
                "format": "wav",
                "mime": "audio/wav",
                "sample_rate": sample_rate,
                "duration": duration,
                "data": base64.b64encode(wav_bytes).decode("ascii"),
            }
        )
        self._greeting_mute_until = time.monotonic() + duration + 0.4

    async def _respond_to_text(self, text: str, from_voice: bool) -> None:
        await self._set_state("processing")
        await self.send_event({"type": "transcript", "role": "user", "text": text, "source": "voice" if from_voice else "text"})

        if self.settings.commands_enabled and await self._run_command(text):
            return

        assistant_text = ""
        sentence_buffer = ""
        tts_buffer = ""
        assistant_started = False
        tts_queue: asyncio.Queue[str | None] = asyncio.Queue()
        tts_task = asyncio.create_task(self._tts_worker(tts_queue))

        try:
            async def flush_tts_buffer(force: bool = False) -> None:
                nonlocal tts_buffer
                chunk = tts_buffer.strip()
                if chunk and (force or len(chunk) >= self.settings.llm_tts_flush_chars):
                    await tts_queue.put(chunk)
                    tts_buffer = ""

            def add_tts_text(chunk: str) -> None:
                nonlocal tts_buffer
                chunk = chunk.strip()
                if not chunk:
                    return
                tts_buffer = f"{tts_buffer} {chunk}".strip()

            async for token in self.llm.stream_response(text):
                assistant_text += token
                sentence_buffer += token
                if not assistant_started:
                    assistant_started = True
                    await self.send_event({"type": "assistant_start"})
                await self.send_event({"type": "transcript_delta", "role": "assistant", "text": token})

                sentences, sentence_buffer = pop_complete_sentences(sentence_buffer)
                for sentence in sentences:
                    add_tts_text(sentence)
                    await flush_tts_buffer()

                if len(sentence_buffer) >= self.settings.llm_tts_flush_chars and sentence_buffer[-1].isspace():
                    add_tts_text(sentence_buffer)
                    sentence_buffer = ""
                    await flush_tts_buffer(force=True)

            remaining = sentence_buffer.strip()
            if remaining:
                add_tts_text(remaining)
            await flush_tts_buffer(force=True)

            await tts_queue.put(None)
            await tts_task

            await self.send_event({"type": "transcript", "role": "assistant", "text": assistant_text.strip(), "final": True})
            self._remember(text, assistant_text.strip())
            self.vad.reset()
            self.wake_word.reset()
            await self._set_state("sleeping")
        except ComponentUnavailable as exc:
            tts_task.cancel()
            await self._component_error(str(exc))
        except Exception as exc:
            tts_task.cancel()
            await self._component_error(f"Response generation error: {exc}")

    async def _tts_worker(self, queue: asyncio.Queue[str | None]) -> None:
        while True:
            sentence = await queue.get()
            if sentence is None:
                return
            for chunk in self._split_tts_text(sentence):
                await self._speak(chunk)

    def _split_tts_text(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        max_length = max(40, self.tts_max_chunk_length)
        if len(text) <= max_length:
            return [text]

        chunks: list[str] = []
        remaining = text
        while len(remaining) > max_length:
            split_at = -1
            include_chars = 0
            for separator in (". ", "? ", "! ", ", ", " "):
                index = remaining.rfind(separator, 0, max_length)
                if index > split_at:
                    split_at = index
                    include_chars = 1 if separator != " " else 0
            if split_at < 20:
                split_at = max_length
                include_chars = 0
            cut_at = split_at + include_chars
            chunk = remaining[:cut_at].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[cut_at:].strip()
        if remaining:
            chunks.append(remaining)
        return chunks

    async def _speak(self, sentence: str) -> None:
        if not sentence.strip():
            return
        await self._set_state("speaking")
        try:
            wav_bytes, sample_rate, duration = await asyncio.to_thread(
                self.tts.synthesize_wav,
                sentence.strip(),
                voice=self.tts_voice,
                language=self.tts_language,
                total_steps=self.tts_steps,
                speed=self.tts_speed,
                max_chunk_length=self.tts_max_chunk_length,
                silence_duration=self.tts_silence_duration,
            )
        except ComponentUnavailable as exc:
            logger.warning("tts failed: %s", exc)
            return

        await self.send_event(
            {
                "type": "audio",
                "format": "wav",
                "mime": "audio/wav",
                "sample_rate": sample_rate,
                "duration": duration,
                "data": base64.b64encode(wav_bytes).decode("ascii"),
            }
        )

    async def _apply_settings(self, message: dict) -> None:
        try:
            voices = await asyncio.to_thread(lambda: self.tts.available_voices)
            languages = await asyncio.to_thread(lambda: self.tts.available_languages)
        except ComponentUnavailable as exc:
            await self.send_event({"type": "error", "message": str(exc)})
            return

        voice = str(message.get("voice", self.tts_voice)).strip()
        if voice:
            if voice not in voices:
                await self.send_event({"type": "error", "message": f"Unknown voice: {voice}"})
                return
            self.tts_voice = voice

        language = str(message.get("language", self.tts_language)).strip().lower()
        if language:
            if language not in languages:
                await self.send_event({"type": "error", "message": f"Unsupported TTS language: {language}"})
                return
            self.tts_language = language

        if "steps" in message:
            self.tts_steps = min(100, max(1, int(message["steps"])))
        if "speed" in message:
            self.tts_speed = min(2.0, max(0.7, float(message["speed"])))

        await self._send_tts_config(voices=voices, languages=languages)

    async def _send_tts_config(self, voices: list[str] | None = None, languages: list[str] | None = None) -> None:
        if voices is None:
            voices = await asyncio.to_thread(lambda: self.tts.available_voices)
        if languages is None:
            languages = await asyncio.to_thread(lambda: self.tts.available_languages)
        await self.send_event(
            {
                "type": "tts_config",
                "engine": "piper",
                "voices": voices,
                "languages": languages,
                "voice": self.tts_voice,
                "language": self.tts_language,
                "steps": self.tts_steps,
                "speed": self.tts_speed,
                "max_chunk_length": self.tts_max_chunk_length,
                "silence_duration": self.tts_silence_duration,
            }
        )

    async def _set_state(self, state: str) -> None:
        if self.state != state:
            self.state = state
            await self.send_event({"type": "state", "state": state})

    async def _component_error(self, message: str) -> None:
        # Log the real cause; show the user a calm, friendly line. Then recover
        # to sleeping so the assistant stays usable (no stuck error state).
        logger.warning("component error: %s", message)
        await self._set_state("error")
        await self.send_event({"type": "error", "message": self.settings.friendly_error})
        self.vad.reset()
        self.wake_word.reset()
        await asyncio.sleep(1.4)
        await self._set_state("sleeping")
