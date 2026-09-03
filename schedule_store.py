"""
schedule_store.py - simple thread-safe JSON persistence for TV CEC
schedule entries. No database needed for a handful of daily cycles.
"""

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

STORE_PATH = Path(__file__).parent / "schedule.json"
_lock = threading.Lock()

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _read():
    if not STORE_PATH.exists():
        return []
    with open(STORE_PATH, "r") as f:
        return json.load(f)


def _write(entries):
    with open(STORE_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def list_entries():
    with _lock:
        return _read()


def get_entry(entry_id):
    with _lock:
        for e in _read():
            if e["id"] == entry_id:
                return e
        return None


def add_entry(entry):
    with _lock:
        entries = _read()
        entry["id"] = uuid.uuid4().hex[:8]
        entries.append(entry)
        _write(entries)
        return entry


def update_entry(entry_id, updates):
    with _lock:
        entries = _read()
        for e in entries:
            if e["id"] == entry_id:
                e.update(updates)
                _write(entries)
                return e
        return None


def delete_entry(entry_id):
    with _lock:
        entries = _read()
        remaining = [e for e in entries if e["id"] != entry_id]
        changed = len(remaining) != len(entries)
        if changed:
            _write(remaining)
        return changed


def record_run(entry_id, success, message=""):
    with _lock:
        entries = _read()
        for e in entries:
            if e["id"] == entry_id:
                e["last_run"] = {
                    "success": success,
                    "message": message,
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                _write(entries)
                return
