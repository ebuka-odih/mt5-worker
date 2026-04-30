from __future__ import annotations

import pandas as pd

from brain.simulation.grid_dry_run import GridSimulationConfig, run_grid_simulation


def _candles(rows: list[tuple[float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [close for close, _, _ in rows],
            "High": [high for _, high, _ in rows],
            "Low": [low for _, _, low in rows],
            "Close": [close for close, _, _ in rows],
            "Volume": [1] * len(rows),
        },
        index=pd.date_range("2026-01-01", periods=len(rows), freq="h", tz="UTC"),
    )


def test_tp_profit_uses_pip_distance_not_full_stop_risk() -> None:
    candles = _candles(
        [
            (100.0, 100.0, 99.0),   # buy limit at 99 fills
            (124.0, 124.0, 98.5),   # TP at 124 hits before SL 49
        ]
    )
    cfg = GridSimulationConfig(
        starting_balance=10_000,
        grid_spacing=1,
        take_profit_spacing=25,
        stop_loss_spacing=50,
        risk_per_order=100,
        max_active_orders=1,
        max_new_orders_per_bar=1,
        allowed_sides=("buy",),
        pip_size=1.0,
        contract_size_per_lot=1.0,
        spread_pips=0,
        round_trip_cost_per_order=0,
        trend_guard_pct=999,
    )

    result = run_grid_simulation(candles, cfg)

    # A 25-pip TP against a 50-pip stop should earn $50 when the stop risk is $100.
    assert result.realized_pnl == 50.0


def test_spread_pips_reduce_closed_trade_result() -> None:
    candles = _candles(
        [
            (100.0, 100.0, 99.0),
            (124.0, 124.0, 98.5),
        ]
    )
    base = GridSimulationConfig(
        starting_balance=10_000,
        grid_spacing=1,
        take_profit_spacing=25,
        stop_loss_spacing=50,
        risk_per_order=100,
        max_active_orders=1,
        max_new_orders_per_bar=1,
        allowed_sides=("buy",),
        pip_size=1.0,
        contract_size_per_lot=1.0,
        round_trip_cost_per_order=0,
        trend_guard_pct=999,
    )

    no_spread = run_grid_simulation(candles, GridSimulationConfig(**{**base.__dict__, "spread_pips": 0}))
    with_spread = run_grid_simulation(candles, GridSimulationConfig(**{**base.__dict__, "spread_pips": 2}))

    # Risk $100 over 50 pips => $2/pip. Two spread pips should cost $4 round trip.
    assert no_spread.realized_pnl == 50.0
    assert with_spread.realized_pnl == 46.0


def test_leverage_margin_usage_blocks_orders_before_active_order_cap() -> None:
    candles = _candles(
        [
            (50_000.0, 50_000.0, 49_000.0),
            (50_000.0, 50_000.0, 49_000.0),
        ]
    )
    cfg = GridSimulationConfig(
        starting_balance=10_000,
        grid_spacing=100,
        take_profit_spacing=100,
        stop_loss_spacing=1000,
        risk_per_order=1000,
        max_active_orders=10,
        max_new_orders_per_bar=10,
        allowed_sides=("buy",),
        pip_size=1.0,
        contract_size_per_lot=1.0,
        leverage=2.0,
        max_margin_usage_pct=25.0,
        trend_guard_pct=999,
    )

    result = run_grid_simulation(candles, cfg)

    assert result.max_active_orders < 10
    assert result.margin_block_events > 0
    assert result.max_margin_used <= 2500.0
