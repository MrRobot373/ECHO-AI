"""OBD-II / vehicle data module.

In mock mode (default) returns realistic simulated data so the demo works
without any hardware. In real mode, swap mock_data.py for python-obd calls
on an ELM327 Bluetooth adapter.
"""
from backend.obd.mock_data import get_vehicle_data, get_diagnostics
from backend.obd.monitor import OBDMonitor

__all__ = ["get_vehicle_data", "get_diagnostics", "OBDMonitor"]
