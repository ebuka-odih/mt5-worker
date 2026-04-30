"""Windows MT5 worker template.

Run this on the Windows machine that has MetaTrader 5 installed and logged in.
The worker makes OUTBOUND requests to the VPS, so no inbound Windows port is needed.

Install on Windows:
    py -m venv venv
    venv\Scripts\activate
    pip install MetaTrader5 requests python-dotenv

Create .env next to this file:
    VPS_API_BASE=https://your-vps-domain-or-ip:8780
    WORKER_TOKEN=CHANGE_ME_LONG_RANDOM_TOKEN
    WORKER_ID=windows-mt5-local-01
    DRY_RUN=true

Then run:
    python windows_mt5_worker.py
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv

try:
    import MetaTrader5 as mt5
except ImportError:  # lets the file be linted on non-Windows machines
    mt5 = None

load_dotenv()

API_BASE = os.getenv("VPS_API_BASE", "http://127.0.0.1:8780").rstrip("/")
TOKEN = os.getenv("WORKER_TOKEN", "CHANGE_ME_LONG_RANDOM_TOKEN")
WORKER_ID = os.getenv("WORKER_ID", "windows-mt5-local-01")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "1"))
MAGIC = int(os.getenv("MT5_MAGIC", "552501"))

HEADERS = {"X-Worker-Token": TOKEN}


def mt5_init() -> bool:
    if mt5 is None:
        print("MetaTrader5 package not installed. Run: pip install MetaTrader5")
        return False
    ok = mt5.initialize()
    if not ok:
        print("MT5 initialize failed:", mt5.last_error())
    return ok


def send_heartbeat() -> None:
    if mt5 is None or not mt5.initialize():
        payload = {"worker_id": WORKER_ID, "mt5_connected": False, "open_positions": 0}
    else:
        account = mt5.account_info()
        positions = mt5.positions_get() or []
        payload = {
            "worker_id": WORKER_ID,
            "mt5_connected": True,
            "account_login": getattr(account, "login", None),
            "broker": getattr(account, "server", None),
            "balance": getattr(account, "balance", None),
            "equity": getattr(account, "equity", None),
            "open_positions": len(positions),
        }
    requests.post(f"{API_BASE}/api/worker/heartbeat", json=payload, headers=HEADERS, timeout=10)


def get_next_signal() -> dict[str, Any] | None:
    resp = requests.get(
        f"{API_BASE}/api/worker/next-signal",
        params={"worker_id": WORKER_ID},
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def report(signal_id: str, status: str, message: str, **extra: Any) -> None:
    payload = {
        "signal_id": signal_id,
        "worker_id": WORKER_ID,
        "status": status,
        "message": message,
        **extra,
    }
    requests.post(f"{API_BASE}/api/worker/execution-report", json=payload, headers=HEADERS, timeout=10)


def execute_signal(signal: dict[str, Any]) -> None:
    print("Received signal:", signal)
    if DRY_RUN:
        report(signal["id"], "filled", "DRY_RUN accepted signal; no MT5 order sent", lots=signal.get("lots"))
        return

    if mt5 is None or not mt5.initialize():
        report(signal["id"], "rejected", "MT5 not connected")
        return

    symbol = signal["symbol"]
    if not mt5.symbol_select(symbol, True):
        report(signal["id"], "rejected", f"symbol_select failed for {symbol}: {mt5.last_error()}")
        return

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        report(signal["id"], "rejected", f"no tick for {symbol}")
        return

    side = signal["side"].lower()
    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    price = tick.ask if side == "buy" else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(signal["lots"]),
        "type": order_type,
        "price": price,
        "sl": signal.get("stop_loss") or 0.0,
        "tp": signal.get("take_profit") or 0.0,
        "deviation": 20,
        "magic": MAGIC,
        "comment": "vps_forex_brain",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None:
        report(signal["id"], "rejected", f"order_send returned None: {mt5.last_error()}")
        return
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        report(signal["id"], "rejected", f"MT5 retcode={result.retcode}, comment={result.comment}")
        return
    report(signal["id"], "filled", "MT5 order filled", broker_order_id=str(result.order), executed_price=price, lots=float(signal["lots"]))


def main() -> None:
    print(f"Starting Windows MT5 worker {WORKER_ID}; dry_run={DRY_RUN}; api={API_BASE}")
    last_hb = 0.0
    while True:
        now = time.time()
        if now - last_hb > 10:
            try:
                send_heartbeat()
            except Exception as exc:
                print("heartbeat failed:", exc)
            last_hb = now
        try:
            signal = get_next_signal()
            if signal:
                execute_signal(signal)
        except Exception as exc:
            print("poll failed:", exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
