"""
settings_store.py - JSON persistence for app-wide settings: the warning
image shown before an "off" cycle, and how long it displays.
"""

import json
import threading
from pathlib import Path

STORE_PATH = Path(__file__).parent / "settings.json"
_lock = threading.Lock()

DEFAULTS = {
    "warning_image": None,  # filename inside static/uploads/
    "warning_duration_seconds": 60,
}


def get_settings():
    with _lock:
        merged = dict(DEFAULTS)
        if STORE_PATH.exists():
            with open(STORE_PATH, "r") as f:
                merged.update(json.load(f))
        return merged


def update_settings(updates):
    with _lock:
        current = dict(DEFAULTS)
        if STORE_PATH.exists():
            with open(STORE_PATH, "r") as f:
                current.update(json.load(f))
        current.update(updates)
        with open(STORE_PATH, "w") as f:
            json.dump(current, f, indent=2)
        return current
