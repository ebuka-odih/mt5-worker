from __future__ import annotations

import pandas as pd

from brain.simulation.grid_dry_run import GridSimulationConfig, run_grid_simulation, run_portfolio_grid_simulation


def make_candles(values: list[float], wick: float = 10) -> pd.DataFrame:
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


def test_single_symbol_simulator_caps_risk_per_entry_at_funded_2pct_rule() -> None:
    cfg = GridSimulationConfig(
        starting_balance=10_000,
        max_entry_risk_pct=2.0,
        daily_loss_budget=9999,
        max_active_orders=10,
        max_new_orders_per_bar=10,
        grid_spacing=25,
        take_profit_spacing=25,
        stop_loss_spacing=75,
        risk_per_order=1_000,
        trend_guard_pct=999,
        allowed_sides=("buy",),
    )

    result = run_grid_simulation(make_candles([10_000, 9_900, 9_800], wick=30), cfg)

    assert result.orders_closed_sl >= 1
    assert result.realized_pnl >= -(200 * result.orders_closed_sl)


def test_daily_pause_uses_equity_drawdown_not_only_closed_balance() -> None:
    cfg = GridSimulationConfig(
        starting_balance=10_000,
        daily_loss_budget=20,
        max_active_orders=5,
        max_new_orders_per_bar=5,
        grid_spacing=25,
        take_profit_spacing=250,
        stop_loss_spacing=250,
        risk_per_order=100,
        trend_guard_pct=999,
        allowed_sides=("buy",),
    )
    candles = pd.DataFrame(
        {
            "Open": [10_000, 9_925, 9_925],
            "High": [10_005, 9_935, 9_935],
            "Low": [9_965, 9_915, 9_915],
            "Close": [10_000, 9_925, 9_925],
            "Volume": [1, 1, 1],
        },
        index=pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
    )

    result = run_grid_simulation(candles, cfg)

    assert result.pause_events >= 1
    assert result.new_orders_blocked >= 1


def test_portfolio_max_active_orders_is_shared_across_btc_and_eth() -> None:
    cfg = GridSimulationConfig(
        starting_balance=10_000,
        daily_loss_budget=9999,
        max_active_orders=6,
        max_new_orders_per_bar=6,
        grid_spacing=25,
        take_profit_spacing=250,
        stop_loss_spacing=250,
        risk_per_order=2,
        trend_guard_pct=999,
        allowed_sides=("buy",),
    )

    btc = make_candles([10_000, 10_000], wick=200)
    eth = make_candles([3_000, 3_000], wick=200)

    result = run_portfolio_grid_simulation({"BTCUSD": btc, "ETHUSD": eth}, cfg)

    assert result.max_active_orders <= 6
    assert result.new_orders_blocked >= 1


def test_portfolio_shared_cap_overrides_oversized_symbol_config() -> None:
    account_cfg = GridSimulationConfig(
        starting_balance=10_000,
        daily_loss_budget=9999,
        max_active_orders=6,
        max_new_orders_per_bar=4,
        grid_spacing=25,
        take_profit_spacing=250,
        stop_loss_spacing=250,
        risk_per_order=2,
        trend_guard_pct=999,
        allowed_sides=("buy",),
    )
    oversized_eth_cfg = GridSimulationConfig(**{**account_cfg.__dict__, "max_active_orders": 10, "max_new_orders_per_bar": 10})

    btc = make_candles([10_000, 10_000], wick=200)
    eth = make_candles([3_000, 3_000], wick=200)

    result = run_portfolio_grid_simulation({"BTCUSD": btc, "ETHUSD": eth}, {"BTCUSD": account_cfg, "ETHUSD": oversized_eth_cfg})

    assert result.max_active_orders <= 6
