from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def latest_log_line(log_dir: Path, needle: str) -> tuple[Path | None, str | None]:
    if not log_dir.exists():
        return None, None

    for path in sorted(log_dir.glob("*.log"), reverse=True):
        text = path.read_text(encoding="utf-16le", errors="ignore")
        matches = [line.replace("\x00", "").strip() for line in text.splitlines() if needle in line]
        if matches:
            return path, matches[-1]
    return None, None


def fetch_health(url: str) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def main() -> None:
    root_dir = Path(__file__).resolve().parent.parent
    mt5_root = (
        Path.home()
        / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5"
    )

    local_env = root_dir / "mt5-worker" / ".env"
    mt5_env = mt5_root / "Files" / "mt5-worker.env"
    experts_dir = mt5_root / "Experts"
    logs_dir = mt5_root / "Logs"

    local_cfg = read_env_file(local_env)
    mt5_cfg = read_env_file(mt5_env)
    api_base = local_cfg.get("VPS_API_BASE", "http://127.0.0.1:8780").rstrip("/")
    health = fetch_health(f"{api_base}/health")
    log_path, log_line = latest_log_line(logs_dir, "Mt5WorkerBridgeEA started.")

    print(f"Local env:      {local_env}")
    print(f"MT5 env:        {mt5_env}")
    print(f"EA binary:      {experts_dir / 'Mt5WorkerBridgeEA.ex5'}")
    print(f"Config dry run: local={local_cfg.get('DRY_RUN', '<missing>')} mt5={mt5_cfg.get('DRY_RUN', '<missing>')}")

    if health is None:
        print(f"Brain health:   unavailable at {api_base}/health")
    else:
        print(f"Brain health:   ok mode={health.get('mode')} workers={health.get('workers')} signals={health.get('signals')}")

    if log_path is None or log_line is None:
        print("EA log status:  no 'Mt5WorkerBridgeEA started.' line found")
    else:
        print(f"EA log file:    {log_path}")
        print(f"EA last start:  {log_line}")


if __name__ == "__main__":
    main()
