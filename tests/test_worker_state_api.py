from __future__ import annotations

import json
from datetime import timedelta

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
        server.LAST_CLOSE_TIMES.clear()
        server.ENTRY_BLOCK_COUNTS.clear()
        server.GRID_REJECTION_COUNTS.clear()
        server.CLOSE_REASON_COUNTS.clear()
    yield
    with server.STATE_LOCK:
        server.HEARTBEATS.clear()
        server.SIGNALS.clear()
        server.EXECUTIONS.clear()
        server.VIRTUAL_POSITIONS.clear()
        server.LAST_CLOSE_TIMES.clear()
        server.ENTRY_BLOCK_COUNTS.clear()
        server.GRID_REJECTION_COUNTS.clear()
        server.CLOSE_REASON_COUNTS.clear()


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

    diagnostics_resp = client.get("/api/workers/windows-mt5-atlas-01/diagnostics", params=_token_param())
    assert diagnostics_resp.status_code == 200
    diagnostics = diagnostics_resp.json()
    assert diagnostics["basket_net_pnl"] == 12.3
    assert diagnostics["positions"][0]["symbol"] == "BTCUSD"


def test_heartbeat_ping_accepts_positions_json_payload() -> None:
    client = TestClient(server.app)
    positions_payload = [
        {
            "ticket": 44556677,
            "symbol": "ETHUSD",
            "side": "sell",
            "lots": 0.1,
            "entry_price": 2500.0,
            "current_price": 2480.0,
            "profit": 20.0,
            "swap": 0.0,
            "opened_at": 1715000000,
            "magic": 552501,
            "comment": "bridge-ea",
        }
    ]
    resp = client.get(
        "/api/worker/heartbeat-ping",
        params={
            **_token_param(),
            "worker_id": "windows-mt5-atlas-01",
            "mt5_connected": "true",
            "account_login": 123456,
            "broker": "AtlasFunded",
            "balance": 400000.0,
            "equity": 401000.0,
            "open_positions": 1,
            "positions_json": json.dumps(positions_payload),
        },
    )
    assert resp.status_code == 200
    assert resp.text == "ok"

    positions_resp = client.get("/api/workers/windows-mt5-atlas-01/positions", params=_token_param())
    assert positions_resp.status_code == 200
    positions = positions_resp.json()
    assert len(positions) == 1
    assert positions[0]["ticket"] == 44556677
    assert positions[0]["symbol"] == "ETHUSD"
    assert positions[0]["side"] == "sell"


def test_heartbeat_marks_pending_grid_signal_filled_when_position_comment_matches() -> None:
    client = TestClient(server.app)
    create_resp = client.post(
        "/api/signals/create",
        json={
            "symbol": "BTCUSD",
            "side": "buy",
            "action": "open",
            "lots": 0.01,
            "target_worker_id": "windows-mt5-atlas-5k-01",
        },
    )
    assert create_resp.status_code == 200
    signal_id = create_resp.json()["id"]

    with server.STATE_LOCK:
        signal = server.SIGNALS[signal_id]
        signal.order_type = "limit"
        signal.status = server.SignalStatus.EXECUTING
        signal.worker_id = "windows-mt5-atlas-5k-01"
        signal.grid_id = "BTCUSD-grid-1"
        signal.grid_index = 3
        signal.limit_price = 99800.0

    hb_resp = client.post(
        "/api/worker/heartbeat",
        params=_token_param(),
        json={
            "worker_id": "windows-mt5-atlas-5k-01",
            "mt5_connected": True,
            "account_login": 123456,
            "broker": "AtlasFunded",
            "balance": 5000.0,
            "equity": 5005.0,
            "open_positions": 1,
            "positions": [
                {
                    "ticket": 777001,
                    "symbol": "BTCUSD",
                    "side": "buy",
                    "lots": 0.01,
                    "entry_price": 99800.0,
                    "current_price": 99820.0,
                    "profit": 2.5,
                    "swap": 0.0,
                    "commission": 0.0,
                    "magic": 552501,
                    "comment": "grid:BTCUSD-grid-1:3",
                }
            ],
        },
    )
    assert hb_resp.status_code == 200

    signals = client.get("/api/signals").json()
    filled = next(row for row in signals if row["id"] == signal_id)
    assert filled["status"] == "filled"

    orders = client.get("/api/orders", params={**_token_param(), "worker_id": "windows-mt5-atlas-5k-01"}).json()
    execution = next(row for row in orders if row["signal_id"] == signal_id)
    assert execution["status"] == "filled"
    assert execution["message"] == "position confirmed by heartbeat"


def test_next_signal_plain_includes_action_and_position_ticket() -> None:
    client = TestClient(server.app)
    created = client.post(
        "/api/signals/create",
        json={
            "symbol": "BTCUSD",
            "side": "sell",
            "action": "close",
            "lots": 0.01,
            "position_ticket": 777001,
            "target_worker_id": "windows-mt5-atlas-01",
        },
    )
    assert created.status_code == 200
    signal_id = created.json()["id"]

    plain = client.get(
        "/api/worker/next-signal-plain",
        params={**_token_param(), "worker_id": "windows-mt5-atlas-01"},
    )
    assert plain.status_code == 200
    parts = plain.text.split("|")
    assert len(parts) >= 8
    assert parts[0] == signal_id
    assert parts[6] == "close"
    assert parts[7] == "777001"


def test_worker_state_endpoints_return_404_for_unknown_worker() -> None:
    client = TestClient(server.app)
    response = client.get("/api/workers/not-found-worker/positions", params=_token_param())
    assert response.status_code == 404
    assert response.json()["detail"] == "worker not found"


def test_auto_close_and_order_details_endpoints() -> None:
    server.settings.mt5_worker.reentry_cooldown_seconds = 0
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

    signals_after_close = client.get("/api/signals").json()
    reopen_signal = next(
        row
        for row in signals_after_close
        if row["action"] == "open" and row["reason"] == f"auto-reopen-after-close:{close_signal_id}"
    )
    assert reopen_signal["symbol"] == "BTCUSD"
    assert reopen_signal["side"] == "buy"
    assert reopen_signal["target_worker_id"] == "windows-mt5-atlas-01"

    orders_resp = client.get("/api/orders", params={**_token_param(), "worker_id": "windows-mt5-atlas-01"})
    assert orders_resp.status_code == 200
    orders = orders_resp.json()
    assert len(orders) >= 1
    assert orders[0]["signal_id"] == close_signal_id
    assert orders[0]["action"] == "close"
    assert orders[0]["position_ticket"] == 11223344


def test_heartbeat_auto_close_reopens_immediate_replacement_even_with_cooldown(monkeypatch) -> None:
    monkeypatch.setattr(server.settings.mt5_worker, "basket_take_profit_usd", 30.0)
    monkeypatch.setattr(server.settings.mt5_worker, "stale_position_minutes", 60)
    monkeypatch.setattr(server.settings.mt5_worker, "auto_close_profit_pct", 50.0)
    monkeypatch.setattr(server.settings.mt5_worker, "auto_close_loss_pct", 50.0)
    monkeypatch.setattr(server.settings.mt5_worker, "reentry_cooldown_seconds", 300)

    client = TestClient(server.app)
    heartbeat_payload = {
        "worker_id": "windows-mt5-atlas-01",
        "mt5_connected": True,
        "account_login": 123456,
        "broker": "AtlasFunded",
        "balance": 400000.0,
        "equity": 400050.0,
        "open_positions": 2,
        "positions": [
            {
                "ticket": 1,
                "symbol": "BTCUSD",
                "side": "buy",
                "lots": 0.01,
                "entry_price": 65000.0,
                "current_price": 65100.0,
                "profit": 20.0,
                "swap": 0.0,
                "commission": -0.2,
                "opened_at": "2026-01-01T00:00:00Z",
            },
            {
                "ticket": 2,
                "symbol": "ETHUSD",
                "side": "buy",
                "lots": 0.10,
                "entry_price": 2500.0,
                "current_price": 2502.0,
                "profit": 11.0,
                "swap": 0.0,
                "commission": -0.1,
                "opened_at": "2026-01-01T00:00:00Z",
            },
        ],
    }
    hb_resp = client.post("/api/worker/heartbeat", params=_token_param(), json=heartbeat_payload)
    assert hb_resp.status_code == 200

    close_signals = [row for row in client.get("/api/signals").json() if row["action"] == "close"]
    assert len(close_signals) == 2
    assert all("basket-tp-hit" in (row["close_reason"] or "") or "stale-exit" in (row["close_reason"] or "") for row in close_signals)

    close_signal = close_signals[0]
    exec_resp = client.post(
        "/api/worker/execution-report",
        params=_token_param(),
        json={
            "signal_id": close_signal["id"],
            "worker_id": "windows-mt5-atlas-01",
            "status": "filled",
            "broker_order_id": "close-1",
            "executed_price": 65100.0,
            "lots": 0.01,
            "message": "closed by basket rule",
        },
    )
    assert exec_resp.status_code == 200

    reopened = [
        row
        for row in client.get("/api/signals").json()
        if row["action"] == "open" and row["reason"] == f"auto-reopen-after-close:{close_signal['id']}"
    ]
    assert len(reopened) == 1
    assert reopened[0]["target_worker_id"] == "windows-mt5-atlas-01"
    assert reopened[0]["symbol"] == close_signal["symbol"]


def test_heartbeat_auto_close_never_stale_closes_losing_positions(monkeypatch, caplog) -> None:
    monkeypatch.setattr(server.settings.mt5_worker, "basket_take_profit_usd", 0.0)
    monkeypatch.setattr(server.settings.mt5_worker, "stale_position_minutes", 60)
    monkeypatch.setattr(server.settings.mt5_worker, "auto_close_profit_pct", 50.0)
    monkeypatch.setattr(server.settings.mt5_worker, "auto_close_loss_pct", 0.0)
    monkeypatch.setattr(server.settings.mt5_worker, "volatility_spike_close_pct", 0.0)
    caplog.set_level("INFO")

    client = TestClient(server.app)
    opened_at = (server.datetime.now(server.timezone.utc) - timedelta(hours=5)).isoformat()
    heartbeat_payload = {
        "worker_id": "windows-mt5-atlas-01",
        "mt5_connected": True,
        "account_login": 123456,
        "broker": "AtlasFunded",
        "balance": 400000.0,
        "equity": 399995.0,
        "open_positions": 1,
        "positions": [
            {
                "ticket": 445566,
                "symbol": "BTCUSD",
                "side": "buy",
                "lots": 0.01,
                "entry_price": 65000.0,
                "current_price": 64950.0,
                "profit": -5.0,
                "swap": 0.0,
                "commission": 0.0,
                "opened_at": opened_at,
            }
        ],
    }

    hb_resp = client.post("/api/worker/heartbeat", params=_token_param(), json=heartbeat_payload)
    assert hb_resp.status_code == 200

    close_signals = [row for row in client.get("/api/signals").json() if row["action"] == "close"]
    assert close_signals == []
    assert any("reason=stale-loss-blocked" in message for message in caplog.messages)


def test_diagnostics_summary_exposes_counters_and_cooldowns() -> None:
    client = TestClient(server.app)
    with server.STATE_LOCK:
        server.ENTRY_BLOCK_COUNTS.update({"reentry-cooldown": 2})
        server.GRID_REJECTION_COUNTS.update({"outside configured session window": 3})
        server.CLOSE_REASON_COUNTS.update({"basket-tp-hit": 1})
        server.LAST_CLOSE_TIMES["BTCUSD"] = server.datetime.now(server.timezone.utc)
        server.HEARTBEATS["windows-mt5-atlas-01"] = server.WorkerHeartbeat(
            worker_id="windows-mt5-atlas-01",
            mt5_connected=True,
            balance=400000.0,
            equity=400100.0,
            open_positions=1,
            positions=[
                server.WorkerPosition(
                    symbol="BTCUSD",
                    side="buy",
                    lots=0.01,
                    profit=15.0,
                    commission=-0.2,
                    swap=0.0,
                )
            ],
        )

    resp = client.get("/api/diagnostics/summary", params=_token_param())
    assert resp.status_code == 200
    body = resp.json()
    assert body["entry_block_counts"]["reentry-cooldown"] == 2
    assert body["grid_rejection_counts"]["outside configured session window"] == 3
    assert body["close_reason_counts"]["basket-tp-hit"] == 1
    assert body["workers"][0]["basket_net_pnl"] == 14.8
    assert "BTCUSD" in body["cooldowns"]
