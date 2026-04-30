from __future__ import annotations

from datetime import datetime, timezone

from brain.data.bybit_data import BybitMarketDataProvider, BybitWebhookCache, bybit_symbol


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.params: list[dict] = []

    def get(self, url: str, params: dict, timeout: int):
        self.urls.append(url)
        self.params.append(params)
        if url.endswith("/v5/market/tickers"):
            return FakeResponse(
                {
                    "retCode": 0,
                    "result": {
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "lastPrice": "77000.5",
                                "bid1Price": "76999.0",
                                "ask1Price": "77002.0",
                            }
                        ]
                    },
                }
            )
        return FakeResponse(
            {
                "retCode": 0,
                "result": {
                    "list": [
                        ["1710000900000", "77000", "77100", "76900", "77050", "10", "770500"],
                        ["1710000000000", "76900", "77000", "76800", "77000", "12", "923000"],
                    ]
                },
            }
        )


def test_bybit_symbol_maps_mt5_crypto_aliases_to_bybit_perps() -> None:
    assert bybit_symbol("BTCUSD") == "BTCUSDT"
    assert bybit_symbol("BTC/USD") == "BTCUSDT"
    assert bybit_symbol("XBTUSD") == "BTCUSDT"
    assert bybit_symbol("ETHUSD") == "ETHUSDT"
    assert bybit_symbol("ETH/USD") == "ETHUSDT"


def test_bybit_provider_fetches_btc_quote_and_candles() -> None:
    session = FakeSession()
    provider = BybitMarketDataProvider(session=session)

    quote = provider.fetch_quote("BTCUSD")
    candles = provider.fetch_candles("BTCUSD", period="5d", interval="15m")

    assert quote.symbol == "BTCUSD"
    assert quote.mid == 77000.5
    assert quote.bid == 76999.0
    assert quote.ask == 77002.0
    assert quote.source == "bybit"
    assert session.params[0] == {"category": "linear", "symbol": "BTCUSDT"}
    assert session.params[1]["interval"] == "15"
    assert list(candles.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert candles["Close"].tolist() == [77000.0, 77050.0]


def test_bybit_webhook_cache_updates_and_returns_quote() -> None:
    cache = BybitWebhookCache(source="bybit-webhook")
    now = datetime.now(timezone.utc)

    quote = cache.update_quote(symbol="BTCUSD", price=77001.25, bid=77000.0, ask=77002.5, timestamp=now)

    assert quote.mid == 77001.25
    assert quote.source == "bybit-webhook"
    assert cache.fetch_quote("BTCUSD") == quote
    assert cache.fetch_quotes(["BTCUSD"])[0] == quote
