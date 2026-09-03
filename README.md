# TV CEC Scheduler (Raspberry Pi)

Sends HDMI-CEC commands to a TV (power on/off, input switch) on a schedule,
with a browser-based control panel: recurring cycles, a calendar view,
holiday overrides, and an optional warning image shown on-screen before
the TV turns off.

Everything lives in **one folder** - the CLI script, the web app, and its
`templates/`/`static/` subfolders. Copy the whole folder to the Pi and
run `install.sh` from inside it.

## Hardware notes

- CEC runs over the same HDMI cable as video - plug your Pi's HDMI (or
  mini-HDMI, on a Zero 2 W) directly into the TV, or through a switch that
  passes CEC through (cheap switches often don't).
- Most TVs ship with CEC **disabled by default** and under a
  vendor-specific name: Sony "Bravia Sync", Samsung "Anynet+", LG "SimpLink",
  Vizio "CEC", etc. Enable it in the TV's settings menu first.
- Use **Raspberry Pi OS Lite** (no desktop). The warning image is drawn
  straight to the framebuffer with `fbi`, which is simplest on a
  console-only boot - see Troubleshooting if you're on the Desktop image.

## Getting the files onto the Pi

Copy or drag the **whole project folder** onto the Pi as a single unit
(e.g. in FileZilla, drag the top-level folder itself into your Pi's home
directory, rather than multi-selecting individual files inside it) - that
preserves the `templates/` and `static/` subfolders. If you do end up with
everything flattened into one folder anyway, `install.sh` will detect and
fix that automatically (see below).

The folder should look like this once it's on the Pi:

```
tv-cec-scheduler/
├── install.sh
├── app.py
├── tv_cec.py
├── display_image.py
├── holidays_store.py
├── schedule_store.py
├── settings_store.py
├── requirements.txt
├── tv-cec-web.service
├── templates/
│   └── index.html
└── static/
    ├── app.js
    ├── style.css
    └── uploads/
```

## Setup

```bash
cd tv-cec-scheduler
chmod +x install.sh
./install.sh
```

`install.sh` is self-healing and safe to re-run:

- If `index.html`, `app.js`, or `style.css` ended up loose in the folder
  instead of nested in `templates/`/`static/` (a common result of
  transferring files individually rather than as a folder), it moves them
  into place automatically.
- If `requirements.txt` didn't make it over, it recreates it.
- It then checks that every required file is present, installs
  `cec-utils` and `fbi`, and sets up a Python virtual environment
  (`venv/`) with the web app's dependencies.

If it reports missing files it couldn't fix on its own, re-transfer those
specific files into the folder and run `./install.sh` again.

Once it's done, find your TV/device addresses:

```bash
./tv_cec.py scan
```

Look for the entry with `osd string: TV` (or similar) - note its
**physical address** (e.g. `0.0.0.0` is almost always the TV itself).

## Manual test

```bash
./tv_cec.py on              # power on TV
./tv_cec.py active-source   # switch TV to the Pi's HDMI input
./tv_cec.py off             # standby
./tv_cec.py switch --addr 3.0.0.0   # switch to another device's port
```

If `on`/`off` don't work, some TVs need the reverse direction - try
`echo "on 0" | cec-client -s` manually and check `cec-client -l` to
confirm your adapter is detected.

## Web UI

```bash
sudo venv/bin/python3 app.py
```

Visit `http://<pi-ip-address>/` from any device on the same network. Port
80 needs elevated privileges to bind, hence `sudo` for this manual test -
for day-to-day use, run it via systemd instead (see below), which handles
that for you.

### What's on the page

**Schedule tab** - recurring cycles. Pick a time, an action (power on,
standby, switch to Pi, or switch to another device's input), and which
days of the week it runs on (tap to toggle). For a "standby" cycle you
can also turn on **"Show warning image first, then turn off"** - the Pi
will switch itself to be the active source and show the configured image
with a live countdown ("TV turning off in 0:45") and the current clock
time overlaid at the bottom, updating once per second, for the
configured duration, then put the TV in standby. (This overlay needs
Pillow, installed automatically by `install.sh`; if it's ever missing,
the image still displays, just without the countdown/clock text.) Each
cycle also has a **"Skip this cycle on holidays"** checkbox (on by
default).

**Calendar tab** - a month view of everything scheduled, with colored dots
per day for each action. Click any date to see what's scheduled, mark
that date as a holiday, or add a **one-time event** that only fires on
that date.

**Holidays tab** - add a single date or a date range (e.g. a school break)
with a label. Any cycle with "skip on holidays" checked won't fire on
these dates. You can also mark/unmark individual dates from the Calendar
tab.

**Warning image tab** - upload the image to display (PNG/JPEG/GIF/WEBP)
and set how many seconds it shows before the TV goes to standby.

Everything is stored in small JSON files in this folder (`schedule.json`,
`holidays.json`, `settings.json`) and reloaded into the scheduler
automatically whenever you make a change - no restarts needed.

### Run it persistently (systemd)

```bash
sudo cp tv-cec-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tv-cec-web
```

Edit the `WorkingDirectory` and `ExecStart` paths in `tv-cec-web.service`
first if your username or install path isn't `/home/pi/tv-cec-scheduler/`.

**Note on running as root:** this service runs as root. That's needed both
to bind port 80 and - more importantly - for `fbi` to reliably access the
framebuffer/virtual terminal to show the warning image, which is much
fiddlier to grant piecemeal than port binding alone. For a single-purpose
device on your home network this is a reasonable trade-off. If you'd
rather avoid it: drop the warning-image feature, set `User=pi` instead,
add `AmbientCapabilities=CAP_NET_BIND_SERVICE` and
`CapabilityBoundingSet=CAP_NET_BIND_SERVICE` for port 80, and add `pi` to
the `video` group (`sudo usermod -aG video pi`) - though you may still hit
VT-switching permission issues without root.

Check it's up:

```bash
systemctl status tv-cec-web
journalctl -u tv-cec-web -f
```

### Reaching it from other devices

If you can't reach it, check the Pi's firewall (`sudo ufw allow 80` if
`ufw` is active), confirm you're using the Pi's LAN IP not `localhost`,
and make sure nothing else on the Pi is already using port 80.

---

## Manual scheduling (alternative to the web UI)

If you'd rather not run the web app at all, schedule the CLI script
directly with cron or systemd timers. This skips the calendar, holidays,
and warning-image features - just on/off/switch on a fixed schedule.

### Option A: cron

```bash
crontab -e
```

```
0 7 * * * /home/pi/tv-cec-scheduler/tv_cec.py on && sleep 3 && /home/pi/tv-cec-scheduler/tv_cec.py active-source
0 23 * * * /home/pi/tv-cec-scheduler/tv_cec.py off
```

### Option B: systemd timers

```bash
sudo cp tv-off.service tv-off.timer tv-morning.service tv-morning.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tv-off.timer
sudo systemctl enable --now tv-morning.timer
```

```bash
systemctl list-timers | grep tv-
```

Edit the `ExecStart` paths in the `.service` files if your username or
install path differs from `/home/pi/tv-cec-scheduler/`.

## Troubleshooting

- `cec-client not found`: rerun `install.sh`, or `sudo apt install cec-utils`.
- Commands silently do nothing: confirm CEC is enabled on the TV, and
  that you're plugged directly into a TV port (not through a
  non-CEC-passthrough switch/splitter).
- Logical address 0 not responding: run `./tv_cec.py scan` and confirm
  the TV shows up on the bus - if not, it's a TV-side CEC setting issue,
  not a script issue.
- `install.sh` reports missing files: re-transfer just those files into
  the folder (drag the whole project folder rather than individual files
  next time) and run `./install.sh` again.
- Log file for CLI commands: `~/tv_cec.log` (in your home directory).
- Web app log: `tv_cec_web.log` (inside the project folder). Per-cycle
  run history also shows under each entry in the Schedule and Calendar
  tabs.
- Web app won't load / `TemplateNotFound` error: confirm `templates/`
  and `static/` are actual subfolders here, not files sitting loose in
  the project folder - `find . -type f` should show `templates/index.html`
  and `static/app.js`/`static/style.css` nested, not at the top level.
  Re-run `install.sh`, which fixes this automatically if it can.

### Warning image doesn't display

Framebuffer/VT access is the most hardware- and OS-dependent part of this
setup. Before relying on the scheduled feature, SSH in and test manually:

```bash
sudo fbi -d /dev/fb0 -T 1 -a static/uploads/warning.png
```
(Ctrl+C to exit.) If that shows the image on the TV, the scheduled
version should work too, since the app runs the same command. If it
doesn't:

- Confirm you're on **Raspberry Pi OS Lite** booted to a console, not the
  Desktop image - a desktop environment normally owns the display and
  can conflict with direct framebuffer writes.
- Try without `-T 1` (some setups don't need an explicit VT).
- Confirm `fbi` is installed: `sudo apt install fbi`.
- Check `/dev/fb0` exists: `ls /dev/fb0`. If not, your display config
  may need a `dtoverlay` adjusted in `/boot/firmware/config.txt` - this
  varies by Pi OS version.

This is genuinely fiddly across different Pi OS versions and display
configs, so expect a bit of trial and error the first time.
