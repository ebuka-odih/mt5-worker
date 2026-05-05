#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="/Applications/MetaTrader 5.app"
WINE="$APP_BUNDLE/Contents/SharedSupport/wine/bin/wine64"
WINEPREFIX_DIR="${WINEPREFIX:-$HOME/Library/Application Support/net.metaquotes.wine.metatrader5}"
PYTHON_EXE_WIN="C:\\Python311\\python.exe"

run_native_brain() {
  source "$ROOT_DIR/.venv/bin/activate"
  PYTHONPATH="$ROOT_DIR" exec python "$ROOT_DIR/scripts/run_brain.py"
}

run_vendor_brain() {
  PYTHONPATH="$ROOT_DIR:$ROOT_DIR/vendor/site-packages" exec /usr/bin/python3 "$ROOT_DIR/scripts/run_brain.py"
}

run_wine_brain() {
  echo "Falling back to Wine Python because native Python is missing or unavailable."
  cd "$ROOT_DIR"
  WINEPREFIX="$WINEPREFIX_DIR" exec "$WINE" "$PYTHON_EXE_WIN" "Z:$ROOT_DIR\\scripts\\run_brain.py"
}

cd "$ROOT_DIR"

if [[ -d ".venv" ]]; then
  run_native_brain
fi

if [[ -d "$ROOT_DIR/vendor/site-packages" ]]; then
  run_vendor_brain
fi

if [[ ! -x "$WINE" || ! -f "$WINEPREFIX_DIR/drive_c/Python311/python.exe" ]]; then
  echo "No usable native Python environment found, and Wine Python is unavailable." >&2
  echo "Either create .venv and install requirements-brain.txt or run scripts/setup_macos_mt5_worker.sh first." >&2
  exit 1
fi

run_wine_brain
