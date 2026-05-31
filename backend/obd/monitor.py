"""Proactive OBD-II monitor — watches vehicle data and fires spoken alerts."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from backend.obd.mock_data import get_vehicle_data

logger = logging.getLogger(__name__)

# Alert thresholds
_BATTERY_LOW = 20       # % — warn when battery drops below this
_BATTERY_CRITICAL = 10  # % — urgent warning
_TYRE_LOW = 29          # PSI — warn when any tyre drops below this
_MOTOR_HOT = 90         # °C — warn if motor overheats

_TYRE_NAMES = {"FR": "front right", "FL": "front left", "RR": "rear right", "RL": "rear left"}


class OBDMonitor:
    """Runs as an asyncio background task and emits spoken alerts."""

    def __init__(
        self,
        speak: Callable[[str], Awaitable[None]],
        interval: float = 60.0,
    ) -> None:
        self._speak = speak
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._alerted: set[str] = set()   # tracks which alerts already fired

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _loop(self) -> None:
        await asyncio.sleep(30)   # wait for warmup to finish
        while True:
            try:
                await self._check()
            except Exception as exc:  # noqa: BLE001
                logger.debug("obd monitor check error: %s", exc)
            await asyncio.sleep(self._interval)

    async def _check(self) -> None:
        data = get_vehicle_data()
        alerts: list[str] = []

        bat = data.get("battery_pct", 100)
        if bat <= _BATTERY_CRITICAL and "bat_critical" not in self._alerted:
            alerts.append(f"Battery is critically low at {round(bat)} percent. Please charge soon.")
            self._alerted.add("bat_critical")
        elif bat <= _BATTERY_LOW and "bat_low" not in self._alerted:
            alerts.append(f"Battery is at {round(bat)} percent. You have about {data.get('range_km', '?')} kilometres of range left.")
            self._alerted.add("bat_low")
        elif bat > _BATTERY_LOW + 5:
            self._alerted.discard("bat_low")
            self._alerted.discard("bat_critical")

        pressures = data.get("tyre_pressure", {})
        for code, psi in pressures.items():
            key = f"tyre_{code}"
            if psi < _TYRE_LOW and key not in self._alerted:
                name = _TYRE_NAMES.get(code, code)
                alerts.append(f"Your {name} tyre pressure is low at {psi} PSI. Recommended is {'33' if code.startswith('F') else '35'} PSI.")
                self._alerted.add(key)
            elif psi >= _TYRE_LOW:
                self._alerted.discard(key)

        motor_temp = data.get("motor_temp_c", 0)
        if motor_temp >= _MOTOR_HOT and "motor_hot" not in self._alerted:
            alerts.append(f"Motor temperature is high at {motor_temp} degrees. Consider reducing speed.")
            self._alerted.add("motor_hot")
        elif motor_temp < _MOTOR_HOT - 10:
            self._alerted.discard("motor_hot")

        for alert in alerts:
            logger.info("obd alert: %s", alert)
            await self._speak(alert)
            await asyncio.sleep(2)
