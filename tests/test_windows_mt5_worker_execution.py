from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = PROJECT_ROOT / "mt5-worker" / "windows_mt5_worker.py"


class FakeMT5:
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 8
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008

    def __init__(self, retcode: int | None = None, account_login: int = 5000):
        self.retcode = retcode if retcode is not None else self.TRADE_RETCODE_DONE
        self.account_login = account_login
        self.last_request = None
        self.shutdown_called = False
        self.position_ticket_requests: list[int | None] = []
        self.order_ticket_requests: list[int | None] = []

    def account_info(self):
        return SimpleNamespace(login=self.account_login, server="TestBroker-Demo", balance=5000.0, equity=5000.0)

    def shutdown(self):
        self.shutdown_called = True

    def initialize(self):
        return True

    def symbol_select(self, symbol: str, enable: bool):
        return True

    def symbol_info_tick(self, symbol: str):
        return SimpleNamespace(ask=101.25, bid=100.75)

    def order_send(self, request):
        self.last_request = dict(request)
        return SimpleNamespace(retcode=self.retcode, order=321654, comment="ok")

    def positions_get(self, ticket=None):
        self.position_ticket_requests.append(ticket)
        return []

    def orders_get(self, ticket=None):
        self.order_ticket_requests.append(ticket)
        return []

    def last_error(self):
        return (0, "ok")


def _load_worker_module(monkeypatch, mt5_stub: FakeMT5):
    monkeypatch.setenv("BRAIN_URL", "http://127.0.0.1:8780")
    monkeypatch.setenv("WORKER_ID", "test-worker")
    monkeypatch.setenv("WORKER_TOKEN", "test-token")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setitem(sys.modules, "MetaTrader5", mt5_stub)

    module_name = "windows_mt5_worker_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_execute_signal_places_buy_limit_pending_order(monkeypatch):
    mt5 = FakeMT5(retcode=FakeMT5.TRADE_RETCODE_PLACED)
    worker = _load_worker_module(monkeypatch, mt5)

    reports = []
    monkeypatch.setattr(worker, "report", lambda *args, **kwargs: reports.append((args, kwargs)))

    worker.execute_signal(
        {
            "id": "grid-buy-1",
            "symbol": "EURUSD",
            "side": "buy",
            "lots": 0.05,
            "order_type": "limit",
            "limit_price": 1.08125,
            "stop_loss": 1.07925,
            "take_profit": 1.08325,
            "grid_id": "eurusd-grid-123",
            "grid_index": 4,
        }
    )

    assert mt5.last_request is not None
    assert mt5.last_request["action"] == mt5.TRADE_ACTION_PENDING
    assert mt5.last_request["type"] == mt5.ORDER_TYPE_BUY_LIMIT
    assert mt5.last_request["price"] == 1.08125
    assert mt5.last_request["sl"] == 1.07925
    assert mt5.last_request["tp"] == 1.08325
    assert mt5.last_request["type_time"] == mt5.ORDER_TIME_GTC
    assert mt5.last_request["type_filling"] == mt5.ORDER_FILLING_RETURN
    assert "grid:eurusd-grid-123:4" in mt5.last_request["comment"]
    assert reports and reports[0][0][1] == "executing"
    assert reports[0][0][2] == "MT5 pending order placed"


def test_execute_signal_places_sell_limit_pending_order(monkeypatch):
    mt5 = FakeMT5(retcode=FakeMT5.TRADE_RETCODE_PLACED)
    worker = _load_worker_module(monkeypatch, mt5)

    reports = []
    monkeypatch.setattr(worker, "report", lambda *args, **kwargs: reports.append((args, kwargs)))

    worker.execute_signal(
        {
            "id": "grid-sell-1",
            "symbol": "GBPUSD",
            "side": "sell",
            "lots": 0.03,
            "order_type": "limit",
            "limit_price": 1.255,
            "stop_loss": 1.257,
            "take_profit": 1.253,
            "grid_id": "gbpusd-grid-9",
            "grid_index": 1,
        }
    )

    assert mt5.last_request is not None
    assert mt5.last_request["action"] == mt5.TRADE_ACTION_PENDING
    assert mt5.last_request["type"] == mt5.ORDER_TYPE_SELL_LIMIT
    assert mt5.last_request["price"] == 1.255
    assert mt5.last_request["type_filling"] == mt5.ORDER_FILLING_RETURN
    assert "grid:gbpusd-grid-9:1" in mt5.last_request["comment"]
    assert reports and reports[0][0][1] == "executing"
    assert reports[0][0][2] == "MT5 pending order placed"


def test_execute_signal_clamps_long_grid_comment_for_mt5(monkeypatch):
    mt5 = FakeMT5(retcode=FakeMT5.TRADE_RETCODE_PLACED)
    worker = _load_worker_module(monkeypatch, mt5)

    reports = []
    monkeypatch.setattr(worker, "report", lambda *args, **kwargs: reports.append((args, kwargs)))

    worker.execute_signal(
        {
            "id": "grid-buy-long-comment",
            "symbol": "BTCUSD",
            "side": "buy",
            "lots": 0.05,
            "order_type": "limit",
            "limit_price": 76000.0,
            "stop_loss": 75650.0,
            "take_profit": 76525.0,
            "grid_id": "atlas50k-btc-eth-accepted-btc",
            "grid_index": -4,
        }
    )

    assert mt5.last_request is not None
    assert len(mt5.last_request["comment"]) <= worker.MT5_COMMENT_MAX_LEN
    assert mt5.last_request["comment"].startswith("grid:atl~")
    assert mt5.last_request["comment"].endswith("accepted-btc:-4")
    assert reports and reports[0][0][1] == "executing"


def test_execute_signal_cancels_pending_order_without_touching_positions(monkeypatch):
    mt5 = FakeMT5(retcode=FakeMT5.TRADE_RETCODE_DONE)
    mt5.orders_get = lambda ticket=None: [SimpleNamespace(ticket=ticket, symbol="EURUSD", volume_current=0.05)]
    worker = _load_worker_module(monkeypatch, mt5)

    reports = []
    monkeypatch.setattr(worker, "report", lambda *args, **kwargs: reports.append((args, kwargs)))

    worker.execute_signal(
        {
            "id": "grid-cancel-1",
            "symbol": "EURUSD",
            "side": "buy",
            "lots": 0.05,
            "action": "cancel",
            "order_ticket": 321654,
        }
    )

    assert mt5.last_request is not None
    assert mt5.last_request["action"] == mt5.TRADE_ACTION_REMOVE
    assert mt5.last_request["order"] == 321654
    assert mt5.position_ticket_requests == []
    assert reports and reports[0][0][1] == "cancelled"
    assert reports[0][0][2] == "MT5 pending order cancelled"


def test_execute_signal_rejects_when_terminal_is_logged_into_wrong_expected_account(monkeypatch):
    mt5 = FakeMT5(account_login=5001)
    monkeypatch.setenv("EXPECTED_MT5_LOGIN", "5000")
    worker = _load_worker_module(monkeypatch, mt5)

    reports = []
    monkeypatch.setattr(worker, "report", lambda *args, **kwargs: reports.append((args, kwargs)))

    worker.execute_signal(
        {
            "id": "wrong-login-1",
            "symbol": "EURUSD",
            "side": "buy",
            "lots": 0.05,
        }
    )

    assert mt5.last_request is None
    assert mt5.shutdown_called is True
    assert reports and reports[0][0][1] == "rejected"
    assert "Expected MT5 login 5000 but terminal is logged into 5001" in reports[0][0][2]


def test_serialize_positions_normalizes_future_shifted_mt5_times(monkeypatch, caplog):
    worker = _load_worker_module(monkeypatch, FakeMT5())
    monkeypatch.setattr(worker, "_local_utc_offset_seconds", lambda: 3 * 3600)
    caplog.set_level("WARNING")

    now_utc = datetime.now(timezone.utc)
    shifted_epoch = int(now_utc.timestamp()) + (3 * 3600)
    positions = [
        SimpleNamespace(
            ticket=77,
            symbol="BTCUSD",
            type=worker.mt5.ORDER_TYPE_BUY,
            volume=0.01,
            price_open=65000.0,
            price_current=65010.0,
            profit=1.0,
            swap=0.0,
            commission=0.0,
            time=shifted_epoch,
            comment="grid:test",
            magic=552501,
        )
    ]

    serialized = worker._serialize_positions(positions)

    opened_at = datetime.fromisoformat(serialized[0]["opened_at"])
    assert abs((opened_at - now_utc).total_seconds()) < 5
    assert any("normalized future-shifted MT5 position time" in message for message in caplog.messages)
