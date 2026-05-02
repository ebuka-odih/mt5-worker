from __future__ import annotations

import pandas as pd

from brain.simulation.grid_dry_run import GridSimulationConfig, run_grid_simulation


def test_simulator_order_costs_reduce_net_result() -> None:
    df = pd.DataFrame(
        {
            "Open": [10_000, 10_000],
            "High": [10_050, 10_050],
            "Low": [9_950, 9_950],
            "Close": [10_000, 10_000],
            "Volume": [1, 1],
        },
        index=pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC"),
    )
    no_cost = run_grid_simulation(df, GridSimulationConfig(round_trip_cost_per_order=0, max_new_orders_per_bar=2, grid_spacing=30, take_profit_spacing=30, stop_loss_spacing=15))
    with_cost = run_grid_simulation(df, GridSimulationConfig(round_trip_cost_per_order=2, max_new_orders_per_bar=2, grid_spacing=30, take_profit_spacing=30, stop_loss_spacing=15))

    assert with_cost.balance < no_cost.balance


def test_simulator_throttles_new_orders_per_bar() -> None:
    df = pd.DataFrame(
        {
            "Open": [10_000],
            "High": [10_200],
            "Low": [9_800],
            "Close": [10_000],
            "Volume": [1],
        },
        index=pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC"),
    )

    result = run_grid_simulation(
        df,
        GridSimulationConfig(max_active_orders=50, max_new_orders_per_bar=3, grid_spacing=25),
    )

    assert result.orders_opened <= 3
