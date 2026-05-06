from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from brain.api import server
from brain.signals.grid_strike import GridStrikeSettings


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


class FakeProvider:
    def fetch_candles(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        if symbol == "EURUSD":
            return candles_from([1.1000 + (0.0008 if i % 2 else -0.0008) for i in range(96)])
        return candles_from([159.0 + (0.002 if i % 2 else -0.002) for i in range(96)])


def test_grid_strike_scan_endpoint_returns_ranked_candidates(monkeypatch) -> None:
    monkeypatch.setattr(server, "provider", FakeProvider())
    monkeypatch.setattr(server.settings.market_data, "symbols", ["EURUSD", "USDJPY"])
    monkeypatch.setattr(server.settings, "grid_strike", GridStrikeSettings())

    response = TestClient(server.app).post("/api/grid-strike/scan")

    assert response.status_code == 200
    body = response.json()
    assert [item["symbol"] for item in body] == ["EURUSD"]
    assert body[0]["market_regime"] == "range"


def test_grid_strike_plan_endpoint_builds_plan_for_best_candidate(monkeypatch) -> None:
    monkeypatch.setattr(server, "provider", FakeProvider())
    monkeypatch.setattr(server.settings.market_data, "symbols", ["EURUSD", "USDJPY"])
    monkeypatch.setattr(server.settings, "grid_strike", GridStrikeSettings())

    response = TestClient(server.app).post("/api/grid-strike/plan")

    assert response.status_code == 200
    plan = response.json()
    assert plan["symbol"] == "EURUSD"
    assert len(plan["buy_levels"]) == server.settings.grid_strike.levels_each_side
    assert len(plan["sell_levels"]) == server.settings.grid_strike.levels_each_side


def test_grid_strike_scan_all_returns_rejected_candidates_too(monkeypatch) -> None:
    monkeypatch.setattr(server, "provider", FakeProvider())
    monkeypatch.setattr(server.settings.market_data, "symbols", ["EURUSD", "USDJPY"])
    monkeypatch.setattr(server.settings, "grid_strike", GridStrikeSettings())

    response = TestClient(server.app).post("/api/grid-strike/scan-all")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {item["symbol"] for item in body} == {"EURUSD", "USDJPY"}


def test_worker_ping_accepts_query_token(monkeypatch) -> None:
    monkeypatch.setattr(server.settings.api, "worker_token", "test-token")

    response = TestClient(server.app).get(
        "/api/worker/heartbeat-ping",
        params={
            "worker_id": "macos-mt5-local-01",
            "mt5_connected": "true",
            "worker_token": "test-token",
        },
    )

    assert response.status_code == 200
    assert response.text == "ok"


def test_worker_ping_rejects_invalid_query_token(monkeypatch) -> None:
    monkeypatch.setattr(server.settings.api, "worker_token", "test-token")

    response = TestClient(server.app).get(
        "/api/worker/heartbeat-ping",
        params={
            "worker_id": "macos-mt5-local-01",
            "mt5_connected": "true",
            "worker_token": "wrong-token",
        },
    )

    assert response.status_code == 401
