from __future__ import annotations

from pathlib import Path

import yaml

from shared.settings import load_settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_atlas_50k_instant_settings_profile_loads_expected_rules() -> None:
    settings = load_settings(PROJECT_ROOT / "config/settings.atlas-50k-instant.yaml")

    assert settings.app.name == "forex-mt5-bot-atlas-50k-instant"
    assert settings.api.port == 8783
    assert settings.market_data.symbols == ["BTCUSD"]
    assert settings.risk.starting_balance == 50_000
    assert settings.risk.max_daily_loss_pct == 3.0
    assert settings.risk.max_total_drawdown_pct == 5.0
    assert settings.risk.daily_loss_budget == 600.0
    assert settings.risk.risk_per_order == 125.0
    assert settings.risk.max_positions_per_symbol == 6
    assert settings.risk.max_same_side_positions == 3
    assert settings.grid_strike.levels_each_side == 3
    assert settings.grid_strike.grid_spacing == 900.0
    assert settings.grid_strike.take_profit_spacing == 1800.0
    assert settings.grid_strike.stop_loss_spacing == 900.0
    assert settings.grid_strike.symbol_lots["BTCUSD"] == 0.12
    assert settings.mt5_worker.magic_number == 552650
    assert settings.mt5_worker.comment_prefix == "vps_forex_brain_atlas50k"
    assert settings.api.worker_token == "CHANGE_ME_ATLAS_50K_INSTANT_WORKER_TOKEN"


def test_atlas_50k_windows_deployment_note_mentions_new_login_and_old_runtime_safety() -> None:
    note = (PROJECT_ROOT / "docs/atlas-50k-second-login-deployment.md").read_text()

    assert "new login account" in note.lower()
    assert "old login" in note.lower()
    assert "keep the old worker/service running unchanged" in note.lower()
    assert "settings.atlas-50k-instant.yaml" in note
    assert "docker-compose.atlas-50k-instant.yml" in note
    assert ".env.atlas-50k.example" in note
    assert "8783" in note
    assert "do not overwrite the old worker .env" in note.lower()


def test_atlas_50k_worker_env_example_exists_with_isolated_identity() -> None:
    env_text = (PROJECT_ROOT / "mt5-worker/.env.atlas-50k.example").read_text()

    assert "CHANGE_ME_ATLAS_50K_TUNNEL_OR_HOST" in env_text
    assert "CHANGE_ME_ATLAS_50K_INSTANT_WORKER_TOKEN" in env_text
    assert "windows-mt5-atlas-50k-01" in env_text
    assert "MT5_MAGIC=552650" in env_text


def test_atlas_50k_instant_compose_file_targets_dedicated_runtime() -> None:
    compose_path = PROJECT_ROOT / "docker-compose.atlas-50k-instant.yml"
    compose = yaml.safe_load(compose_path.read_text())

    brain = compose["services"]["brain"]
    assert brain["container_name"] == "forex-brain-atlas-50k-instant"
    assert brain["ports"] == ["8783:8783"]
    assert "./config/settings.atlas-50k-instant.yaml:/app/config/settings.yaml:ro" in brain["volumes"]
    assert "./data-atlas-50k-instant:/app/data" in brain["volumes"]
    assert brain["command"][-1] == "8783"
