from __future__ import annotations

import pandas as pd

from brain.signals.grid_strike import (
    GridStrikeSettings,
    build_grid_plan,
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


def test_score_grid_candidate_prefers_scalpable_ranging_market() -> None:
    # Tight oscillation around a stable mean: good for grid scalping.
    values = [1.1000 + (0.0008 if i % 2 else -0.0008) for i in range(96)]
    candles = candles_from(values)

    candidate = score_grid_candidate("EURUSD", candles, GridStrikeSettings())

    assert candidate.symbol == "EURUSD"
    assert candidate.tradeable is True
    assert candidate.market_regime == "range"
    assert candidate.score >= 0.55
    assert candidate.reason


def test_score_grid_candidate_rejects_thin_flat_market() -> None:
    values = [1.1000 + (0.00002 if i % 2 else -0.00002) for i in range(96)]
    candles = candles_from(values)

    candidate = score_grid_candidate("EURUSD", candles, GridStrikeSettings())

    assert candidate.tradeable is False
    assert "range too small" in candidate.reason.lower()


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
