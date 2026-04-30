from __future__ import annotations

import pandas as pd

from brain.simulation.grid_dry_run import GridSimulationConfig, run_grid_simulation


def candles(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": values,
            "High": [v + 50 for v in values],
            "Low": [v - 50 for v in values],
            "Close": values,
            "Volume": [1] * len(values),
        },
        index=pd.date_range("2026-01-01", periods=len(values), freq="h", tz="UTC"),
    )


def test_simulator_respects_20pct_drawdown_kill_switch() -> None:
    cfg = GridSimulationConfig(
        starting_balance=10_000,
        max_total_drawdown_pct=20,
        max_active_orders=20,
        daily_loss_budget=9999,
        grid_spacing=25,
        take_profit_spacing=25,
        stop_loss_spacing=150,
        risk_per_order=200,
        trend_guard_pct=999,
        allowed_sides=("buy",),
    )

    result = run_grid_simulation(candles([10_000, 9_800, 9_600, 9_400, 9_200, 9_000, 8_800]), cfg)

    assert result.stopped is True
    assert result.stop_reason == "max_drawdown"
    assert result.max_drawdown <= 2_000
    assert result.balance >= 8_000


def test_simulator_limits_active_window_instead_of_placing_all_1000_levels() -> None:
    cfg = GridSimulationConfig(
        starting_balance=10_000,
        total_grid_levels=1000,
        max_active_orders=30,
        grid_spacing=25,
        take_profit_spacing=25,
        stop_loss_spacing=250,
        risk_per_order=10,
    )

    result = run_grid_simulation(candles([10_000, 10_020, 10_010, 10_030, 10_000]), cfg)

    assert result.max_active_orders <= 30
    assert result.total_grid_levels == 1000


def test_simulator_pauses_after_daily_loss_budget_is_hit() -> None:
    cfg = GridSimulationConfig(
        starting_balance=10_000,
        daily_loss_budget=50,
        max_active_orders=10,
        grid_spacing=25,
        take_profit_spacing=25,
        stop_loss_spacing=75,
        risk_per_order=60,
        trend_guard_pct=999,
        allowed_sides=("sell",),
    )

    result = run_grid_simulation(candles([10_000, 10_100, 10_200, 10_300]), cfg)

    assert result.pause_events >= 1
    assert result.new_orders_blocked >= 1
