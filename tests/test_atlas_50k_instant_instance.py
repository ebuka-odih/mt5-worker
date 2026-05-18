from __future__ import annotations

from pathlib import Path

import yaml

from brain.signals.grid_strike import GridStrikeCandidate, build_grid_plan
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
    assert settings.risk.max_open_positions == 10
    assert settings.risk.max_positions_per_symbol == 10
    assert settings.risk.max_same_side_positions == 5
    assert settings.risk.max_directional_skew == 1
    assert settings.grid_strike.levels_each_side == 50
    assert settings.grid_strike.grid_spacing == 300.0
    assert settings.grid_strike.take_profit_spacing == 300.0
    assert settings.grid_strike.stop_loss_spacing == 300.0
    assert settings.grid_strike.symbol_lots["BTCUSD"] == 0.05
    btc_override = settings.grid_strike.symbol_grid_overrides["BTCUSD"]
    assert btc_override["levels_each_side"] == 50
    assert btc_override["lower_bound"] == 60000.0
    assert btc_override["upper_bound"] == 90000.0
    assert settings.mt5_worker.magic_number == 552650
    assert settings.mt5_worker.comment_prefix == "vps_forex_brain_atlas50k"
    assert settings.api.worker_token != "CHANGE_ME_LONG_RANDOM_TOKEN"


def test_atlas_50k_btc_grid_plan_uses_sparse_100_level_range_and_safe_lots() -> None:
    settings = load_settings(PROJECT_ROOT / "config/settings.atlas-50k-instant.yaml")
    candidate = GridStrikeCandidate(
        symbol="BTCUSD",
        score=0.9,
        tradeable=True,
        market_regime="range",
        mid_price=75000.0,
        range_pct=10.0,
        trend_ratio=0.1,
        atr_pips=250.0,
        spread_pips=0.0,
        grid_spacing_pips=300.0,
        reason="test",
    )

    plan = build_grid_plan(candidate, mid_price=75000.0, settings=settings.grid_strike)

    assert plan.lots_per_level == 0.05
    assert len(plan.buy_levels) == 50
    assert len(plan.sell_levels) == 50
    assert len(plan.buy_levels) + len(plan.sell_levels) == 100
    assert plan.lower_bound == 60000.0
    assert plan.upper_bound == 90000.0
    assert plan.buy_levels[0].price == 74700.0
    assert plan.sell_levels[0].price == 75300.0


def test_atlas_50k_windows_deployment_note_mentions_new_login_and_old_runtime_safety() -> None:
    note = (PROJECT_ROOT / "docs/atlas-50k-second-login-deployment.md").read_text()

    assert "new login account" in note.lower()
    assert "old login" in note.lower()
    assert "keep the old worker/service running unchanged" in note.lower()
    assert "settings.atlas-50k-instant.yaml" in note
    assert "docker-compose.atlas-50k-instant.yml" in note
    assert ".env.atlas-50k.example" in note
    assert "--env-file .env.atlas-50k" in note
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
