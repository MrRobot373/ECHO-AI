"""Action executors. Windows-focused for laptop dev; abstracted so the car
head-unit can swap implementations later. Each returns a short spoken string.

Reliable actions run for real; brittle ones (calls, WhatsApp auto-send,
radio, Wi-Fi/BT/data/location toggles) are best-effort with simulated replies.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

from backend.config import Settings

logger = logging.getLogger(__name__)
IS_WINDOWS = platform.system().lower() == "windows"

# Known app name -> launch target (Windows). Unknown names fall back to `start <name>`.
_APP_MAP = {
    "calculator": "calc",
    "calc": "calc",
    "notepad": "notepad",
    "paint": "mspaint",
    "camera": "microsoft.windows.camera:",
    "settings": "ms-settings:",
    "explorer": "explorer",
    "files": "explorer",
    "file manager": "explorer",
    "maps": "bingmaps:",
    "clock": "ms-clock:",
    "calendar": "outlookcal:",
    "browser": "https://www.google.com",
    "chrome": "chrome",
    "edge": "msedge",
}

_WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    95: "a thunderstorm", 96: "a thunderstorm with hail", 99: "a thunderstorm with hail",
}


def _open(target: str) -> None:
    """Open a URL, URI, or protocol target with the OS default handler."""
    if IS_WINDOWS:
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return
        except OSError:
            pass
    webbrowser.open(target)


def _load_contacts(settings: Settings) -> dict:
    path = Path(settings.contacts_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k).strip().lower(): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        return {}


# ── reliable ─────────────────────────────────────────────────────────────
def open_app(args: dict, settings: Settings) -> str:
    name = str(args.get("name", "")).strip()
    if not name:
        return "Which app should I open?"
    target = _APP_MAP.get(name.lower())
    try:
        if target:
            _open(target) if (":" in target or target.startswith("http")) else subprocess.Popen(target, shell=True)
        else:
            subprocess.Popen(f'start "" "{name}"', shell=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("open_app failed: %s", exc)
        return f"I couldn't open {name}."
    return f"Opening {name}."


def play_youtube(args: dict, settings: Settings) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "What should I play on YouTube?"
    _open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query))
    return f"Playing {query} on YouTube."


def play_spotify(args: dict, settings: Settings) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "What should I play on Spotify?"
    try:
        _open("spotify:search:" + urllib.parse.quote(query))
    except Exception:  # noqa: BLE001
        _open("https://open.spotify.com/search/" + urllib.parse.quote(query))
    return f"Playing {query} on Spotify."


def play_music(args: dict, settings: Settings) -> str:
    return play_spotify(args, settings)


def navigate_maps(args: dict, settings: Settings) -> str:
    destination = str(args.get("destination", "")).strip()
    if not destination:
        return "Where would you like to go?"
    _open("https://www.google.com/maps/dir/?api=1&destination=" + urllib.parse.quote(destination))
    return f"Starting navigation to {destination}."


def web_search(args: dict, settings: Settings) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "What should I search for?"
    _open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Here are search results for {query}."


def get_weather(args: dict, settings: Settings) -> str:
    city = str(args.get("city", "")).strip() or settings.default_city
    try:
        with httpx.Client(timeout=8) as client:
            geo = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1},
            ).json()
            results = geo.get("results") or []
            if not results:
                return f"I couldn't find weather for {city}."
            place = results[0]
            forecast = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": "temperature_2m,weather_code",
                },
            ).json()
            current = forecast.get("current", {})
            temp = round(current.get("temperature_2m"))
            desc = _WEATHER_CODES.get(int(current.get("weather_code", -1)), "")
        label = place.get("name", city)
        return f"It's {desc}, {temp}°C in {label}." if desc else f"It's {temp}°C in {label}."
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_weather failed: %s", exc)
        return f"I couldn't get the weather for {city} right now."


def set_volume(args: dict, settings: Settings) -> str:
    action = str(args.get("action", "")).lower()
    try:
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(interface, POINTER(IAudioEndpointVolume))

        if action == "mute":
            vol.SetMute(1, None)
            return "Muted."
        if action == "unmute":
            vol.SetMute(0, None)
            return "Unmuted."
        if action == "set":
            level = max(0, min(100, int(args.get("level", 50))))
            vol.SetMasterVolumeLevelScalar(level / 100, None)
            return f"Volume set to {level} percent."
        current = vol.GetMasterVolumeLevelScalar()
        new = min(1.0, current + 0.1) if action == "up" else max(0.0, current - 0.1)
        vol.SetMasterVolumeLevelScalar(new, None)
        return "Turning it up." if action == "up" else "Turning it down."
    except Exception as exc:  # noqa: BLE001
        logger.warning("set_volume failed: %s", exc)
        return "I couldn't change the volume on this device."


def set_brightness(args: dict, settings: Settings) -> str:
    action = str(args.get("action", "")).lower()
    try:
        import screen_brightness_control as sbc

        if action == "set":
            level = max(0, min(100, int(args.get("level", 50))))
        else:
            current = sbc.get_brightness()
            current = current[0] if isinstance(current, list) else current
            level = min(100, current + 20) if action == "up" else max(0, current - 20)
        sbc.set_brightness(level)
        return f"Brightness set to {level} percent."
    except Exception as exc:  # noqa: BLE001
        logger.warning("set_brightness failed: %s", exc)
        return "I couldn't change the brightness on this device."


# ── best-effort / stubs ───────────────────────────────────────────────────
def send_whatsapp(args: dict, settings: Settings) -> str:
    contact = str(args.get("contact", "")).strip()
    message = str(args.get("message", "")).strip()
    number = _load_contacts(settings).get(contact.lower())
    if not number:
        return f"I don't have a number saved for {contact}. Add them to contacts.json."
    digits = "".join(ch for ch in number if ch.isdigit())
    _open(f"https://wa.me/{digits}?text=" + urllib.parse.quote(message))
    return f"I've opened WhatsApp to {contact} with your message — tap send to deliver it."


def send_text(args: dict, settings: Settings) -> str:
    contact = str(args.get("contact", "")).strip()
    number = _load_contacts(settings).get(contact.lower())
    if not number:
        return f"I don't have a number saved for {contact}."
    return f"I'll send that message to {contact} once connected to your phone."


def make_call(args: dict, settings: Settings) -> str:
    contact = str(args.get("contact", "")).strip()
    number = _load_contacts(settings).get(contact.lower())
    if not number:
        return f"I don't have a number saved for {contact}. Add them to contacts.json."
    return f"I'll call {contact} through the car's connected phone."


def control_setting(args: dict, settings: Settings) -> str:
    setting = str(args.get("setting", "")).lower()
    action = str(args.get("action", "")).lower()
    on = action == "on"
    if setting == "wifi" and IS_WINDOWS:
        try:
            subprocess.run(
                ["netsh", "interface", "set", "interface", "Wi-Fi",
                 f"admin={'enabled' if on else 'disabled'}"],
                capture_output=True, timeout=8, check=True,
            )
            return f"Wi-Fi turned {action}."
        except Exception as exc:  # noqa: BLE001
            logger.info("wifi toggle best-effort failed: %s", exc)
            return f"I tried to turn Wi-Fi {action}, but it needs admin rights here."
    return f"Turning {setting} {action}. (Simulated on this device.)"


def play_radio(args: dict, settings: Settings) -> str:
    station = str(args.get("station", "")).strip()
    if settings.radio_stream_url:
        _open(settings.radio_stream_url)
        return f"Playing {station or 'the radio'}."
    return "Radio isn't configured on this device yet."


def get_car_info(args: dict, settings: Settings) -> str:
    question = str(args.get("question", "")).strip().lower()
    path = Path(settings.car_info_path)
    if not path.exists():
        return "I don't have car information loaded yet."
    text = path.read_text(encoding="utf-8")
    # naive section match: return the paragraph whose heading shares a keyword
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    words = {w for w in question.split() if len(w) > 3}
    best = None
    for block in blocks:
        if words and any(w in block.lower() for w in words):
            best = block
            break
    snippet = (best or (blocks[0] if blocks else "")).replace("#", "").strip()
    return snippet[:300] if snippet else "I don't have details on that yet."


EXECUTORS = {
    "open_app": open_app,
    "play_youtube": play_youtube,
    "play_spotify": play_spotify,
    "play_music": play_music,
    "navigate_maps": navigate_maps,
    "web_search": web_search,
    "get_weather": get_weather,
    "set_volume": set_volume,
    "set_brightness": set_brightness,
    "send_whatsapp": send_whatsapp,
    "send_text": send_text,
    "make_call": make_call,
    "control_setting": control_setting,
    "play_radio": play_radio,
    "get_car_info": get_car_info,
}


def execute(name: str, args: dict, settings: Settings) -> str:
    handler = EXECUTORS.get(name)
    if not handler:
        return "I'm not able to do that yet."
    return handler(args or {}, settings)
