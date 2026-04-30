from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from shared.models import Signal, SignalSide
from shared.settings import Settings


def rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff().dropna()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    value = 100 - (100 / (1 + rs.iloc[-1]))
    return float(value) if pd.notna(value) else 50.0


def pip_size(symbol: str) -> float:
    return 0.01 if symbol.upper().endswith("JPY") else 0.0001


def simple_signal(symbol: str, candles: pd.DataFrame, settings: Settings) -> Signal | None:
    """Very conservative starter signal for paper/demo only.

    Logic:
    - Uses EMA trend + RSI pullback.
    - Does not trade if too few candles.
    - Returns a signal object only when confidence clears threshold.
    """
    if len(candles) < max(settings.strategy.trend_slow_ema, settings.strategy.rsi_period) + 5:
        return None

    close = candles["Close"].dropna()
    fast = close.ewm(span=settings.strategy.trend_fast_ema).mean().iloc[-1]
    slow = close.ewm(span=settings.strategy.trend_slow_ema).mean().iloc[-1]
    last = float(close.iloc[-1])
    current_rsi = rsi(close, settings.strategy.rsi_period)

    side: SignalSide | None = None
    confidence = 0.0
    reason = ""

    if fast > slow and current_rsi <= settings.strategy.rsi_buy_below:
        side = SignalSide.BUY
        confidence = min(0.95, 0.65 + ((settings.strategy.rsi_buy_below - current_rsi) / 100))
        reason = f"uptrend pullback: EMA{settings.strategy.trend_fast_ema}>{settings.strategy.trend_slow_ema}, RSI={current_rsi:.1f}"
    elif fast < slow and current_rsi >= settings.strategy.rsi_sell_above:
        side = SignalSide.SELL
        confidence = min(0.95, 0.65 + ((current_rsi - settings.strategy.rsi_sell_above) / 100))
        reason = f"downtrend pullback: EMA{settings.strategy.trend_fast_ema}<{settings.strategy.trend_slow_ema}, RSI={current_rsi:.1f}"

    if side is None or confidence < settings.strategy.min_signal_confidence:
        return None

    pip = pip_size(symbol)
    sl_dist = settings.risk.default_stop_loss_pips * pip
    tp_dist = settings.risk.default_take_profit_pips * pip
    if side == SignalSide.BUY:
        sl, tp = last - sl_dist, last + tp_dist
    else:
        sl, tp = last + sl_dist, last - tp_dist

    # Placeholder lot size; real worker/risk manager will verify against account balance.
    return Signal(
        symbol=symbol.upper(),
        side=side,
        lots=0.01,
        stop_loss=round(sl, 5),
        take_profit=round(tp, 5),
        confidence=round(confidence, 3),
        reason=reason + f" @ {datetime.now(timezone.utc).isoformat()}",
    )
