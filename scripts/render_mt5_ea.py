from __future__ import annotations

import re
from pathlib import Path

from scripts.sync_mt5_config import read_existing_env


def _mql_bool(value: bool) -> str:
    return "true" if value else "false"


def render_ea_source(template: str, env: dict[str, str]) -> str:
    replacements = {
        "ApiBase": f"input string ApiBase = \"{env['VPS_API_BASE']}\";",
        "WorkerToken": f"input string WorkerToken = \"{env['WORKER_TOKEN']}\";",
        "WorkerId": f"input string WorkerId = \"{env['WORKER_ID']}\";",
        "DryRun": f"input bool DryRun = {_mql_bool(env['DRY_RUN'].lower() == 'true')};",
        "MagicNumber": f"input long MagicNumber = {env['MT5_MAGIC']};",
        "PollSeconds": f"input int PollSeconds = {env['POLL_SECONDS']};",
        "HeartbeatSeconds": f"input int HeartbeatSeconds = {env['HEARTBEAT_SECONDS']};",
        "RequestTimeoutMs": f"input int RequestTimeoutMs = {env['REQUEST_TIMEOUT_MS']};",
    }

    rendered = template
    for key, line in replacements.items():
        rendered = re.sub(rf"^input .+ {key} = .+;$", line, rendered, flags=re.MULTILINE)
    return rendered


def main() -> None:
    root_dir = Path(__file__).resolve().parent.parent
    env = read_existing_env(root_dir)
    required = {
        "VPS_API_BASE",
        "WORKER_TOKEN",
        "WORKER_ID",
        "DRY_RUN",
        "MT5_MAGIC",
        "POLL_SECONDS",
        "HEARTBEAT_SECONDS",
        "REQUEST_TIMEOUT_MS",
    }
    missing = sorted(required - set(env))
    if missing:
        raise SystemExit(f"Missing required env values for EA render: {', '.join(missing)}")

    template_path = root_dir / "mt5-worker" / "mql5" / "Mt5WorkerBridgeEA.mq5"
    target_path = (
        Path.home()
        / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Experts/Mt5WorkerBridgeEA.mq5"
    )

    rendered = render_ea_source(template_path.read_text(), env)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(rendered)
    print(f"Rendered {target_path}")


if __name__ == "__main__":
    main()
