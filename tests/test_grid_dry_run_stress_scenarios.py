import math

import pandas as pd

from brain.simulation.grid_dry_run import GridSimulationConfig, run_grid_simulation, run_portfolio_grid_simulation


def candles_from_prices(prices):
    idx = pd.date_range("2026-02-01", periods=len(prices), freq="1h", tz="UTC")
    prev = prices[0]
    rows = []
    for price in prices:
        high = max(prev, price) + abs(price - prev) * 0.25 + 10
        low = min(prev, price) - abs(price - prev) * 0.25 - 10
        rows.append({"Open": prev, "High": high, "Low": low, "Close": price})
        prev = price
    return pd.DataFrame(rows, index=idx)


def one_way_crash(base=75_000, bars=80, step=180):
    return [base - i * step + 50 * math.sin(i / 2) for i in range(bars)]


def high_cost_saw(base=75_000, bars=120, amp=450):
    return [base + (amp if (i // 6) % 2 else -amp) + 80 * math.sin(i) for i in range(bars)]


def sideways_range(base=75_000, bars=120, amp=300):
    return [base + amp * math.sin(i / 3) for i in range(bars)]


def one_way_rally(base=75_000, bars=80, step=180):
    return [base + i * step + 50 * math.sin(i / 2) for i in range(bars)]


def eth_one_way_crash(base=2_250, bars=80, step=5):
    return [base - i * step + math.sin(i / 2) for i in range(bars)]


def eth_config(**overrides):
    return base_config(
        grid_spacing=3,
        take_profit_spacing=7,
        stop_loss_spacing=40,
        spread_pips=1,
        **overrides,
    )


def base_config(**overrides):
    data = dict(
        starting_balance=10_000,
        max_total_drawdown_pct=20,
        daily_loss_budget=66.67,
        total_grid_levels=1000,
        max_active_orders=30,
        grid_spacing=75,
        take_profit_spacing=150,
        stop_loss_spacing=750,
        risk_per_order=25,
        trend_guard_bars=6,
        trend_guard_pct=99,
        max_new_orders_per_bar=4,
        max_entry_risk_pct=2,
        pip_size=1.0,
        spread_pips=15,
        contract_size_per_lot=1.0,
        leverage=10,
        max_margin_usage_pct=50,
    )
    data.update(overrides)
    return GridSimulationConfig(**data)


def test_sideways_range_can_profit_without_breaching_daily_or_total_drawdown():
    result = run_grid_simulation(candles_from_prices(sideways_range()), base_config())

    assert result.orders_opened > 0
    assert result.orders_closed_tp > result.orders_closed_sl
    assert result.realized_pnl > 0
    assert result.max_drawdown < 100
    assert not result.stopped


def test_pre_existing_long_grid_orders_are_hit_during_one_way_crash():
    result = run_grid_simulation(
        candles_from_prices(one_way_crash()),
        base_config(allowed_sides=("buy",), daily_loss_budget=99999),
    )

    assert result.orders_opened > 0
    assert result.orders_closed_sl > 0
    assert result.realized_pnl < 0
    assert result.max_drawdown > 0


def test_pre_existing_short_grid_orders_are_hit_during_one_way_rally():
    result = run_grid_simulation(
        candles_from_prices(one_way_rally()),
        base_config(allowed_sides=("sell",), daily_loss_budget=99999),
    )

    assert result.orders_opened > 0
    assert result.orders_closed_sl > 0
    assert result.realized_pnl < 0
    assert result.stopped
    assert result.stop_reason == "max_drawdown"


def test_tighter_trend_guard_blocks_most_adverse_crash_entries():
    result = run_grid_simulation(
        candles_from_prices(one_way_crash()),
        base_config(allowed_sides=("buy",), trend_guard_pct=0.75),
    )

    assert result.trend_guard_events > 0
    assert result.new_orders_blocked > result.orders_opened
    assert result.max_drawdown < 500


def test_high_spread_tight_grid_can_be_unprofitable_and_trigger_pause():
    result = run_grid_simulation(
        candles_from_prices(high_cost_saw()),
        base_config(
            grid_spacing=50,
            take_profit_spacing=70,
            stop_loss_spacing=500,
            spread_pips=60,
            round_trip_cost_per_order=1.0,
        ),
    )

    assert result.orders_opened > 0
    assert result.realized_pnl < 0
    assert result.pause_events > 0


def test_margin_throttle_blocks_new_orders_before_overusing_account_margin():
    result = run_grid_simulation(
        candles_from_prices(sideways_range(amp=800)),
        base_config(risk_per_order=200, max_margin_usage_pct=3, spread_pips=10),
    )

    assert result.orders_opened == 0
    assert result.margin_block_events > 0
    assert result.new_orders_blocked == result.margin_block_events
    assert result.max_margin_used == 0


def test_correlated_btc_eth_long_crash_can_hit_shared_funded_drawdown_limit():
    result = run_portfolio_grid_simulation(
        {
            "BTCUSD": candles_from_prices(one_way_crash()),
            "ETHUSD": candles_from_prices(eth_one_way_crash()),
        },
        {
            "BTCUSD": base_config(allowed_sides=("buy",), daily_loss_budget=99999),
            "ETHUSD": eth_config(allowed_sides=("buy",), daily_loss_budget=99999),
        },
    )

    assert result.orders_opened > 0
    assert result.orders_closed_sl > 0
    assert result.realized_pnl <= -2_000
    assert result.stopped
    assert result.stop_reason == "max_drawdown"
    assert result.max_drawdown >= 2_000
