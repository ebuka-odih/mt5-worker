from __future__ import annotations

import pandas as pd

from brain.simulation.grid_dry_run import GridSimulationConfig, run_portfolio_grid_simulation
from shared.settings import load_settings


def make_candles(values: list[float], wick: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": values,
            "High": [v + wick for v in values],
            "Low": [v - wick for v in values],
            "Close": values,
            "Volume": [1] * len(values),
        },
        index=pd.date_range("2026-01-01", periods=len(values), freq="h", tz="UTC"),
    )


def test_config_tracks_btc_and_eth_for_same_funded_challenge_account() -> None:
    settings = load_settings()

    assert settings.market_data.provider == "bybit"
    assert settings.market_data.symbols == ["BTCUSD", "ETHUSD"]
    assert settings.risk.starting_balance == 10_000
    assert settings.risk.max_risk_per_trade_pct == 2.0
    assert settings.risk.max_total_drawdown_pct == 20.0
    assert settings.grid_strike.levels_each_side * 2 == 1000


def test_portfolio_simulator_shares_drawdown_budget_across_btc_and_eth() -> None:
    cfg = GridSimulationConfig(
        starting_balance=10_000,
        max_total_drawdown_pct=20,
        daily_loss_budget=9999,
        max_active_orders=12,
        max_new_orders_per_bar=4,
        grid_spacing=25,
        take_profit_spacing=25,
        stop_loss_spacing=150,
        risk_per_order=200,
        trend_guard_pct=999,
        allowed_sides=("buy",),
    )

    btc = make_candles([10_000, 9_800, 9_600, 9_400, 9_200, 9_000, 8_800], wick=50)
    eth = make_candles([3_000, 2_800, 2_600, 2_400, 2_200, 2_000, 1_800], wick=50)

    result = run_portfolio_grid_simulation({"BTCUSD": btc, "ETHUSD": eth}, cfg)

    assert result.stopped is True
    assert result.stop_reason == "max_drawdown"
    assert result.max_drawdown <= 2_000
    assert result.balance >= 8_000
    assert set(result.symbol_results) == {"BTCUSD", "ETHUSD"}


def test_eth_hedge_can_stabilize_btc_drawdown_without_breaking_shared_rules() -> None:
    shared = GridSimulationConfig(
        starting_balance=10_000,
        max_total_drawdown_pct=20,
        daily_loss_budget=9999,
        max_active_orders=10,
        max_new_orders_per_bar=3,
        grid_spacing=25,
        take_profit_spacing=25,
        stop_loss_spacing=150,
        risk_per_order=50,
        trend_guard_pct=999,
        allowed_sides=("buy",),
    )
    btc_buy = GridSimulationConfig(**{**shared.__dict__, "allowed_sides": ("buy",)})
    eth_sell = GridSimulationConfig(**{**shared.__dict__, "allowed_sides": ("sell",)})

    btc_falling = make_candles([10_000, 9_875, 9_750, 9_625, 9_500, 9_375], wick=50)
    eth_falling = make_candles([3_000, 2_875, 2_750, 2_625, 2_500, 2_375], wick=50)

    btc_only = run_portfolio_grid_simulation({"BTCUSD": btc_falling}, {"BTCUSD": btc_buy})
    hedged = run_portfolio_grid_simulation({"BTCUSD": btc_falling, "ETHUSD": eth_falling}, {"BTCUSD": btc_buy, "ETHUSD": eth_sell})

    assert hedged.max_drawdown < btc_only.max_drawdown
    assert hedged.balance > btc_only.balance
    assert hedged.max_drawdown <= 2_000
    assert hedged.max_entry_risk <= 200
