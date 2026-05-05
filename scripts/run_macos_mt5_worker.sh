#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="/Applications/MetaTrader 5.app"
WINE_BIN="$APP_BUNDLE/Contents/SharedSupport/wine/bin"
WINE="$WINE_BIN/wine64"
WINEPREFIX_DIR="${WINEPREFIX:-$HOME/Library/Application Support/net.metaquotes.wine.metatrader5}"
TERMINAL_EXE_WIN="C:\\Program Files\\MetaTrader 5\\terminal64.exe"
PYTHON_EXE_WIN="C:\\Python311\\python.exe"
ENV_FILE="$ROOT_DIR/mt5-worker/.env"

to_wine_path() {
  local posix_path="$1"
  printf 'Z:%s' "${posix_path//\//\\}"
}

if [[ ! -x "$WINE" ]]; then
  echo "Missing Wine runtime at: $WINE" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing worker env file at: $ENV_FILE" >&2
  echo "Create it from mt5-worker/.env.macos.example" >&2
  exit 1
fi

if [[ ! -f "$WINEPREFIX_DIR/drive_c/Python311/python.exe" ]]; then
  echo "Missing Windows Python in the MT5 prefix." >&2
  echo "Run scripts/setup_macos_mt5_worker.sh first." >&2
  exit 1
fi

echo "Starting MetaTrader 5 terminal in the MT5 Wine prefix..."
WINEPREFIX="$WINEPREFIX_DIR" "$WINE" "$TERMINAL_EXE_WIN" >/tmp/mt5-terminal.log 2>&1 &
sleep 5

echo "Starting worker..."
cd "$ROOT_DIR/mt5-worker"
WORKER_SCRIPT_WIN="$(to_wine_path "$ROOT_DIR/mt5-worker/windows_mt5_worker.py")"
WINEPREFIX="$WINEPREFIX_DIR" "$WINE" "$PYTHON_EXE_WIN" "$WORKER_SCRIPT_WIN"
