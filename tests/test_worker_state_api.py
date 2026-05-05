from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from brain.api import server


def _token_param() -> dict[str, str]:
    return {"worker_token": server.settings.api.worker_token}


@pytest.fixture(autouse=True)
def _reset_server_state():
    with server.STATE_LOCK:
        server.HEARTBEATS.clear()
        server.SIGNALS.clear()
        server.EXECUTIONS.clear()
        server.VIRTUAL_POSITIONS.clear()
    yield
    with server.STATE_LOCK:
        server.HEARTBEATS.clear()
        server.SIGNALS.clear()
        server.EXECUTIONS.clear()
        server.VIRTUAL_POSITIONS.clear()


def test_worker_state_endpoints_expose_position_details() -> None:
    client = TestClient(server.app)
    heartbeat_payload = {
        "worker_id": "windows-mt5-atlas-01",
        "mt5_connected": True,
        "account_login": 123456,
        "broker": "AtlasFunded",
        "balance": 400000.0,
        "equity": 401250.5,
        "open_positions": 1,
        "positions": [
            {
                "ticket": 99887766,
                "symbol": "BTCUSD",
                "side": "buy",
                "lots": 0.01,
                "entry_price": 65000.0,
                "current_price": 65120.0,
                "profit": 12.5,
                "swap": 0.0,
                "commission": -0.2,
                "magic": 552501,
                "comment": "vps_forex_brain",
            }
        ],
    }

    hb_resp = client.post("/api/worker/heartbeat", params=_token_param(), json=heartbeat_payload)
    assert hb_resp.status_code == 200
    assert hb_resp.json()["ok"] is True

    workers_resp = client.get("/api/workers", params=_token_param())
    assert workers_resp.status_code == 200
    workers = workers_resp.json()
    assert len(workers) >= 1
    worker = next(row for row in workers if row["worker_id"] == "windows-mt5-atlas-01")
    assert worker["open_positions"] == 1
    assert worker["positions"][0]["symbol"] == "BTCUSD"
    assert worker["positions"][0]["side"] == "buy"

    positions_resp = client.get("/api/workers/windows-mt5-atlas-01/positions", params=_token_param())
    assert positions_resp.status_code == 200
    positions = positions_resp.json()
    assert len(positions) == 1
    assert positions[0]["ticket"] == 99887766
    assert positions[0]["profit"] == 12.5


def test_worker_state_endpoints_return_404_for_unknown_worker() -> None:
    client = TestClient(server.app)
    response = client.get("/api/workers/not-found-worker/positions", params=_token_param())
    assert response.status_code == 404
    assert response.json()["detail"] == "worker not found"


def test_auto_close_and_order_details_endpoints() -> None:
    client = TestClient(server.app)
    heartbeat_payload = {
        "worker_id": "windows-mt5-atlas-01",
        "mt5_connected": True,
        "account_login": 123456,
        "broker": "AtlasFunded",
        "balance": 400000.0,
        "equity": 402000.0,
        "open_positions": 1,
        "positions": [
            {
                "ticket": 11223344,
                "symbol": "BTCUSD",
                "side": "buy",
                "lots": 0.01,
                "entry_price": 65000.0,
                "current_price": 66000.0,
                "profit": 50.0,
                "swap": 0.0,
                "commission": -0.2,
                "magic": 552501,
                "comment": "vps_forex_brain",
            }
        ],
    }
    hb_resp = client.post("/api/worker/heartbeat", params=_token_param(), json=heartbeat_payload)
    assert hb_resp.status_code == 200

    close_resp = client.post("/api/workers/windows-mt5-atlas-01/auto-close", params={**_token_param(), "profit_pct": 1.0})
    assert close_resp.status_code == 200
    payload = close_resp.json()
    assert payload["close_signals_created"] == 1
    close_signal_id = payload["signal_ids"][0]

    signals = client.get("/api/signals").json()
    close_signal = next(row for row in signals if row["id"] == close_signal_id)
    assert close_signal["action"] == "close"
    assert close_signal["position_ticket"] == 11223344
    assert close_signal["target_worker_id"] == "windows-mt5-atlas-01"

    exec_resp = client.post(
        "/api/worker/execution-report",
        params=_token_param(),
        json={
            "signal_id": close_signal_id,
            "worker_id": "windows-mt5-atlas-01",
            "status": "filled",
            "broker_order_id": "9001",
            "executed_price": 66000.0,
            "lots": 0.01,
            "message": "closed by auto-close",
        },
    )
    assert exec_resp.status_code == 200

    orders_resp = client.get("/api/orders", params={**_token_param(), "worker_id": "windows-mt5-atlas-01"})
    assert orders_resp.status_code == 200
    orders = orders_resp.json()
    assert len(orders) >= 1
    assert orders[0]["signal_id"] == close_signal_id
    assert orders[0]["action"] == "close"
    assert orders[0]["position_ticket"] == 11223344
