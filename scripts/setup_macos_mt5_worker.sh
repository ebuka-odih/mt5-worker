#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="/Applications/MetaTrader 5.app"
WINE_BIN="$APP_BUNDLE/Contents/SharedSupport/wine/bin"
WINE="$WINE_BIN/wine64"
WINEPREFIX_DIR="${WINEPREFIX:-$HOME/Library/Application Support/net.metaquotes.wine.metatrader5}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11.9}"
PYTHON_EMBED_ZIP="python-${PYTHON_VERSION}-embed-amd64.zip"
PYTHON_EMBED_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/${PYTHON_EMBED_ZIP}"
GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"
PYTHON_ROOT_WIN="C:\\Python311"
PYTHON_EXE_WIN="${PYTHON_ROOT_WIN}\\python.exe"
PYTHON_EXE_UNIX="$WINEPREFIX_DIR/drive_c/Python311/python.exe"
PYTHON_ROOT_UNIX="$WINEPREFIX_DIR/drive_c/Python311"
EMBED_CACHE="${TMPDIR:-/tmp}/${PYTHON_EMBED_ZIP}"
GET_PIP_CACHE="${TMPDIR:-/tmp}/get-pip.py"

to_wine_path() {
  local posix_path="$1"
  printf 'Z:%s' "${posix_path//\//\\}"
}

if [[ ! -x "$WINE" ]]; then
  echo "Missing Wine runtime at: $WINE" >&2
  exit 1
fi

if [[ ! -d "$WINEPREFIX_DIR" ]]; then
  echo "Missing MT5 Wine prefix at: $WINEPREFIX_DIR" >&2
  echo "Launch MetaTrader 5 once before running this script." >&2
  exit 1
fi

if [[ ! -f "$EMBED_CACHE" ]]; then
  echo "Downloading embeddable Windows Python ${PYTHON_VERSION}..."
  curl -L "$PYTHON_EMBED_URL" -o "$EMBED_CACHE"
fi

if [[ ! -f "$GET_PIP_CACHE" ]]; then
  echo "Downloading get-pip.py..."
  curl -L "$GET_PIP_URL" -o "$GET_PIP_CACHE"
fi

echo "Installing embeddable Windows Python into the MT5 Wine prefix..."
mkdir -p "$PYTHON_ROOT_UNIX"
unzip -oq "$EMBED_CACHE" -d "$PYTHON_ROOT_UNIX"

PYTHON_PTH_FILE="$(find "$PYTHON_ROOT_UNIX" -maxdepth 1 -name 'python*._pth' | head -n 1)"
if [[ -z "$PYTHON_PTH_FILE" ]]; then
  echo "Unable to locate python._pth in $PYTHON_ROOT_UNIX" >&2
  exit 1
fi

python3 - <<'PY' "$PYTHON_PTH_FILE"
from pathlib import Path
import sys

pth = Path(sys.argv[1])
lines = pth.read_text().splitlines()
updated = []
has_site_packages = False

for line in lines:
    stripped = line.strip()
    if stripped == "#import site":
        updated.append("import site")
        continue
    updated.append(line)
    if stripped == "Lib\\site-packages":
        has_site_packages = True

if not has_site_packages:
    updated.append("Lib\\site-packages")

pth.write_text("\n".join(updated) + "\n")
PY

if [[ ! -f "$PYTHON_EXE_UNIX" ]]; then
  echo "Windows Python install did not produce $PYTHON_EXE_UNIX" >&2
  exit 1
fi

echo "Bootstrapping pip in Wine Python..."
GET_PIP_WIN="$(to_wine_path "$GET_PIP_CACHE")"
WINEPREFIX="$WINEPREFIX_DIR" "$WINE" "$PYTHON_EXE_WIN" "$GET_PIP_WIN"
WINEPREFIX="$WINEPREFIX_DIR" "$WINE" "$PYTHON_EXE_WIN" -m pip install --upgrade pip

echo "Installing worker dependencies..."
WORKER_REQUIREMENTS_WIN="$(to_wine_path "$ROOT_DIR/mt5-worker/requirements.txt")"
WINEPREFIX="$WINEPREFIX_DIR" "$WINE" "$PYTHON_EXE_WIN" -m pip install -r "$WORKER_REQUIREMENTS_WIN"

echo "Installing brain dependencies into Wine Python for fallback runs..."
BRAIN_REQUIREMENTS_WIN="$(to_wine_path "$ROOT_DIR/requirements-brain.txt")"
WINEPREFIX="$WINEPREFIX_DIR" "$WINE" "$PYTHON_EXE_WIN" -m pip install -r "$BRAIN_REQUIREMENTS_WIN"

if [[ ! -f "$ROOT_DIR/mt5-worker/.env" ]]; then
  cp "$ROOT_DIR/mt5-worker/.env.macos.example" "$ROOT_DIR/mt5-worker/.env"
  echo "Created mt5-worker/.env from .env.macos.example"
fi

echo "Done."
echo "Windows Python: $PYTHON_EXE_UNIX"
echo "Next:"
echo "  1. Edit $ROOT_DIR/mt5-worker/.env"
echo "  2. Create a native macOS Python 3.10+ venv for the brain if available"
echo "  3. Run scripts/run_macos_brain.sh"
echo "  4. Run scripts/run_macos_mt5_worker.sh"
