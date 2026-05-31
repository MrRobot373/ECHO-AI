"""Ollama tool/function specs + permission mapping for the car assistant.

The tool model (see Settings.ollama_tool_model) is given these specs and
picks one when the user's request maps to an action. Anything conversational
gets no tool call and falls through to a normal chat answer.
"""
from __future__ import annotations


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SPECS: list[dict] = [
    _fn("open_app", "Open an application on the device (e.g. calculator, notepad, camera, settings, maps).",
        {"name": {"type": "string", "description": "App name, e.g. 'calculator'"}}, ["name"]),
    _fn("play_youtube", "Search or play something on YouTube.",
        {"query": {"type": "string", "description": "What to search/play on YouTube"}}, ["query"]),
    _fn("play_spotify", "Play a song, artist, or playlist on Spotify.",
        {"query": {"type": "string", "description": "What to play on Spotify"}}, ["query"]),
    _fn("play_music", "Play music when no specific service is named.",
        {"query": {"type": "string", "description": "Song, artist, or genre"}}, ["query"]),
    _fn("navigate_maps", "Open navigation / directions to a place in Google Maps.",
        {"destination": {"type": "string", "description": "Destination, e.g. 'Pune airport'"}}, ["destination"]),
    _fn("web_search",
        "Search the web ONLY when the user explicitly asks to search/look up/Google "
        "something, or needs live/current info (news, prices, scores). Do NOT use this "
        "for general knowledge you can answer yourself.",
        {"query": {"type": "string", "description": "Search query"}}, ["query"]),
    _fn("get_weather", "Get the current weather for a city (defaults to the car's city).",
        {"city": {"type": "string", "description": "City name; optional"}}, []),
    _fn("set_volume", "Change the system volume.",
        {"action": {"type": "string", "enum": ["up", "down", "mute", "unmute", "set"]},
         "level": {"type": "integer", "description": "0-100, only for action 'set'"}}, ["action"]),
    _fn("set_brightness", "Change the screen brightness.",
        {"action": {"type": "string", "enum": ["up", "down", "set"]},
         "level": {"type": "integer", "description": "0-100, only for action 'set'"}}, ["action"]),
    _fn("send_whatsapp", "Send a WhatsApp message to a contact.",
        {"contact": {"type": "string"}, "message": {"type": "string"}}, ["contact", "message"]),
    _fn("send_text", "Send a text/SMS message to a contact.",
        {"contact": {"type": "string"}, "message": {"type": "string"}}, ["contact", "message"]),
    _fn("make_call", "Call a contact by name.",
        {"contact": {"type": "string"}}, ["contact"]),
    _fn("control_setting", "Turn a device setting on or off.",
        {"setting": {"type": "string", "enum": ["wifi", "bluetooth", "data", "location"]},
         "action": {"type": "string", "enum": ["on", "off"]}}, ["setting", "action"]),
    _fn("play_radio", "Play FM/web radio, optionally a station.",
        {"station": {"type": "string", "description": "Station name; optional"}}, []),
    _fn("get_car_info", "Answer a question about the car, its features, or FAQs.",
        {"question": {"type": "string"}}, ["question"]),
    _fn("get_vehicle_data",
        "Get live vehicle stats: speed, battery percentage, range, motor temperature, tyre pressures.",
        {}, []),
    _fn("get_diagnostics",
        "Check vehicle health: fault codes, battery health, tyre pressures, motor temperature.",
        {}, []),
    _fn("set_climate",
        "Set cabin temperature or toggle AC. Use when user says 'set AC', 'heat the car', 'set temperature'.",
        {"temperature": {"type": "integer", "description": "Target temperature in Celsius, e.g. 22"},
         "ac": {"type": "string", "enum": ["on", "off"], "description": "Turn AC on or off; optional"}}, []),
    _fn("control_vehicle",
        "Control physical car features: seat position, windows (open/close), sunroof (open/close), driving mode.",
        {"feature": {"type": "string", "enum": ["seat", "window", "sunroof", "driving_mode"]},
         "action": {"type": "string", "description": "e.g. 'recline', 'open', 'close', 'eco', 'sport', 'normal'"}},
        ["feature", "action"]),
]

# Static tool -> permission key. Tools with dynamic permissions resolve in required_permission().
_STATIC_PERMISSION = {
    "open_app": "apps",
    "play_youtube": "youtube",
    "play_spotify": "spotify",
    "play_music": "music",
    "navigate_maps": "maps",
    "web_search": "web_search",
    "get_weather": "weather",
    "set_brightness": "brightness",
    "send_whatsapp": "whatsapp",
    "send_text": "text",
    "make_call": "call",
    "play_radio": "radio",
    "get_car_info": "car_info",
    "get_vehicle_data": "car_info",
    "get_diagnostics": "car_info",
    "set_climate": "car_info",
    "control_vehicle": "car_info",
}


def required_permission(name: str, args: dict) -> str | None:
    """Permission key a tool call needs, resolving dynamic ones from args."""
    if name == "set_volume":
        return "volume_down" if str(args.get("action")) == "down" else "volume_up"
    if name == "control_setting":
        return str(args.get("setting", "")).lower() or None
    return _STATIC_PERMISSION.get(name)
