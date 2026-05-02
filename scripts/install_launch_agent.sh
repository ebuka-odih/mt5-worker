#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_NAME="com.gnosis.mt5-brain"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$AGENT_NAME.plist"
RUNTIME_DIR="$HOME/.codex/memories/mt5-worker-runtime"
LOG_DIR="$RUNTIME_DIR/.logs"
STDOUT_PATH="$LOG_DIR/brain.stdout.log"
STDERR_PATH="$LOG_DIR/brain.stderr.log"

mkdir -p "$LAUNCH_AGENTS_DIR" "$RUNTIME_DIR" "$LOG_DIR"
rm -rf "$RUNTIME_DIR/.venv"

rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.pytest_cache' \
  --exclude '__pycache__' \
  "$ROOT_DIR/" "$RUNTIME_DIR/"

if [[ ! -d "$RUNTIME_DIR/.venv" ]]; then
  /usr/bin/python3 -m venv "$RUNTIME_DIR/.venv"
fi

"$RUNTIME_DIR/.venv/bin/pip" install --upgrade pip
"$RUNTIME_DIR/.venv/bin/pip" install -r "$RUNTIME_DIR/requirements-brain.txt"

cat >"$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$AGENT_NAME</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$RUNTIME_DIR/scripts/run_macos_brain.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$RUNTIME_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$STDOUT_PATH</string>
  <key>StandardErrorPath</key>
  <string>$STDERR_PATH</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/$AGENT_NAME"

echo "Installed launch agent at $PLIST_PATH"
echo "runtime dir: $RUNTIME_DIR"
echo "stdout log: $STDOUT_PATH"
echo "stderr log: $STDERR_PATH"
