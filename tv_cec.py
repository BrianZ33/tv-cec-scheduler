#!/usr/bin/env python3
"""
tv_cec.py - Send HDMI-CEC commands to a TV from a Raspberry Pi.

Wraps `cec-client` (from the cec-utils / libcec package) so you can
call simple, scriptable commands from cron or systemd:

    tv_cec.py on
    tv_cec.py off
    tv_cec.py active-source          # make the Pi itself the active input
    tv_cec.py switch --addr 3.0.0.0  # switch TV to another device's HDMI port
    tv_cec.py scan                   # list devices + their physical addresses

Requires: sudo apt install cec-utils
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

LOG_FILE = Path.home() / "tv_cec.log"

# The name the TV shows for this device in its input list. CEC limits
# this to 14 ASCII characters - change it to whatever you'd like the
# Pi to be called (e.g. "Living Room", "Kids TV").
OSD_NAME = "TV Scheduler"


def _configure_cli_logging():
    """
    Only called when this file runs as a standalone CLI script (see
    main() below) - never at import time. Python's logging.basicConfig
    only honors the FIRST call in a process; calling it here unconditionally
    at module load would silently win over app.py's own basicConfig call
    when app.py imports this module, breaking the web app's own logging
    to tv_cec_web.log without any error or warning.
    """
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def run_cec(command: str, timeout: int = 15) -> str:
    """
    Send one command to cec-client in single-shot mode and return output.
    -s = single command mode (exits after running it)
    -d 1 = only log errors from cec-client itself (keeps output clean)
    -o = OSD name shown on the TV's input list for this device
    """
    try:
        result = subprocess.run(
            ["cec-client", "-s", "-d", "1", "-o", OSD_NAME],
            input=f"{command}\n",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        logging.info("cmd=%r rc=%s", command, result.returncode)
        if result.returncode != 0:
            logging.warning("stderr: %s", result.stderr.strip())
        return result.stdout
    except FileNotFoundError:
        logging.error("cec-client not found. Install with: sudo apt install cec-utils")
        raise
    except subprocess.TimeoutExpired:
        logging.error("cec-client timed out on command %r", command)
        raise


def power_on():
    """Power on the TV (logical address 0 = TV)."""
    return run_cec("on 0")


def power_off():
    """Put the TV into standby."""
    return run_cec("standby 0")


def make_active_source():
    """
    Tell the TV the Pi is now the active source. This is the most
    reliable way to switch the TV to whatever HDMI port the Pi is
    plugged into.
    """
    return run_cec("as")


def switch_to(physical_addr: str):
    """
    Switch the TV's active input to a specific physical address
    (e.g. '3.0.0.0' for HDMI 3), even if it's a different device
    than the Pi. Use `scan` first to find the address you want.
    """
    hexed = "".join(f"{int(p):01x}" for p in physical_addr.split("."))
    frame = f"tx 1F:82:{hexed[0]}{hexed[1]}:{hexed[2]}{hexed[3]}"
    return run_cec(frame)


def scan():
    """List CEC devices on the bus with their physical addresses."""
    return run_cec("scan", timeout=25)


def main():
    _configure_cli_logging()
    parser = argparse.ArgumentParser(description="Send CEC commands to a TV")
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("on", help="Power on the TV")
    sub.add_parser("off", help="Put the TV in standby")
    sub.add_parser("active-source", help="Make the Pi the active HDMI input")
    sub.add_parser("scan", help="List CEC devices and their addresses")

    switch_parser = sub.add_parser("switch", help="Switch TV input to a given device")
    switch_parser.add_argument(
        "--addr", required=True, help="Physical address, e.g. 3.0.0.0"
    )

    args = parser.parse_args()

    try:
        if args.action == "on":
            output = power_on()
        elif args.action == "off":
            output = power_off()
        elif args.action == "active-source":
            output = make_active_source()
        elif args.action == "scan":
            output = scan()
        elif args.action == "switch":
            output = switch_to(args.addr)
        print(output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
