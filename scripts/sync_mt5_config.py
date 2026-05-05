from __future__ import annotations

import argparse
import os
from pathlib import Path

from shared.settings import load_settings


def read_existing_env(root_dir: Path) -> dict[str, str]:
    env_path = root_dir / "mt5-worker" / ".env"
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def read_existing_dry_run(root_dir: Path, default: bool = True) -> bool:
    return read_existing_env(root_dir).get("DRY_RUN", str(default)).lower() == "true"


def render_env_lines(
    api_base: str,
    token: str,
    worker_id: str = "macos-mt5-local-01",
    dry_run: bool = True,
    magic_number: int = 552501,
    poll_seconds: int = 1,
    heartbeat_seconds: int = 10,
    request_timeout_ms: int = 5000,
) -> list[str]:
    return [
        f"VPS_API_BASE={api_base.rstrip('/')}",
        f"WORKER_TOKEN={token}",
        f"WORKER_ID={worker_id}",
        f"DRY_RUN={'true' if dry_run else 'false'}",
        f"MT5_MAGIC={magic_number}",
        f"POLL_SECONDS={poll_seconds}",
        f"HEARTBEAT_SECONDS={heartbeat_seconds}",
        f"REQUEST_TIMEOUT_MS={request_timeout_ms}",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync MT5 worker config files for the Python worker and MT5 EA bridge."
    )
    parser.add_argument(
        "--api-base",
        default=os.getenv("VPS_API_BASE"),
        help="Worker API base URL. Defaults to VPS_API_BASE env var or local config port.",
    )
    parser.add_argument(
        "--worker-id",
        default=os.getenv("WORKER_ID"),
        help="Worker identifier written into each config file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write DRY_RUN=true to the synced worker configs.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Write DRY_RUN=false to the synced worker configs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root_dir = Path(__file__).resolve().parent.parent
    settings = load_settings(root_dir / "config/settings.yaml")
    existing_env = read_existing_env(root_dir)
    if args.dry_run and args.live:
        raise SystemExit("Choose either --dry-run or --live, not both.")

    api_base = args.api_base or existing_env.get("VPS_API_BASE") or f"http://127.0.0.1:{settings.api.port}"
    dry_run = read_existing_dry_run(root_dir)
    if args.live:
        dry_run = False
    elif args.dry_run:
        dry_run = True

    lines = render_env_lines(
        api_base=api_base,
        token=settings.api.worker_token,
        worker_id=args.worker_id or existing_env.get("WORKER_ID", "macos-mt5-local-01"),
        dry_run=dry_run,
        magic_number=settings.mt5_worker.magic_number,
        poll_seconds=settings.mt5_worker.poll_seconds,
        heartbeat_seconds=settings.mt5_worker.heartbeat_seconds,
    )
    body = "\n".join(lines) + "\n"

    targets = [
        root_dir / "mt5-worker" / ".env",
        root_dir / "mt5-worker" / "mql5" / "mt5-worker.env",
        Path.home()
        / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Files/mt5-worker.env",
        Path.home()
        / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/mt5-worker.env",
        Path.home()
        / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/gnosis/AppData/Roaming/MetaQuotes/Terminal/Common/Files/mt5-worker.env",
    ]

    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        print(f"Updated {target}")


if __name__ == "__main__":
    main()
