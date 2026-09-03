"""
display_image.py - show a full-screen image on the Pi's own HDMI output
using `fbi`, the lightweight framebuffer image viewer. This is meant for
a Pi running headless (Raspberry Pi OS Lite, booting to a console, no
desktop) dedicated to this appliance.

Requires: sudo apt install fbi

Framebuffer/VT access is one of the more hardware- and OS-dependent
things a Pi can do - if this doesn't display anything on your setup,
SSH in and test it manually first:
    sudo fbi -d /dev/fb0 -T 1 -a /path/to/image.jpg
(Ctrl+C to exit.) See the README troubleshooting section for fixes.
"""

"""
display_image.py - show a full-screen image on the Pi's own HDMI output
using `fbi`, the lightweight framebuffer image viewer. This is meant for
a Pi running headless (Raspberry Pi OS Lite, booting to a console, no
desktop) dedicated to this appliance.

Requires: sudo apt install fbi
Countdown overlay requires: pip install Pillow (in requirements.txt)

Framebuffer/VT access is one of the more hardware- and OS-dependent
things a Pi can do - if this doesn't display anything on your setup,
SSH in and test it manually first:
    sudo fbi -d /dev/fb0 -T 1 -a /path/to/image.jpg
(Ctrl+C to exit.) See the README troubleshooting section for fixes.
"""

import logging
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]

MAX_DIMENSION = 1920  # cap frame size so rendering stays fast on a Pi Zero 2W


def _load_font(size):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _format_countdown(seconds_left):
    m, s = divmod(max(0, seconds_left), 60)
    return f"{m}:{s:02d}"


def _prepare_base_image(image_path):
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    if w > MAX_DIMENSION or h > MAX_DIMENSION:
        scale = MAX_DIMENSION / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)))
    return img


def _render_frame(base_image, seconds_left, clock_dt, big_font, small_font, out_path):
    img = base_image.copy()
    w, h = img.size
    draw = ImageDraw.Draw(img, "RGBA")

    countdown_text = f"TV turning off in {_format_countdown(seconds_left)}"
    clock_text = clock_dt.strftime("%I:%M:%S %p").lstrip("0")

    bar_h = int(h * 0.22)
    draw.rectangle([0, h - bar_h, w, h], fill=(0, 0, 0, 165))

    bbox = draw.textbbox((0, 0), countdown_text, font=big_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2, h - bar_h + 12), countdown_text, font=big_font, fill=(255, 255, 255, 255))

    bbox2 = draw.textbbox((0, 0), clock_text, font=small_font)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(((w - tw2) / 2, h - bar_h + 20 + th), clock_text, font=small_font, fill=(220, 220, 220, 255))

    img.save(out_path, "PNG")


def prepare_countdown_frames(image_path, duration_seconds):
    """
    Pre-renders the countdown/clock frame sequence for image_path over
    duration_seconds, entirely before anything is displayed. Call this
    BEFORE switching the TV's input, so the Pi is ready to show frame 1
    the instant it becomes the active source - no dead time staring at
    a blank/idle screen while frames are still being generated.

    Returns (frame_paths, tmp_dir) on success, or (None, None) if Pillow
    isn't available or preparation fails - caller should fall back to
    show_static() in that case. Caller must call cleanup(tmp_dir)
    once done with the frames.
    """
    if not image_path or not PIL_AVAILABLE:
        if image_path and not PIL_AVAILABLE:
            logger.warning("Pillow not installed - falling back to a static image, no countdown")
        return None, None

    try:
        base_image = _prepare_base_image(image_path)
        w, h = base_image.size
        big_font = _load_font(max(24, h // 12))
        small_font = _load_font(max(16, h // 22))

        tmp_dir = tempfile.mkdtemp(prefix="tv_cec_warning_")
        frame_paths = []
        start = datetime.now()
        for i in range(duration_seconds):
            seconds_left = duration_seconds - i
            clock_dt = start + timedelta(seconds=i)
            out_path = Path(tmp_dir) / f"frame_{i:04d}.png"
            _render_frame(base_image, seconds_left, clock_dt, big_font, small_font, out_path)
            frame_paths.append(str(out_path))
        return frame_paths, tmp_dir
    except Exception:
        logger.exception("Failed to prepare countdown frames")
        return None, None


def _kill_existing_fbi():
    """
    Stop any already-running fbi instance (e.g. a boot splash) before
    starting a new one. Two fbi processes fighting over the same VT
    causes the same kind of garbled display/lost-frame issue as a
    getty conflict, so only one may run at a time.
    """
    try:
        subprocess.run(["pkill", "-x", "fbi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)  # give it a moment to actually release the framebuffer/VT
    except Exception:
        logger.exception("Failed to stop an existing fbi instance")


def play_frames(frame_paths, duration_seconds):
    """
    Play a pre-rendered frame sequence via fbi, one frame per second.
    Call this AFTER the TV has been switched to the Pi's input. Blocks
    for duration_seconds, then stops fbi. Returns True if it ran.
    """
    _kill_existing_fbi()
    proc = None
    try:
        proc = subprocess.Popen(
            ["fbi", "-d", "/dev/fb0", "-T", "1", "--noverbose", "-t", "1", "-a"] + frame_paths,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(max(1, int(duration_seconds)))
        return True
    except FileNotFoundError:
        logger.error("fbi not found - install with: sudo apt install fbi")
        return False
    except Exception:
        logger.exception("Failed to play countdown frames")
        return False
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


def cleanup(tmp_dir):
    """Remove the temp directory of rendered frames."""
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def show_static(image_path, duration_seconds):
    """
    Display a single static image (no countdown) for duration_seconds.
    Used as a fallback when Pillow isn't available, or directly for a
    plain warning image with no overlay. Call after switching input.
    """
    _kill_existing_fbi()
    proc = None
    try:
        proc = subprocess.Popen(
            ["fbi", "-d", "/dev/fb0", "-T", "1", "--noverbose", "-a", str(image_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(max(1, int(duration_seconds)))
        return True
    except FileNotFoundError:
        logger.error("fbi not found - install with: sudo apt install fbi")
        return False
    except Exception:
        logger.exception("Failed to display warning image")
        return False
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


def blank_screen():
    """
    Clear the Pi's framebuffer to black. Call this after the TV has
    been put in standby, so the Pi isn't left showing a frozen last
    frame if someone switches back to its input later.
    """
    try:
        subprocess.run("dd if=/dev/zero of=/dev/fb0 2>/dev/null", shell=True)
    except Exception:
        logger.exception("Failed to blank framebuffer")
