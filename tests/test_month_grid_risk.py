from __future__ import annotations

from brain.risk.funded_challenge import (
    AccountRiskSnapshot,
    PositionExposure,
    daily_loss_budget,
    evaluate_entry_guard,
    estimate_margin_usage_pct,
    max_drawdown_budget,
    per_grid_level_risk_budget,
)
from shared.settings import Settings, load_settings


def test_month_grid_config_targets_30_day_bybit_btc_eth_and_1000_levels() -> None:
    settings = load_settings()

    assert settings.market_data.provider == "bybit"
    assert settings.market_data.candles_period == "30d"
    assert settings.market_data.candles_interval == "1h"
    assert settings.market_data.symbols == ["BTCUSD", "ETHUSD"]
    assert settings.grid_strike.levels_each_side == 500
    assert settings.grid_strike.levels_each_side * 2 == 1000


def test_funded_challenge_total_drawdown_budget_caps_10000_balance_at_2000() -> None:
    settings = Settings()
    settings.risk.starting_balance = 10_000
    settings.risk.max_total_drawdown_pct = 20.0
    settings.risk.challenge_min_days = 30
    settings.risk.challenge_max_days = 60

    assert max_drawdown_budget(settings.risk.starting_balance, settings.risk) == 2_000
    assert daily_loss_budget(settings.risk.starting_balance, settings.risk, days=30) == 66.67
    assert daily_loss_budget(settings.risk.starting_balance, settings.risk, days=60) == 33.33


def test_1000_level_grid_risk_budget_does_not_allow_2pct_on_every_level() -> None:
    settings = Settings()
    settings.risk.starting_balance = 10_000
    settings.risk.max_total_drawdown_pct = 20.0

    assert per_grid_level_risk_budget(10_000, settings.risk, total_levels=1000) == 2.0


def test_entry_guard_blocks_daily_drawdown_breach_before_new_entries() -> None:
    settings = Settings()
    settings.risk.funded_challenge_mode = True
    settings.risk.starting_balance = 10_000
    settings.risk.daily_loss_budget = 100
    settings.risk.max_daily_loss_pct = 2.0

    decision = evaluate_entry_guard(
        "BTCUSD",
        "buy",
        AccountRiskSnapshot(balance=10_000, equity=9_890, positions=[]),
        settings.risk,
    )

    assert decision.allowed is False
    assert "daily drawdown" in decision.reason


def test_entry_guard_blocks_same_side_inventory_skew() -> None:
    settings = Settings()
    settings.risk.max_positions_per_symbol = 10
    settings.risk.max_same_side_positions = 2
    settings.risk.max_directional_skew = 2

    decision = evaluate_entry_guard(
        "BTCUSD",
        "buy",
        AccountRiskSnapshot(
            balance=10_000,
            equity=10_000,
            positions=[
                PositionExposure(symbol="BTCUSD", side="buy", lots=0.01, entry_price=100_000),
                PositionExposure(symbol="ETHUSD", side="buy", lots=0.10, entry_price=3_000),
            ],
        ),
        settings.risk,
    )

    assert decision.allowed is False
    assert "max buy inventory" in decision.reason


def test_margin_usage_estimate_reflects_open_positions() -> None:
    settings = Settings()
    settings.risk.leverage = 10

    margin_usage_pct = estimate_margin_usage_pct(
        AccountRiskSnapshot(
            balance=10_000,
            equity=10_000,
            positions=[
                PositionExposure(symbol="BTCUSD", side="buy", lots=0.5, entry_price=100_000),
            ],
        ),
        settings.risk,
    )

    assert margin_usage_pct == 50.0
