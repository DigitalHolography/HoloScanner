#!/usr/bin/env bash
set -euo pipefail

APP_NAME="HoloScanner"

rm -rf build dist *.spec

if [ ! -d "venv" ]; then
    python -m venv venv
fi

source venv/Scripts/activate

python -m pip install --upgrade pip
python -m pip install -e ".[build]"

pyinstaller \
    --noconfirm \
    --clean \
    --onefile \
    --windowed \
    --name "$APP_NAME" \
    holo_scanner.py

echo ""
echo "Built:"
echo "dist/$APP_NAME.exe"