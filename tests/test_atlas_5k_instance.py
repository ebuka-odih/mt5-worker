from __future__ import annotations

from pathlib import Path

import yaml

from shared.settings import load_settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_atlas_5k_settings_profile_loads_expected_rules() -> None:
    settings = load_settings(PROJECT_ROOT / "config/settings.atlas-5k.yaml")

    assert settings.app.name == "forex-mt5-bot-atlas-5k"
    assert settings.api.port == 8782
    assert settings.api.worker_token == "CHANGE_ME_ATLAS_5K_WORKER_TOKEN"
    assert settings.market_data.symbols == ["BTCUSD"]
    assert settings.risk.starting_balance == 5_000
    assert settings.risk.max_risk_per_trade_pct == 0.6
    assert settings.risk.max_daily_loss_pct == 2.0
    assert settings.risk.max_total_drawdown_pct == 4.0
    assert settings.risk.max_open_positions == 30
    assert settings.risk.max_positions_per_symbol == 30
    assert settings.risk.max_same_side_positions == 15
    assert settings.risk.max_directional_skew == 15
    assert settings.risk.default_stop_loss_pips == 600
    assert settings.risk.default_take_profit_pips == 1200
    assert settings.risk.risk_per_order == 7.5
    assert settings.risk.daily_loss_budget == 75.0
    assert settings.risk.leverage == 10.0
    assert settings.risk.max_margin_usage_pct == 35.0
    assert settings.strategy.trend_guard_pct == 2.0
    assert settings.strategy.max_new_orders_per_bar == 1
    assert settings.grid_strike.levels_each_side == 5
    assert settings.grid_strike.grid_spacing == 600.0
    assert settings.grid_strike.take_profit_spacing == 1200.0
    assert settings.grid_strike.stop_loss_spacing == 600.0
    btc_override = settings.grid_strike.symbol_grid_overrides["BTCUSD"]
    assert btc_override["levels_each_side"] == 5
    assert btc_override["lower_bound"] == 69_000.0
    assert btc_override["upper_bound"] == 90_000.0
    assert settings.grid_strike.get_lots("BTCUSD") == 0.01
    assert settings.mt5_worker.magic_number == 552701
    assert settings.mt5_worker.comment_prefix == "vps_forex_brain_atlas_5k"
    assert settings.mt5_worker.auto_close_profit_pct == 0.6
    assert settings.mt5_worker.auto_close_loss_pct == 0.0
    assert settings.mt5_worker.basket_take_profit_usd == 12.0


def test_atlas_5k_compose_file_targets_dedicated_runtime() -> None:
    compose_path = PROJECT_ROOT / "docker-compose.atlas-5k.yml"
    compose = yaml.safe_load(compose_path.read_text())

    brain = compose["services"]["brain"]
    assert brain["container_name"] == "forex-brain-atlas-5k"
    assert brain["ports"] == ["8782:8782"]
    assert "./config/settings.atlas-5k.yaml:/app/config/settings.yaml:ro" in brain["volumes"]
    assert "./data-atlas-5k:/app/data" in brain["volumes"]


def test_atlas_5k_windows_env_example_stays_safe_and_profile_specific() -> None:
    env_example = (PROJECT_ROOT / "mt5-worker/.env.atlas-5k.example").read_text()

    assert "https://CHANGE_ME_ATLAS_5K_TUNNEL_OR_HOST" in env_example
    assert "windows-mt5-atlas-5k-01" in env_example
    assert "MT5_MAGIC=552701" in env_example
    assert "WORKER_TOKEN=<paste-token-from-vps-config>" in env_example
