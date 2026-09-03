#!/bin/bash
# Sets up cec-utils, fbi, and the web app's Python environment on a
# Raspberry Pi. Safe to re-run.
#
# This also repairs a common file-transfer problem: if templates/index.html
# or static/app.js and static/style.css ended up loose in this directory
# instead of nested in their subfolders (which happens if you multi-select
# individual files in an FTP client instead of dragging the whole project
# folder), this script detects that and moves them into place automatically.

set -e

echo "== Checking project layout =="

mkdir -p templates static/uploads

if [ -f "index.html" ] && [ ! -f "templates/index.html" ]; then
    echo "Found index.html loose in this folder - moving it to templates/"
    mv index.html templates/
fi

for f in app.js style.css; do
    if [ -f "$f" ] && [ ! -f "static/$f" ]; then
        echo "Found $f loose in this folder - moving it to static/"
        mv "$f" "static/"
    fi
done

if [ ! -f "requirements.txt" ]; then
    echo "requirements.txt missing - recreating it"
    cat > requirements.txt << 'REQEOF'
Flask==3.0.3
APScheduler==3.10.4
REQEOF
fi

echo ""
echo "== Verifying required files are present =="
required_files=(
    "app.py" "tv_cec.py" "display_image.py" "holidays_store.py"
    "schedule_store.py" "settings_store.py" "requirements.txt"
    "templates/index.html" "static/app.js" "static/style.css"
)
missing=0
for f in "${required_files[@]}"; do
    if [ ! -f "$f" ]; then
        echo "  MISSING: $f"
        missing=1
    fi
done

if [ "$missing" -eq 1 ]; then
    echo ""
    echo "One or more files above are missing from this directory."
    echo "Re-transfer them here (drag the whole project folder rather than"
    echo "individual files) and run ./install.sh again."
    exit 1
fi
echo "All required files present."

echo ""
echo "== Installing system packages =="
sudo apt update
sudo apt install -y cec-utils fbi python3 python3-venv fonts-dejavu-core libjpeg-dev zlib1g-dev

echo ""
echo "== Setting up Python virtual environment =="
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

chmod +x tv_cec.py

echo ""
echo "Done. Test the CEC connection first:"
echo "  ./tv_cec.py scan            # find your TV/devices and their addresses"
echo "  ./tv_cec.py on               # power on the TV"
echo "  ./tv_cec.py off              # standby"
echo ""
echo "Then test the web app (port 80 needs sudo for a manual run):"
echo "  sudo venv/bin/python3 app.py"
echo "  Visit http://<this-pi-ip>/ from another device on your network."
echo ""
echo "For it to run persistently, see the README section on installing"
echo "tv-cec-web.service with systemd."
