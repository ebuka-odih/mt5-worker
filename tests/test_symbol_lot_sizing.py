from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from brain.api import server
from brain.signals.simple_strategy import simple_signal
from shared.settings import Settings


def test_simple_signal_uses_symbol_specific_lot_size() -> None:
    settings = Settings()
    settings.strategy.rsi_buy_below = 100.0
    settings.strategy.min_signal_confidence = 0.6
    settings.grid_strike.symbol_lots = {"ETHUSD": 0.10}

    candles = pd.DataFrame(
        {
            "Open": [float(i) for i in range(1, 80)],
            "High": [float(i) + 1.0 for i in range(1, 80)],
            "Low": [float(i) - 1.0 for i in range(1, 80)],
            "Close": [float(i) for i in range(1, 80)],
            "Volume": [1000.0 for _ in range(1, 80)],
        }
    )

    signal = simple_signal("ETHUSD", candles, settings)
    assert signal is not None
    assert signal.lots == 0.10


def test_manual_create_signal_defaults_to_symbol_specific_lot_size() -> None:
    client = TestClient(server.app)
    original_symbol_lots = dict(server.settings.grid_strike.symbol_lots)
    try:
        server.settings.grid_strike.symbol_lots = {"BTCUSD": 0.01, "ETHUSD": 0.10}
        resp = client.post(
            "/api/signals/create",
            json={"symbol": "ETHUSD", "side": "buy", "action": "open"},
        )
    finally:
        server.settings.grid_strike.symbol_lots = original_symbol_lots

    assert resp.status_code == 200
    created = resp.json()
    assert created["symbol"] == "ETHUSD"
    assert created["lots"] == 0.10
