from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Optional

import pandas as pd
from pydantic import BaseModel, Field


CRYPTO_PIP_SIZES: dict[str, float] = {
    "BTC": 1.0,
    "XBT": 1.0,
    "ETH": 0.01,
    "SOL": 0.01,
    "BNB": 0.01,
    "XRP": 0.0001,
}

CRYPTO_PRICE_DECIMALS: dict[str, int] = {
    "BTC": 2,
    "XBT": 2,
    "ETH": 2,
    "SOL": 3,
    "BNB": 2,
    "XRP": 4,
}


class GridStrikeSettings(BaseModel):
    """Settings for the Forex Grid Strike scalping filter.

    The filter looks for pairs that are moving enough to scalp, but not trending
    so hard that a symmetric grid is likely to get run over.
    """

    enabled: bool = True
    min_score: float = 0.55
    min_range_pct: float = 0.05
    max_range_pct: float = 1.20
    max_trend_ratio: float = 0.65
    lookback_candles: int = 96
    levels_each_side: int = 5
    min_spacing_pips: float = 3.0
    max_spacing_pips: float = 25.0
    order_lots: float = 0.01
    grid_spacing: float = 120.0
    take_profit_spacing: float = 120.0
    stop_loss_spacing: float = 60.0
    atr_period: int = 14
    atr_spacing_multiplier: float = 1.25
    session_start_hour_utc: int = 6
    session_end_hour_utc: int = 22
    max_spread_pips: float = 0.0
    symbol_lots: dict[str, float] = Field(default_factory=dict)
    symbol_grid_overrides: dict[str, dict[str, float | int | None]] = Field(default_factory=dict)

    def get_lots(self, symbol: str) -> float:
        return self.symbol_lots.get(symbol.upper(), self.order_lots)

    def get_symbol_grid_override(self, symbol: str) -> dict[str, float | int | None]:
        return self.symbol_grid_overrides.get(symbol.upper(), {})

    def get_levels_each_side(self, symbol: str) -> int:
        override = self.get_symbol_grid_override(symbol)
        value = override.get("levels_each_side")
        if value is None:
            return self.levels_each_side
        return max(int(value), 1)

    def get_price_bounds(self, symbol: str) -> tuple[float | None, float | None]:
        override = self.get_symbol_grid_override(symbol)
        lower = override.get("lower_bound")
        upper = override.get("upper_bound")
        return (
            float(lower) if lower is not None else None,
            float(upper) if upper is not None else None,
        )


class GridLevel(BaseModel):
    index: int
    side: str
    price: float
    lots: float


class GridStrikeCandidate(BaseModel):
    symbol: str
    score: float
    tradeable: bool
    market_regime: str
    mid_price: float
    range_pct: float
    trend_ratio: float
    atr_pips: float = 0.0
    spread_pips: float = 0.0
    grid_spacing_pips: float
    reason: str


class GridPlan(BaseModel):
    symbol: str
    score: float
    mid_price: float
    lower_bound: float
    upper_bound: float
    grid_spacing_pips: float
    lots_per_level: float
    buy_levels: list[GridLevel] = Field(default_factory=list)
    sell_levels: list[GridLevel] = Field(default_factory=list)
    reason: str


def pip_size(symbol: str) -> float:
    normalized = symbol.upper().replace("/", "")
    for prefix, value in CRYPTO_PIP_SIZES.items():
        if normalized.startswith(prefix):
            return value
    return 0.01 if normalized.endswith("JPY") else 0.0001


def round_price(symbol: str, price: float) -> float:
    normalized = symbol.upper().replace("/", "")
    for prefix, decimals in CRYPTO_PRICE_DECIMALS.items():
        if normalized.startswith(prefix):
            return round(price, decimals)
    return round(price, 3 if normalized.endswith("JPY") else 5)


def _atr_pips(symbol: str, candles: pd.DataFrame, period: int) -> float:
    high = candles["High"].astype(float)
    low = candles["Low"].astype(float)
    close = candles["Close"].astype(float)
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(true_range.tail(max(period, 1)).mean()) if not true_range.empty else 0.0
    return atr / max(pip_size(symbol), 1e-9)


def _latest_spread_pips(symbol: str, candles: pd.DataFrame) -> float:
    if "SpreadPips" in candles.columns:
        spread = float(candles["SpreadPips"].dropna().iloc[-1])
        return max(spread, 0.0)
    if {"Bid", "Ask"}.issubset(candles.columns):
        bid = float(candles["Bid"].dropna().iloc[-1])
        ask = float(candles["Ask"].dropna().iloc[-1])
        return max((ask - bid) / max(pip_size(symbol), 1e-9), 0.0)
    return 0.0


def _latest_timestamp(candles: pd.DataFrame) -> datetime | None:
    if candles.empty:
        return None
    last_idx = candles.index[-1]
    if isinstance(last_idx, pd.Timestamp):
        ts = last_idx.to_pydatetime()
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if "Timestamp" in candles.columns:
        ts = pd.Timestamp(candles["Timestamp"].iloc[-1]).to_pydatetime()
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return None


def _within_session(ts: datetime | None, settings: GridStrikeSettings) -> bool:
    if ts is None:
        return True
    hour = ts.astimezone(timezone.utc).hour
    start = settings.session_start_hour_utc
    end = settings.session_end_hour_utc
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def score_grid_candidate(
    symbol: str,
    candles: pd.DataFrame,
    settings: GridStrikeSettings,
) -> GridStrikeCandidate:
    close = candles["Close"].dropna().tail(settings.lookback_candles)
    high = candles["High"].dropna().tail(settings.lookback_candles)
    low = candles["Low"].dropna().tail(settings.lookback_candles)

    if len(close) < max(20, settings.lookback_candles // 3):
        return GridStrikeCandidate(
            symbol=symbol.upper(),
            score=0.0,
            tradeable=False,
            market_regime="unknown",
            mid_price=0.0,
            range_pct=0.0,
            trend_ratio=1.0,
            grid_spacing_pips=settings.grid_spacing,
            reason="not enough candle data for grid strike filter",
        )

    hi = float(high.max())
    lo = float(low.min())
    last = float(close.iloc[-1])
    mid = (hi + lo) / 2
    raw_range = max(hi - lo, 0.0)
    range_pct = (raw_range / mid) * 100 if mid > 0 else 0.0
    # Use the drift between early/late rolling means rather than first-vs-last
    # candle so an oscillating pair is not mislabeled as trending just because
    # the sample starts at a low strike and ends at a high strike.
    window = max(5, min(20, len(close) // 4))
    directional_move = abs(float(close.tail(window).mean()) - float(close.head(window).mean()))
    trend_ratio = min(1.0, directional_move / raw_range) if raw_range > 0 else 1.0

    atr_pips = _atr_pips(symbol, candles.tail(settings.lookback_candles), settings.atr_period)
    adaptive_spacing = atr_pips * max(settings.atr_spacing_multiplier, 0.0)
    spacing_pips = adaptive_spacing if adaptive_spacing > 0 else settings.grid_spacing
    spacing_pips = max(settings.min_spacing_pips, min(settings.max_spacing_pips, spacing_pips))
    spread_pips = _latest_spread_pips(symbol, candles)
    in_session = _within_session(_latest_timestamp(candles), settings)

    reasons: list[str] = []
    if range_pct < settings.min_range_pct:
        reasons.append(f"range too small ({range_pct:.3f}% < {settings.min_range_pct:.3f}%)")
    if range_pct > settings.max_range_pct:
        reasons.append(f"range too wide ({range_pct:.3f}% > {settings.max_range_pct:.3f}%)")
    if trend_ratio > settings.max_trend_ratio:
        reasons.append(f"trend too one-sided ({trend_ratio:.2f} > {settings.max_trend_ratio:.2f})")
    if not in_session:
        reasons.append("outside configured session window")
    if settings.max_spread_pips > 0 and spread_pips > settings.max_spread_pips:
        reasons.append(f"spread too wide ({spread_pips:.2f} > {settings.max_spread_pips:.2f} pips)")

    range_score = min(1.0, range_pct / max(settings.min_range_pct * 3, 0.0001))
    trend_score = max(0.0, 1.0 - (trend_ratio / max(settings.max_trend_ratio, 0.0001)))
    spacing_score = 1.0 if settings.min_spacing_pips <= spacing_pips <= settings.max_spacing_pips else 0.5
    spread_score = 1.0
    if settings.max_spread_pips > 0:
        spread_score = max(0.0, 1.0 - (spread_pips / max(settings.max_spread_pips, 0.0001)))
    score = round((range_score * 0.40) + (trend_score * 0.35) + (spacing_score * 0.15) + (spread_score * 0.10), 3)

    tradeable = not reasons and score >= settings.min_score
    regime = "range" if tradeable else ("trend" if trend_ratio > settings.max_trend_ratio else "no_trade")
    reason = "; ".join(reasons) if reasons else (
        f"scalpable range: range={range_pct:.3f}%, trend_ratio={trend_ratio:.2f}, "
        f"atr={atr_pips:.1f} pips, spread={spread_pips:.1f} pips, spacing={spacing_pips:.1f} pips"
    )

    return GridStrikeCandidate(
            symbol=symbol.upper(),
            score=score,
            tradeable=tradeable,
            market_regime=regime,
            mid_price=round_price(symbol, last),
            range_pct=round(range_pct, 4),
            trend_ratio=round(trend_ratio, 4),
            atr_pips=round(atr_pips, 2),
        spread_pips=round(spread_pips, 2),
        grid_spacing_pips=round(spacing_pips, 2),
        reason=reason,
    )


def build_grid_plan(
    candidate: GridStrikeCandidate,
    mid_price: Optional[float] = None,
    settings: Optional[GridStrikeSettings] = None,
) -> GridPlan:
    settings = settings or GridStrikeSettings()
    default_settings = GridStrikeSettings()
    pip = pip_size(candidate.symbol)
    mid = mid_price or candidate.last_price
    normalized_symbol = candidate.symbol.upper().replace("/", "")

    configured_spacing_pips = float(candidate.grid_spacing_pips)
    if getattr(settings, "grid_spacing", 0.0) > 0:
        configured_spacing_pips = float(settings.grid_spacing)

    btc_tight_spacing_pips = configured_spacing_pips
    if normalized_symbol.startswith(("BTC", "XBT")) and candidate.atr_pips > 0:
        using_default_grid_spacing = abs(float(settings.grid_spacing) - float(default_settings.grid_spacing)) < 1e-9
        if using_default_grid_spacing:
            btc_tight_spacing_pips = max(float(candidate.atr_pips) / 2.0, pip)

    step = configured_spacing_pips * pip

    lots = settings.get_lots(candidate.symbol)
    levels_each_side = settings.get_levels_each_side(candidate.symbol)
    lower_bound, upper_bound = settings.get_price_bounds(candidate.symbol)
    active_window = (btc_tight_spacing_pips * pip) * levels_each_side if normalized_symbol.startswith(("BTC", "XBT")) else step * levels_each_side
    clamp_btc_active_window = (
        normalized_symbol.startswith(("BTC", "XBT"))
        and levels_each_side > 1
        and lower_bound is not None
        and upper_bound is not None
        and (mid - lower_bound > active_window or upper_bound - mid > active_window)
    )

    if clamp_btc_active_window:
        tight_step = btc_tight_spacing_pips * pip
        buy_levels = [
            GridLevel(index=i, side="buy", price=round_price(candidate.symbol, mid - (tight_step * i)), lots=lots)
            for i in range(1, levels_each_side + 1)
        ]
        sell_levels = [
            GridLevel(index=i, side="sell", price=round_price(candidate.symbol, mid + (tight_step * i)), lots=lots)
            for i in range(1, levels_each_side + 1)
        ]
    else:
        if lower_bound is not None and lower_bound < mid:
            buy_step = (mid - lower_bound) / levels_each_side
            buy_levels = [
                GridLevel(index=i, side="buy", price=round_price(candidate.symbol, mid - (buy_step * i)), lots=lots)
                for i in range(1, levels_each_side + 1)
            ]
        else:
            buy_levels = [
                GridLevel(index=i, side="buy", price=round_price(candidate.symbol, mid - (step * i)), lots=lots)
                for i in range(1, levels_each_side + 1)
            ]

        if upper_bound is not None and upper_bound > mid:
            sell_step = (upper_bound - mid) / levels_each_side
            sell_levels = [
                GridLevel(index=i, side="sell", price=round_price(candidate.symbol, mid + (sell_step * i)), lots=lots)
                for i in range(1, levels_each_side + 1)
            ]
        else:
            sell_levels = [
                GridLevel(index=i, side="sell", price=round_price(candidate.symbol, mid + (step * i)), lots=lots)
                for i in range(1, levels_each_side + 1)
            ]

    effective_spacing_pips = configured_spacing_pips
    deltas: list[float] = []
    if buy_levels:
        deltas.append(abs(mid - buy_levels[0].price) / pip)
    if sell_levels:
        deltas.append(abs(sell_levels[0].price - mid) / pip)
    if deltas:
        effective_spacing_pips = round(sum(deltas) / len(deltas), 2)

    return GridPlan(
        symbol=candidate.symbol,
        score=candidate.score,
        mid_price=round_price(candidate.symbol, mid),
        lower_bound=buy_levels[-1].price,
        upper_bound=sell_levels[-1].price,
        grid_spacing_pips=effective_spacing_pips,
        lots_per_level=lots,
        buy_levels=buy_levels,
        sell_levels=sell_levels,
        reason=candidate.reason,
    )


def scan_grid_candidates(
    candles_by_symbol: Mapping[str, pd.DataFrame],
    settings: GridStrikeSettings,
) -> list[GridStrikeCandidate]:
    candidates = [score_grid_candidate(symbol, candles, settings) for symbol, candles in candles_by_symbol.items()]
    tradeable = [candidate for candidate in candidates if candidate.tradeable]
    return sorted(tradeable, key=lambda candidate: candidate.score, reverse=True)
