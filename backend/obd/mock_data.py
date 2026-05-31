"""Simulated OBD-II vehicle data for demo / development.

Returns realistic values for an electric vehicle. Replace with python-obd
calls when a real ELM327 Bluetooth adapter is connected.

To use real OBD-II:
    pip install obd
    import obd
    connection = obd.OBD()  # connects to first available port
    speed = connection.query(obd.commands.SPEED).value.magnitude
"""
from __future__ import annotations

import math
import time

_start = time.time()

# Simulated state (mutable so monitor can update it)
_state: dict = {
    "speed_kmh": 0,
    "battery_pct": 78.0,
    "range_km": 340,
    "motor_rpm": 0,
    "motor_temp_c": 42,
    "cabin_temp_c": 22,
    "outside_temp_c": 28,
    "tyre_pressure": {"FR": 33, "FL": 33, "RR": 35, "RL": 35},
    "fault_codes": [],
    "driving_mode": "normal",
    "regen_level": "medium",
    "ac_on": True,
    "target_cabin_temp": 22,
    "seat_position": "normal",
    "windows": "closed",
    "sunroof": "closed",
}


def _tick() -> None:
    """Advance simulation slightly on each read."""
    elapsed = time.time() - _start
    # speed oscillates 0–80 km/h with a slow sine
    _state["speed_kmh"] = max(0, round(40 + 40 * math.sin(elapsed / 60)))
    _state["motor_rpm"] = _state["speed_kmh"] * 45
    # battery drains 0.5% per minute of elapsed time
    _state["battery_pct"] = max(5.0, 78.0 - (elapsed / 60) * 0.5)
    _state["range_km"] = round(450 * _state["battery_pct"] / 100)
    # motor warms up with speed
    _state["motor_temp_c"] = 42 + round(_state["speed_kmh"] * 0.1)


def get_vehicle_data() -> dict:
    _tick()
    return dict(_state)


def get_diagnostics() -> dict:
    _tick()
    return {
        "fault_codes": _state["fault_codes"],
        "battery_health_pct": 97,
        "battery_pct": round(_state["battery_pct"]),
        "motor_temp_c": _state["motor_temp_c"],
        "tyre_pressure": _state["tyre_pressure"],
        "overall": "good" if not _state["fault_codes"] else "fault detected",
    }


def set_climate(target_temp: int, ac_on: bool | None = None) -> None:
    _state["target_cabin_temp"] = target_temp
    if ac_on is not None:
        _state["ac_on"] = ac_on


def set_seat(position: str) -> None:
    _state["seat_position"] = position


def set_window(state: str) -> None:
    _state["windows"] = state


def set_sunroof(state: str) -> None:
    _state["sunroof"] = state


def set_driving_mode(mode: str) -> None:
    if mode in ("eco", "normal", "sport"):
        _state["driving_mode"] = mode
