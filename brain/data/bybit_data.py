from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Protocol

import pandas as pd
import requests

from shared.models import ForexQuote

BYBIT_SYMBOLS = {
    "BTCUSD": "BTCUSDT",
    "BTCUSDT": "BTCUSDT",
    "XBTUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "ETHUSDT": "ETHUSDT",
}


class SupportsGet(Protocol):
    def get(self, url: str, params: dict, timeout: int): ...


def bybit_symbol(symbol: str) -> str:
    normalized = symbol.upper().replace("/", "").replace("-", "")
    if normalized in BYBIT_SYMBOLS:
        return BYBIT_SYMBOLS[normalized]
    if normalized.endswith("USD") and len(normalized) > 3:
        return f"{normalized[:-3]}USDT"
    return normalized


def _interval_to_bybit(interval: str) -> str:
    mapping = {
        "1m": "1",
        "3m": "3",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "2h": "120",
        "4h": "240",
        "6h": "360",
        "12h": "720",
        "1d": "D",
    }
    return mapping.get(interval.lower(), interval)


def _period_interval_limit(period: str, interval: str) -> int:
    period = period.lower()
    interval = interval.lower()
    days = 5
    if period.endswith("d"):
        days = max(1, int(period[:-1] or 1))
    elif period.endswith("mo"):
        days = max(1, int(period[:-2] or 1) * 30)
    minutes_by_interval = {
        "1m": 1,
        "3m": 3,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "2h": 120,
        "4h": 240,
        "6h": 360,
        "12h": 720,
        "1d": 1440,
    }
    minutes = minutes_by_interval.get(interval, 15)
    return max(2, min(1000, int((days * 24 * 60) / minutes)))


class BybitMarketDataProvider:
    """Bybit public market data provider for BTC movement.

    This does not place Bybit trades. It only reads BTCUSDT public market data as
    a faster BTC movement feed for the MT5/forex-funded grid method.
    """

    source = "bybit"

    def __init__(self, session: SupportsGet | None = None, base_url: str = "https://api.bybit.com") -> None:
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")

    def fetch_quote(self, symbol: str) -> ForexQuote:
        normalized_symbol = symbol.upper().replace("/", "")
        response = self.session.get(
            f"{self.base_url}/v5/market/tickers",
            params={"category": "linear", "symbol": bybit_symbol(symbol)},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit quote error for {symbol}: {payload}")
        rows = payload.get("result", {}).get("list", [])
        if not rows:
            raise RuntimeError(f"No Bybit quote data returned for {symbol}")
        row = rows[0]
        last = float(row["lastPrice"])
        bid = float(row["bid1Price"]) if row.get("bid1Price") not in (None, "") else None
        ask = float(row["ask1Price"]) if row.get("ask1Price") not in (None, "") else None
        return ForexQuote(
            symbol=normalized_symbol,
            bid=bid,
            ask=ask,
            mid=last,
            timestamp=datetime.now(timezone.utc),
            source=self.source,
        )

    def fetch_quotes(self, symbols: Iterable[str]) -> list[ForexQuote]:
        quotes: list[ForexQuote] = []
        for symbol in symbols:
            try:
                quotes.append(self.fetch_quote(symbol))
            except Exception as exc:
                print(f"WARN: failed to fetch {symbol} from Bybit: {exc}")
        return quotes

    def fetch_candles(self, symbol: str, period: str = "5d", interval: str = "15m") -> pd.DataFrame:
        response = self.session.get(
            f"{self.base_url}/v5/market/kline",
            params={
                "category": "linear",
                "symbol": bybit_symbol(symbol),
                "interval": _interval_to_bybit(interval),
                "limit": _period_interval_limit(period, interval),
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit candle error for {symbol}: {payload}")
        rows = payload.get("result", {}).get("list", [])
        if not rows:
            raise RuntimeError(f"No Bybit candle data returned for {symbol}")

        parsed = []
        for row in rows:
            parsed.append(
                {
                    "timestamp": pd.to_datetime(int(row[0]), unit="ms", utc=True),
                    "Open": float(row[1]),
                    "High": float(row[2]),
                    "Low": float(row[3]),
                    "Close": float(row[4]),
                    "Volume": float(row[5]),
                }
            )
        frame = pd.DataFrame(parsed).sort_values("timestamp").set_index("timestamp")
        return frame[["Open", "High", "Low", "Close", "Volume"]].copy()


class BybitWebhookCache:
    """In-memory cache for pushed Bybit/TradingView-style BTC price updates."""

    def __init__(self, source: str = "bybit-webhook") -> None:
        self.source = source
        self._quotes: dict[str, ForexQuote] = {}

    def update_quote(
        self,
        symbol: str,
        price: float,
        bid: float | None = None,
        ask: float | None = None,
        timestamp: datetime | None = None,
    ) -> ForexQuote:
        normalized_symbol = symbol.upper().replace("/", "")
        quote = ForexQuote(
            symbol=normalized_symbol,
            bid=bid,
            ask=ask,
            mid=float(price),
            timestamp=timestamp or datetime.now(timezone.utc),
            source=self.source,
        )
        self._quotes[normalized_symbol] = quote
        return quote

    def fetch_quote(self, symbol: str) -> ForexQuote:
        normalized_symbol = symbol.upper().replace("/", "")
        if normalized_symbol not in self._quotes:
            raise RuntimeError(f"No webhook quote cached for {symbol}")
        return self._quotes[normalized_symbol]

    def fetch_quotes(self, symbols: Iterable[str]) -> list[ForexQuote]:
        return [self.fetch_quote(symbol) for symbol in symbols if symbol.upper().replace("/", "") in self._quotes]
