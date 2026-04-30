from __future__ import annotations

from fastapi.testclient import TestClient

from brain.api import server
from brain.data.bybit_data import BybitWebhookCache


def test_bybit_webhook_endpoint_updates_market_cache(monkeypatch) -> None:
    cache = BybitWebhookCache()
    monkeypatch.setattr(server, "bybit_webhook_cache", cache)

    response = TestClient(server.app).post(
        "/api/market/bybit-webhook",
        json={"symbol": "BTCUSD", "price": 77010.5, "bid": 77010.0, "ask": 77011.0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["quote"]["symbol"] == "BTCUSD"
    assert cache.fetch_quote("BTCUSD").mid == 77010.5
