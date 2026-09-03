#!/usr/bin/env python3
"""
app.py - Web UI + scheduler for TV CEC control.

Runs a Flask server with an embedded APScheduler. Two kinds of schedule
entries live in schedule.json (via schedule_store.py):
  - "recurring": fires on chosen days of the week, every week
  - "once": fires on a single specific date (for one-off overrides)

holidays.json (via holidays_store.py) lists dates on which entries with
skip_holidays=True are suppressed - e.g. no school, so don't force the
TV off at the usual time.

settings.json (via settings_store.py) holds the warning image and how
long it displays before an "off" cycle actually turns the TV off.

The scheduler is rebuilt from schedule.json any time an entry is added,
edited, or deleted through the API.

Run directly for testing:
    python3 app.py
Or install as a systemd service - see tv-cec-web.service.
"""

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

import schedule_store as store
import holidays_store
import settings_store
import display_image
import tv_cec

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

logging.basicConfig(
    filename=BASE_DIR / "tv_cec_web.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

app = Flask(__name__)
scheduler = BackgroundScheduler()

ACTION_LABELS = {
    "on": "Power on",
    "off": "Standby",
    "active-source": "Switch to Pi",
    "switch": "Switch input",
}


# ---------------------------------------------------------------------
# Scheduler execution
# ---------------------------------------------------------------------

def run_action(entry_id):
    """Executed by APScheduler when a cycle fires."""
    entry = store.get_entry(entry_id)
    if not entry:
        return

    today_str = date.today().isoformat()
    if entry.get("skip_holidays", True) and holidays_store.is_holiday(today_str):
        store.record_run(entry_id, True, "Skipped (holiday)")
        logging.info("Entry %s skipped - holiday", entry_id)
        return

    action = entry["action"]
    try:
        if action == "on":
            tv_cec.power_on()
        elif action == "off":
            if entry.get("warning_enabled"):
                settings = settings_store.get_settings()
                img = settings.get("warning_image")
                duration = settings.get("warning_duration_seconds", 60)
                if img:
                    img_path = UPLOAD_DIR / img
                    # Render everything BEFORE switching input, so there's
                    # no dead time on the Pi's screen mid-transition.
                    frame_paths, tmp_dir = display_image.prepare_countdown_frames(img_path, duration)
                    tv_cec.make_active_source()
                    if frame_paths:
                        display_image.play_frames(frame_paths, duration)
                        display_image.cleanup(tmp_dir)
                    else:
                        display_image.show_static(img_path, duration)
                    tv_cec.power_off()
                    display_image.blank_screen()
                else:
                    tv_cec.power_off()
            else:
                tv_cec.power_off()
        elif action == "active-source":
            tv_cec.make_active_source()
        elif action == "switch":
            tv_cec.switch_to(entry.get("addr", "0.0.0.0"))

        store.record_run(entry_id, True, f"{ACTION_LABELS.get(action, action)} sent")
        logging.info("Ran entry %s (%s)", entry_id, action)

        if entry.get("type") == "once":
            store.update_entry(entry_id, {"enabled": False, "completed": True})
    except Exception as e:
        store.record_run(entry_id, False, str(e))
        logging.exception("Entry %s failed", entry_id)


def reload_jobs():
    """Rebuild all scheduler jobs from the current schedule.json contents."""
    scheduler.remove_all_jobs()
    for entry in store.list_entries():
        if not entry.get("enabled", True):
            continue
        try:
            hour, minute = entry["time"].split(":")
            if entry.get("type", "recurring") == "once":
                if not entry.get("date"):
                    continue
                run_date = datetime.strptime(
                    f"{entry['date']} {entry['time']}", "%Y-%m-%d %H:%M"
                )
                if run_date < datetime.now():
                    continue  # already in the past, don't schedule
                trigger = DateTrigger(run_date=run_date)
            else:
                days = ",".join(entry.get("days") or store.DAYS)
                trigger = CronTrigger(day_of_week=days, hour=hour, minute=minute)

            scheduler.add_job(
                run_action,
                trigger=trigger,
                args=[entry["id"]],
                id=entry["id"],
                replace_existing=True,
            )
        except Exception:
            logging.exception("Could not schedule entry %s", entry.get("id"))


# ---------------------------------------------------------------------
# Calendar occurrence calculation
# ---------------------------------------------------------------------

def occurrences_for_month(year, month):
    """
    Returns {date_str: {"holiday": bool, "entries": [entry, ...]}} for
    every day in the given month, expanding recurring entries onto the
    days of the week they apply to and placing "once" entries on their
    specific date.
    """
    entries = store.list_entries()
    holidays = {h["date"] for h in holidays_store.list_holidays()}

    first_day = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    days_in_month = (next_month - first_day).days

    result = {}
    for i in range(days_in_month):
        d = first_day + timedelta(days=i)
        date_str = d.isoformat()
        weekday_code = store.DAYS[d.weekday()]  # Mon=0 ... Sun=6, matches store.DAYS order
        day_entries = []
        for e in entries:
            if e.get("type", "recurring") == "recurring":
                if weekday_code in (e.get("days") or []):
                    day_entries.append(e)
            else:
                if e.get("date") == date_str:
                    day_entries.append(e)
        result[date_str] = {
            "holiday": date_str in holidays,
            "entries": day_entries,
        }
    return result


# ---------------------------------------------------------------------
# Routes: pages
# ---------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------
# Routes: schedule CRUD
# ---------------------------------------------------------------------

@app.route("/api/schedule", methods=["GET"])
def api_list():
    return jsonify(store.list_entries())


@app.route("/api/schedule", methods=["POST"])
def api_create():
    data = request.get_json(force=True)
    if "time" not in data or "action" not in data:
        return jsonify({"error": "time and action are required"}), 400

    entry_type = data.get("type", "recurring")
    entry = {
        "type": entry_type,
        "time": data["time"],
        "action": data["action"],
        "addr": data.get("addr", ""),
        "enabled": True,
        "warning_enabled": bool(data.get("warning_enabled", False)),
        "skip_holidays": bool(data.get("skip_holidays", True)),
    }
    if entry_type == "once":
        if not data.get("date"):
            return jsonify({"error": "date is required for one-time events"}), 400
        entry["date"] = data["date"]
    else:
        entry["days"] = data.get("days") or store.DAYS

    created = store.add_entry(entry)
    reload_jobs()
    return jsonify(created), 201


@app.route("/api/schedule/<entry_id>", methods=["PUT"])
def api_update(entry_id):
    updates = request.get_json(force=True)
    updated = store.update_entry(entry_id, updates)
    if not updated:
        return jsonify({"error": "not found"}), 404
    reload_jobs()
    return jsonify(updated)


@app.route("/api/schedule/<entry_id>", methods=["DELETE"])
def api_delete(entry_id):
    ok = store.delete_entry(entry_id)
    reload_jobs()
    return ("", 204) if ok else (jsonify({"error": "not found"}), 404)


@app.route("/api/run-now", methods=["POST"])
def api_run_now():
    data = request.get_json(force=True)
    action = data.get("action")
    try:
        if action == "on":
            tv_cec.power_on()
        elif action == "off":
            tv_cec.power_off()
        elif action == "active-source":
            tv_cec.make_active_source()
        else:
            return jsonify({"ok": False, "error": "unknown action"}), 400
        return jsonify({"ok": True})
    except Exception as e:
        logging.exception("run-now failed")
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------
# Routes: calendar
# ---------------------------------------------------------------------

@app.route("/api/calendar", methods=["GET"])
def api_calendar():
    try:
        year = int(request.args["year"])
        month = int(request.args["month"])
    except (KeyError, ValueError):
        return jsonify({"error": "year and month query params are required"}), 400
    return jsonify(occurrences_for_month(year, month))


# ---------------------------------------------------------------------
# Routes: holidays
# ---------------------------------------------------------------------

@app.route("/api/holidays", methods=["GET"])
def api_holidays_list():
    return jsonify(holidays_store.list_holidays())


@app.route("/api/holidays", methods=["POST"])
def api_holidays_add():
    data = request.get_json(force=True)
    label = data.get("label", "")
    try:
        if "start" in data:
            start = date.fromisoformat(data["start"])
            end = date.fromisoformat(data.get("end") or data["start"])
            if end < start:
                return jsonify({"error": "end date must be on or after start date"}), 400
            d = start
            while d <= end:
                holidays_store.add_holiday(d.isoformat(), label)
                d += timedelta(days=1)
        elif "date" in data:
            holidays_store.add_holiday(data["date"], label)
        else:
            return jsonify({"error": "date, or start/end, is required"}), 400
    except ValueError:
        return jsonify({"error": "dates must be in YYYY-MM-DD format"}), 400
    reload_jobs()
    return jsonify(holidays_store.list_holidays()), 201


@app.route("/api/holidays/<date_str>", methods=["DELETE"])
def api_holidays_remove(date_str):
    ok = holidays_store.remove_holiday(date_str)
    reload_jobs()
    return ("", 204) if ok else (jsonify({"error": "not found"}), 404)


# ---------------------------------------------------------------------
# Routes: settings + warning image
# ---------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(settings_store.get_settings())


@app.route("/api/settings", methods=["PUT"])
def api_settings_update():
    data = request.get_json(force=True)
    updates = {}
    if "warning_duration_seconds" in data:
        try:
            updates["warning_duration_seconds"] = max(1, int(data["warning_duration_seconds"]))
        except (TypeError, ValueError):
            return jsonify({"error": "warning_duration_seconds must be a number"}), 400
    updated = settings_store.update_settings(updates)
    return jsonify(updated)


@app.route("/api/settings/image", methods=["POST"])
def api_settings_image():
    if "image" not in request.files:
        return jsonify({"error": "no file uploaded"}), 400
    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "no file selected"}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGE_EXT:
        return jsonify({"error": f"unsupported file type: .{ext}"}), 400

    for old in UPLOAD_DIR.glob("warning.*"):
        old.unlink()

    filename = f"warning.{ext}"
    file.save(UPLOAD_DIR / filename)
    updated = settings_store.update_settings({"warning_image": filename})
    return jsonify(updated)


if __name__ == "__main__":
    reload_jobs()
    scheduler.start()
    app.run(host="0.0.0.0", port=80, threaded=True)
