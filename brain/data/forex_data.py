from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
import yfinance as yf

from brain.data.bybit_data import BybitMarketDataProvider
from shared.models import ForexQuote

YF_SYMBOLS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "CAD=X",
    "USDCHF": "CHF=X",
    "NZDUSD": "NZDUSD=X",
    "XAUUSD": "GC=F",  # Gold futures proxy until broker MT5 feed is connected
    # Bitcoin CFDs on MT5 are broker-specific (BTCUSD, BTCUSDm, BTCUSD., etc.).
    # During VPS-side development use Yahoo's BTC-USD as a public movement proxy;
    # the Windows MT5 worker/broker ticks become execution truth once connected.
    "BTCUSD": "BTC-USD",
    "XBTUSD": "BTC-USD",
}


class YFinanceForexProvider:
    """Free public FX data provider for pre-MT5 market understanding.

    This is not execution-grade. Once the Windows worker is connected, MT5 broker
    ticks should become the execution source of truth.
    """

    source = "yfinance"

    def to_yf_symbol(self, symbol: str) -> str:
        normalized = symbol.upper().replace("/", "")
        if normalized not in YF_SYMBOLS:
            if len(normalized) == 6:
                return f"{normalized}=X"
            raise ValueError(f"Unsupported symbol: {symbol}")
        return YF_SYMBOLS[normalized]

    def fetch_quote(self, symbol: str) -> ForexQuote:
        yf_symbol = self.to_yf_symbol(symbol)
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period="1d", interval="1m")
        if hist.empty:
            raise RuntimeError(f"No quote data returned for {symbol} ({yf_symbol})")
        last = float(hist["Close"].dropna().iloc[-1])
        ts = hist.index[-1].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ForexQuote(symbol=symbol.upper(), mid=last, timestamp=ts, source=self.source)

    def fetch_quotes(self, symbols: Iterable[str]) -> list[ForexQuote]:
        quotes: list[ForexQuote] = []
        for symbol in symbols:
            try:
                quotes.append(self.fetch_quote(symbol))
            except Exception as exc:
                print(f"WARN: failed to fetch {symbol}: {exc}")
        return quotes

    def fetch_candles(self, symbol: str, period: str = "5d", interval: str = "15m") -> pd.DataFrame:
        yf_symbol = self.to_yf_symbol(symbol)
        hist = yf.Ticker(yf_symbol).history(period=period, interval=interval)
        if hist.empty:
            raise RuntimeError(f"No candle data returned for {symbol} ({yf_symbol})")
        return hist[["Open", "High", "Low", "Close", "Volume"]].copy()


def main() -> None:
    from shared.settings import load_settings

    settings = load_settings()
    provider = BybitMarketDataProvider() if settings.market_data.provider.lower() == "bybit" else YFinanceForexProvider()
    quotes = provider.fetch_quotes(settings.market_data.symbols)
    print(f"Live {settings.market_data.provider} data snapshot @ {datetime.now(timezone.utc).isoformat()}")
    for q in quotes:
        print(f"{q.symbol:<8} {q.mid:<12.6f} {q.timestamp.isoformat()} source={q.source}")


if __name__ == "__main__":
    main()
