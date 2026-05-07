from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = PROJECT_ROOT / "mt5-worker" / "windows_mt5_worker.py"


class FakeMT5:
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008

    def __init__(self, retcode: int | None = None):
        self.retcode = retcode if retcode is not None else self.TRADE_RETCODE_DONE
        self.last_request = None

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
    assert reports and reports[0][0][1] == "filled"


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
    assert reports and reports[0][0][1] == "filled"
