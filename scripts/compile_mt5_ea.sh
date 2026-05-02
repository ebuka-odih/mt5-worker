#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="/Applications/MetaTrader 5.app"
WINE="$APP_BUNDLE/Contents/SharedSupport/wine/bin/wine64"
WINEPREFIX_DIR="${WINEPREFIX:-$HOME/Library/Application Support/net.metaquotes.wine.metatrader5}"
MT5_ROOT_UNIX="$WINEPREFIX_DIR/drive_c/Program Files/MetaTrader 5"
METAEDITOR_EXE_WIN="C:\\Program Files\\MetaTrader 5\\metaeditor64.exe"
EXPERTS_DIR_UNIX="$MT5_ROOT_UNIX/MQL5/Experts"
FILES_DIR_UNIX="$MT5_ROOT_UNIX/MQL5/Files"
LOG_DIR_UNIX="$MT5_ROOT_UNIX/MQL5/Logs"
SOURCE_MQ5="$ROOT_DIR/mt5-worker/mql5/Mt5WorkerBridgeEA.mq5"
SOURCE_ENV="$ROOT_DIR/mt5-worker/mql5/mt5-worker.env"
TARGET_MQ5_UNIX="$EXPERTS_DIR_UNIX/Mt5WorkerBridgeEA.mq5"
TARGET_EX5_UNIX="$EXPERTS_DIR_UNIX/Mt5WorkerBridgeEA.ex5"
TARGET_LOG_UNIX="$LOG_DIR_UNIX/compile-Mt5WorkerBridgeEA.log"

to_wine_path() {
  local posix_path="$1"
  printf 'Z:%s' "${posix_path//\//\\}"
}

if [[ ! -x "$WINE" ]]; then
  echo "Missing Wine runtime at: $WINE" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_MQ5" ]]; then
  echo "Missing EA source at: $SOURCE_MQ5" >&2
  exit 1
fi

cd "$ROOT_DIR"

if [[ -d "$ROOT_DIR/.venv" ]]; then
  source "$ROOT_DIR/.venv/bin/activate"
fi

PYTHONPATH="$ROOT_DIR" python "$ROOT_DIR/scripts/sync_mt5_config.py"

mkdir -p "$EXPERTS_DIR_UNIX" "$FILES_DIR_UNIX" "$LOG_DIR_UNIX"
cp "$SOURCE_MQ5" "$TARGET_MQ5_UNIX"
cp "$SOURCE_ENV" "$FILES_DIR_UNIX/mt5-worker.env"

TARGET_MQ5_WIN="$(to_wine_path "$TARGET_MQ5_UNIX")"
MQL5_ROOT_WIN='C:\Program Files\MetaTrader 5\MQL5'
TARGET_LOG_WIN="$(to_wine_path "$TARGET_LOG_UNIX")"

WINEPREFIX="$WINEPREFIX_DIR" "$WINE" "$METAEDITOR_EXE_WIN" \
  /compile:"$TARGET_MQ5_WIN" \
  /inc:"$MQL5_ROOT_WIN" \
  /log:"$TARGET_LOG_WIN"

if [[ ! -f "$TARGET_EX5_UNIX" ]]; then
  echo "Compilation did not produce $TARGET_EX5_UNIX" >&2
  [[ -f "$TARGET_LOG_UNIX" ]] && cat "$TARGET_LOG_UNIX"
  exit 1
fi

echo "Compiled EA to $TARGET_EX5_UNIX"
if [[ -f "$TARGET_LOG_UNIX" ]]; then
  echo
  echo "Compiler log:"
  cat "$TARGET_LOG_UNIX"
fi
