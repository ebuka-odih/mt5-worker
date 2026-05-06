from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from brain.api import server
from brain.api.server import VirtualPosition
from shared.models import Signal, SignalSide, SignalStatus, WorkerPosition


class DummyProvider:
    def fetch_candles(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Open": [1.0, 1.1, 1.2],
                "High": [1.2, 1.3, 1.4],
                "Low": [0.9, 1.0, 1.1],
                "Close": [1.1, 1.2, 1.3],
                "Volume": [100, 100, 100],
            }
        )


def _reset_runtime_state() -> None:
    with server.STATE_LOCK:
        server.SIGNALS.clear()
        server.EXECUTIONS.clear()
        server.HEARTBEATS.clear()
        server.VIRTUAL_POSITIONS.clear()
        server.LAST_CLOSE_TIMES.clear()


@pytest.fixture(autouse=True)
def _clean_runtime_state():
    _reset_runtime_state()
    yield
    _reset_runtime_state()


def test_scan_skips_same_side_when_virtual_position_exists(monkeypatch) -> None:
    monkeypatch.setattr(server.settings.market_data, "symbols", ["BTCUSD"])
    monkeypatch.setattr(server, "provider", DummyProvider())

    def fake_simple_signal(symbol: str, candles: pd.DataFrame, _settings) -> Signal:
        return Signal(
            symbol=symbol,
            side=SignalSide.BUY,
            lots=0.01,
            stop_loss=1.0,
            take_profit=2.0,
            confidence=0.9,
            reason="test-buy",
        )

    monkeypatch.setattr(server, "simple_signal", fake_simple_signal)

    created = server._run_strategy_scan_once()
    assert len(created) == 1

    with server.STATE_LOCK:
        created[0].status = SignalStatus.FILLED
        server.VIRTUAL_POSITIONS["BTCUSD"] = VirtualPosition(
            symbol="BTCUSD",
            side=SignalSide.BUY,
            lots=0.01,
            updated_at=datetime.now(timezone.utc),
        )

    created_again = server._run_strategy_scan_once()
    assert created_again == []


def test_scan_allows_opposite_side_to_flip_position(monkeypatch) -> None:
    monkeypatch.setattr(server.settings.market_data, "symbols", ["BTCUSD"])
    monkeypatch.setattr(server, "provider", DummyProvider())

    def fake_simple_signal(symbol: str, candles: pd.DataFrame, _settings) -> Signal:
        return Signal(
            symbol=symbol,
            side=SignalSide.SELL,
            lots=0.01,
            stop_loss=2.0,
            take_profit=1.0,
            confidence=0.9,
            reason="test-sell",
        )

    monkeypatch.setattr(server, "simple_signal", fake_simple_signal)

    with server.STATE_LOCK:
        server.VIRTUAL_POSITIONS["BTCUSD"] = VirtualPosition(
            symbol="BTCUSD",
            side=SignalSide.BUY,
            lots=0.01,
            updated_at=datetime.now(timezone.utc),
        )

    created = server._run_strategy_scan_once()
    assert len(created) == 1
    assert created[0].side == SignalSide.SELL
    assert created[0].symbol == "BTCUSD"


def test_scan_blocks_new_entries_when_daily_drawdown_breaker_is_hit(monkeypatch) -> None:
    monkeypatch.setattr(server.settings.market_data, "symbols", ["BTCUSD"])
    monkeypatch.setattr(server, "provider", DummyProvider())
    monkeypatch.setattr(server.settings.risk, "funded_challenge_mode", True)
    monkeypatch.setattr(server.settings.risk, "starting_balance", 400_000.0)
    monkeypatch.setattr(server.settings.risk, "daily_loss_budget", 4_000.0)
    monkeypatch.setattr(server.settings.risk, "max_daily_loss_pct", 1.0)

    def fake_simple_signal(symbol: str, candles: pd.DataFrame, _settings) -> Signal:
        return Signal(
            symbol=symbol,
            side=SignalSide.BUY,
            lots=0.01,
            stop_loss=1.0,
            take_profit=2.0,
            confidence=0.9,
            reason="test-buy",
        )

    monkeypatch.setattr(server, "simple_signal", fake_simple_signal)

    with server.STATE_LOCK:
        server.HEARTBEATS["windows-mt5-atlas-01"] = server.WorkerHeartbeat(
            worker_id="windows-mt5-atlas-01",
            mt5_connected=True,
            balance=400_000.0,
            equity=395_500.0,
            open_positions=0,
        )

    created = server._run_strategy_scan_once()
    assert created == []


def test_manual_signal_create_rejects_when_margin_cap_is_already_exceeded(monkeypatch) -> None:
    monkeypatch.setattr(server.settings.risk, "starting_balance", 400_000.0)
    monkeypatch.setattr(server.settings.risk, "max_margin_usage_pct", 60.0)
    monkeypatch.setattr(server.settings.risk, "leverage", 10.0)

    client = server.app
    with server.STATE_LOCK:
        server.HEARTBEATS["windows-mt5-atlas-01"] = server.WorkerHeartbeat(
            worker_id="windows-mt5-atlas-01",
            mt5_connected=True,
            balance=400_000.0,
            equity=400_000.0,
            open_positions=1,
            positions=[
                WorkerPosition(
                    symbol="BTCUSD",
                    side=SignalSide.BUY,
                    lots=50.0,
                    entry_price=100_000.0,
                    current_price=100_000.0,
                )
            ],
        )

    from fastapi.testclient import TestClient

    response = TestClient(client).post(
        "/api/signals/create",
        json={"symbol": "ETHUSD", "side": "buy", "action": "open", "lots": 0.1},
    )

    assert response.status_code == 409
    assert "margin usage too high" in response.json()["detail"]
