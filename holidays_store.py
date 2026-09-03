"""
holidays_store.py - JSON persistence for holiday dates. Any cycle with
skip_holidays=True (the default) won't fire on a date listed here.
"""

import json
import threading
from pathlib import Path

STORE_PATH = Path(__file__).parent / "holidays.json"
_lock = threading.Lock()


def _read():
    if not STORE_PATH.exists():
        return []
    with open(STORE_PATH, "r") as f:
        return json.load(f)


def _write(data):
    with open(STORE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def list_holidays():
    with _lock:
        return sorted(_read(), key=lambda h: h["date"])


def is_holiday(date_str):
    with _lock:
        return any(h["date"] == date_str for h in _read())


def add_holiday(date_str, label=""):
    with _lock:
        data = _read()
        if any(h["date"] == date_str for h in data):
            return data
        data.append({"date": date_str, "label": label})
        _write(data)
        return data


def remove_holiday(date_str):
    with _lock:
        data = _read()
        remaining = [h for h in data if h["date"] != date_str]
        changed = len(remaining) != len(data)
        if changed:
            _write(remaining)
        return changed
