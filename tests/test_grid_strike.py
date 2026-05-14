from __future__ import annotations

import pandas as pd

from brain.signals.grid_strike import (
    GridStrikeSettings,
    build_grid_plan,
    pip_size,
    round_price,
    score_grid_candidate,
    scan_grid_candidates,
)
from shared.settings import Settings


def candles_from(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": values,
            "High": [v + 0.00025 for v in values],
            "Low": [v - 0.00025 for v in values],
            "Close": values,
            "Volume": [100] * len(values),
        }
    )


def candles_with_time_and_spread(values: list[float], spread_pips: float, start: str = "2026-01-01T10:00:00Z") -> pd.DataFrame:
    frame = candles_from(values)
    frame.index = pd.date_range(start, periods=len(values), freq="h", tz="UTC")
    frame["SpreadPips"] = spread_pips
    return frame


def test_score_grid_candidate_prefers_scalpable_ranging_market() -> None:
    # Tight oscillation around a stable mean: good for grid scalping.
    values = [1.1000 + (0.0008 if i % 2 else -0.0008) for i in range(96)]
    candles = candles_with_time_and_spread(values, spread_pips=0.2)

    candidate = score_grid_candidate("EURUSD", candles, GridStrikeSettings(max_spread_pips=1.0))

    assert candidate.symbol == "EURUSD"
    assert candidate.tradeable is True
    assert candidate.market_regime == "range"
    assert candidate.score >= 0.55
    assert candidate.atr_pips > 0
    assert candidate.reason


def test_score_grid_candidate_rejects_thin_flat_market() -> None:
    values = [1.1000 + (0.00002 if i % 2 else -0.00002) for i in range(96)]
    candles = candles_with_time_and_spread(values, spread_pips=0.2)

    candidate = score_grid_candidate("EURUSD", candles, GridStrikeSettings())

    assert candidate.tradeable is False
    assert "range too small" in candidate.reason.lower()


def test_score_grid_candidate_rejects_wide_spread_and_out_of_session() -> None:
    values = [1.1000 + (0.0008 if i % 2 else -0.0008) for i in range(96)]
    candles = candles_with_time_and_spread(values, spread_pips=4.0, start="2026-01-01T02:00:00Z")

    candidate = score_grid_candidate(
        "EURUSD",
        candles,
        GridStrikeSettings(max_spread_pips=1.0, session_start_hour_utc=6, session_end_hour_utc=22),
    )

    assert candidate.tradeable is False
    assert "outside configured session window" in candidate.reason.lower()
    assert "spread too wide" in candidate.reason.lower()


def test_build_grid_plan_creates_buy_and_sell_strikes_around_mid() -> None:
    candidate = score_grid_candidate("GBPUSD", candles_from([1.2500 + (0.0007 if i % 2 else -0.0007) for i in range(96)]), GridStrikeSettings())

    plan = build_grid_plan(candidate, mid_price=1.25, settings=GridStrikeSettings(levels_each_side=3))

    assert plan.symbol == "GBPUSD"
    assert plan.mid_price == 1.25
    assert len(plan.buy_levels) == 3
    assert len(plan.sell_levels) == 3
    assert all(level.price < 1.25 for level in plan.buy_levels)
    assert all(level.price > 1.25 for level in plan.sell_levels)
    assert plan.lower_bound < 1.25 < plan.upper_bound


def test_build_grid_plan_supports_symbol_specific_bounds_and_levels() -> None:
    candidate = score_grid_candidate(
        "BTCUSD",
        candles_from([80_000 + (600 if i % 2 else -600) for i in range(96)]),
        GridStrikeSettings(min_spacing_pips=50.0, max_spacing_pips=5_000.0),
    )

    plan = build_grid_plan(
        candidate,
        mid_price=80_000,
        settings=GridStrikeSettings(
            levels_each_side=3,
            symbol_lots={"BTCUSD": 0.05},
            symbol_grid_overrides={
                "BTCUSD": {
                    "levels_each_side": 1,
                    "lower_bound": 62_000,
                    "upper_bound": 90_000,
                }
            },
        ),
    )

    assert plan.symbol == "BTCUSD"
    assert plan.lots_per_level == 0.05
    assert len(plan.buy_levels) == 1
    assert len(plan.sell_levels) == 1
    assert plan.buy_levels[0].price == 62_000
    assert plan.sell_levels[0].price == 90_000
    assert plan.lower_bound == 62_000
    assert plan.upper_bound == 90_000


def test_build_grid_plan_clamps_btc_to_tight_active_window_inside_wide_bounds() -> None:
    candidate = score_grid_candidate(
        "BTCUSD",
        candles_from([70_000 + (600 if i % 2 else -600) for i in range(96)]),
        GridStrikeSettings(min_spacing_pips=50.0, max_spacing_pips=5_000.0),
    )

    plan = build_grid_plan(
        candidate,
        mid_price=70_000,
        settings=GridStrikeSettings(
            levels_each_side=5,
            symbol_grid_overrides={
                "BTCUSD": {
                    "levels_each_side": 5,
                    "lower_bound": 65_000,
                    "upper_bound": 96_000,
                }
            },
        ),
    )

    assert plan.buy_levels[0].price == 69_400
    assert plan.sell_levels[0].price == 70_600
    assert plan.lower_bound == 67_000
    assert plan.upper_bound == 73_000


def test_eth_grid_uses_crypto_pip_size_and_two_decimal_rounding() -> None:
    candidate = score_grid_candidate(
        "ETHUSD",
        candles_from([2_400 + (15 if i % 2 else -15) for i in range(96)]),
        GridStrikeSettings(min_range_pct=0.2, max_range_pct=3.0, min_spacing_pips=20.0, max_spacing_pips=5_000.0),
    )

    plan = build_grid_plan(
        candidate,
        mid_price=2_400,
        settings=GridStrikeSettings(
            levels_each_side=2,
            symbol_lots={"ETHUSD": 0.5},
            symbol_grid_overrides={
                "ETHUSD": {
                    "levels_each_side": 2,
                    "lower_bound": 1_000,
                    "upper_bound": 5_000,
                }
            },
        ),
    )

    assert pip_size("ETHUSD") == 0.01
    assert round_price("ETHUSD", 2400.126) == 2400.13
    assert candidate.atr_pips > 0
    assert candidate.atr_pips < 10_000
    assert plan.buy_levels[0].price == 1700.0
    assert plan.buy_levels[1].price == 1000.0
    assert plan.sell_levels[0].price == 3700.0
    assert plan.sell_levels[1].price == 5000.0


def test_scan_grid_candidates_returns_ranked_tradeable_filter() -> None:
    candles_by_symbol = {
        "EURUSD": candles_from([1.1000 + (0.0008 if i % 2 else -0.0008) for i in range(96)]),
        "USDJPY": candles_from([159.0 + (0.002 if i % 2 else -0.002) for i in range(96)]),
    }

    candidates = scan_grid_candidates(candles_by_symbol, GridStrikeSettings())

    assert [c.symbol for c in candidates] == ["EURUSD"]
    assert all(c.tradeable for c in candidates)
    assert candidates == sorted(candidates, key=lambda c: c.score, reverse=True)


def test_settings_loads_grid_strike_defaults() -> None:
    settings = Settings()

    assert settings.grid_strike.enabled is True
    assert settings.grid_strike.levels_each_side >= 3
