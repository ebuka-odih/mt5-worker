"""
Windows MT5 worker template.

Run this on the Windows machine that has MetaTrader 5 installed and logged in.
The worker makes OUTBOUND requests to the VPS, so no inbound Windows port is needed.

Install on Windows:
 py -m venv venv
 venv\\Scripts\\activate
 pip install -r requirements.txt

Create .env next to this file (copy from .env.example and fill in values):
 cp .env.example .env
 # Edit .env with your VPS_API_BASE and a strong WORKER_TOKEN

Then run:
 python windows_mt5_worker.py

For testing without a real VPS, set:
 DRY_RUN=true
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mt5-worker")

try:
    import MetaTrader5 as mt5
except ImportError:  # allows the file to be linted on non-Windows machines
    mt5 = None

def _env_file_from_args(argv: list[str]) -> str:
    """Return the worker env file path from CLI/env, defaulting to .env.

    This lets the same Windows worker script run multiple Atlas logins safely:
    python windows_mt5_worker.py --env-file .env.atlas-50k
    """
    for index, arg in enumerate(argv[1:], start=1):
        if arg == "--env-file" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--env-file="):
            return arg.split("=", 1)[1]
    return os.getenv("WORKER_ENV_FILE", ".env")


ENV_FILE = _env_file_from_args(sys.argv)
load_dotenv(ENV_FILE)


def _optional_int_env(name: str) -> Optional[int]:
    """Return an optional integer env var, treating placeholders as unset."""
    value = os.getenv(name, "").strip()
    if not value or value.upper().startswith("CHANGE_ME") or value.startswith("<"):
        return None
    try:
        return int(value)
    except ValueError:
        logger.error("%s must be an integer MT5 account login, got %r", name, value)
        sys.exit(1)


API_BASE = os.getenv("VPS_API_BASE", "http://127.0.0.1:8780").rstrip("/")
TOKEN = os.getenv("WORKER_TOKEN", "")
WORKER_ID = os.getenv("WORKER_ID", "windows-mt5-local-01")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "1"))
MAGIC = int(os.getenv("MT5_MAGIC", "552501"))
EXPECTED_MT5_LOGIN = _optional_int_env("EXPECTED_MT5_LOGIN")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "2"))

if not TOKEN:
    logger.error(f"WORKER_TOKEN is not set in {ENV_FILE}. Please set a strong random token.")
    sys.exit(1)

HEADERS = {"X-Worker-Token": TOKEN}

# Graceful shutdown flag
_shutdown_requested = False


def _signal_handler(signum, frame) -> None:
    """Handle Ctrl+C or termination signals gracefully."""
    global _shutdown_requested
    logger.info("Shutdown signal received, cleaning up...")
    _shutdown_requested = True


# Register signal handlers
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def retry_request(func, *args, max_attempts: int = MAX_RETRIES, **kwargs) -> Any:
    """Retry a request function with exponential backoff for transient failures."""
    last_exception = None
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except requests.exceptions.RequestException as e:
            last_exception = e
            if attempt < max_attempts - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                logger.warning(f"Request failed (attempt {attempt + 1}/{max_attempts}): {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
    logger.error(f"Request failed after {max_attempts} attempts: {last_exception}")
    raise last_exception


@dataclass
class MT5State:
    """Track MT5 connection state to avoid repeated initialize() calls."""
    initialized: bool = False
    account_login: Optional[int] = None
    broker: Optional[str] = None
    balance: Optional[float] = None
    equity: Optional[float] = None
    last_init_time: float = 0.0

    def ensure_initialized(self) -> bool:
        """Ensure MT5 is initialized, reinitializing only if needed."""
        global _shutdown_requested
        if _shutdown_requested:
            return False

        # Re-initialize if not done or if it's been > 5 minutes
        now = time.time()
        if self.initialized and (now - self.last_init_time) < 300:
            return True

        if mt5 is None:
            logger.warning("MetaTrader5 package not installed")
            self.initialized = False
            return False

        if not self.initialized:
            logger.info("Initializing MT5 connection...")
            ok = mt5.initialize()
            if not ok:
                logger.error(f"MT5 initialize failed: {mt5.last_error()}")
                self.initialized = False
                return False
            self.initialized = True
            self.last_init_time = now
            logger.info("MT5 initialized successfully")

        return True

    def shutdown(self) -> None:
        """Cleanly shutdown MT5 connection."""
        if mt5 and self.initialized:
            logger.info("Shutting down MT5 connection...")
            mt5.shutdown()
            self.initialized = False
            self.account_login = None
            self.broker = None
            self.balance = None
            self.equity = None


# Global MT5 state
_mt5_state = MT5State()


def validate_expected_account() -> tuple[bool, str | None]:
    """Verify the running MT5 terminal is logged into the configured account."""
    global _mt5_state
    if EXPECTED_MT5_LOGIN is None:
        return True, None
    if mt5 is None:
        return False, "MetaTrader5 package not installed"
    account = mt5.account_info()
    actual_login = getattr(account, "login", None)
    _mt5_state.account_login = actual_login
    _mt5_state.broker = getattr(account, "server", None)
    _mt5_state.balance = getattr(account, "balance", None)
    _mt5_state.equity = getattr(account, "equity", None)
    if actual_login != EXPECTED_MT5_LOGIN:
        message = f"Expected MT5 login {EXPECTED_MT5_LOGIN} but terminal is logged into {actual_login}"
        logger.error("%s. Refusing to trade from env file %s.", message, ENV_FILE)
        _mt5_state.shutdown()
        return False, message
    return True, None


def _position_side(position_type: Any) -> str:
    if mt5 is None:
        return "buy"
    if position_type == mt5.POSITION_TYPE_BUY:
        return "buy"
    if position_type == mt5.POSITION_TYPE_SELL:
        return "sell"
    return "buy"


def _local_utc_offset_seconds() -> int:
    now_local = datetime.now().astimezone()
    offset = now_local.utcoffset()
    return int(offset.total_seconds()) if offset is not None else 0


MT5_COMMENT_MAX_LEN = 31


def _mt5_safe_comment(comment: str) -> str:
    """Return an MT5-safe order comment.

    The MetaTrader5 Python binding rejects overlong comments before the request
    reaches the broker with: Invalid "comment" argument. MT5/brokers commonly
    cap comments at 31 characters, so preserve the useful suffix when clipping.
    """
    safe = "".join(ch if 32 <= ord(ch) < 127 else "_" for ch in str(comment))
    if len(safe) <= MT5_COMMENT_MAX_LEN:
        return safe
    return safe[:8] + "~" + safe[-(MT5_COMMENT_MAX_LEN - 9):]


def _normalize_opened_at(ts: Any) -> Optional[str]:
    if ts in (None, ""):
        return None
    try:
        opened_at = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except Exception:
        return None

    now_utc = datetime.now(timezone.utc)
    if opened_at > now_utc:
        local_offset_seconds = _local_utc_offset_seconds()
        if local_offset_seconds > 0:
            adjusted = datetime.fromtimestamp(int(opened_at.timestamp() - local_offset_seconds), tz=timezone.utc)
            if adjusted <= now_utc:
                logger.warning(
                    "normalized future-shifted MT5 position time raw_ts=%s opened_at=%s adjusted_opened_at=%s local_offset_seconds=%s",
                    ts,
                    opened_at.isoformat(),
                    adjusted.isoformat(),
                    local_offset_seconds,
                )
                opened_at = adjusted

    return opened_at.isoformat()


def _serialize_positions(positions: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for pos in positions:
        opened_at = _normalize_opened_at(getattr(pos, "time", None))

        serialized.append(
            {
                "ticket": getattr(pos, "ticket", None),
                "symbol": getattr(pos, "symbol", ""),
                "side": _position_side(getattr(pos, "type", None)),
                "lots": float(getattr(pos, "volume", 0.0)),
                "entry_price": float(getattr(pos, "price_open", 0.0)),
                "current_price": float(getattr(pos, "price_current", 0.0)),
                "profit": float(getattr(pos, "profit", 0.0)),
                "swap": float(getattr(pos, "swap", 0.0)),
                "commission": float(getattr(pos, "commission", 0.0)),
                "opened_at": opened_at,
                "magic": getattr(pos, "magic", None),
                "comment": str(getattr(pos, "comment", "") or ""),
            }
        )
    return serialized


def _pending_order_side(order_type: Any) -> str:
    if mt5 is None:
        return "buy"
    if order_type in {getattr(mt5, "ORDER_TYPE_BUY", object()), getattr(mt5, "ORDER_TYPE_BUY_LIMIT", object())}:
        return "buy"
    if order_type in {getattr(mt5, "ORDER_TYPE_SELL", object()), getattr(mt5, "ORDER_TYPE_SELL_LIMIT", object())}:
        return "sell"
    return "buy"


def _serialize_pending_orders(orders: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for order in orders:
        serialized.append(
            {
                "ticket": getattr(order, "ticket", None),
                "symbol": getattr(order, "symbol", ""),
                "side": _pending_order_side(getattr(order, "type", None)),
                "lots": float(getattr(order, "volume_current", getattr(order, "volume_initial", 0.0))),
                "price": float(getattr(order, "price_open", 0.0)),
                "stop_loss": float(getattr(order, "sl", 0.0)) or None,
                "take_profit": float(getattr(order, "tp", 0.0)) or None,
                "magic": getattr(order, "magic", None),
                "comment": str(getattr(order, "comment", "") or ""),
            }
        )
    return serialized


def send_heartbeat() -> None:
    """Send heartbeat to VPS with current worker status."""
    global _mt5_state

    if _mt5_state.ensure_initialized():
        account_ok, account_error = validate_expected_account()
        if not account_ok:
            payload = {
                "worker_id": WORKER_ID,
                "mt5_connected": False,
                "account_login": EXPECTED_MT5_LOGIN,
                "connection_error": account_error,
                "open_positions": 0,
                "positions": [],
                "pending_orders": [],
                "dry_run": DRY_RUN,
            }
        else:
            account = mt5.account_info()
            positions = mt5.positions_get() or []
            pending_orders = mt5.orders_get() or []
            positions_payload = _serialize_positions(list(positions))
            pending_orders_payload = _serialize_pending_orders(list(pending_orders))
            payload = {
                "worker_id": WORKER_ID,
                "mt5_connected": True,
                "account_login": getattr(account, "login", None),
                "expected_account_login": EXPECTED_MT5_LOGIN,
                "broker": getattr(account, "server", None),
                "balance": getattr(account, "balance", None),
                "equity": getattr(account, "equity", None),
                "open_positions": len(positions),
                "positions": positions_payload,
                "pending_orders": pending_orders_payload,
                "dry_run": DRY_RUN,
            }
    else:
        payload = {
            "worker_id": WORKER_ID,
            "mt5_connected": False,
            "open_positions": 0,
            "positions": [],
            "pending_orders": [],
            "dry_run": DRY_RUN,
        }

    def _send():
        resp = requests.post(
            f"{API_BASE}/api/worker/heartbeat",
            json=payload,
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        return resp

    try:
        retry_request(_send)
        logger.debug(f"Heartbeat sent: positions={payload['open_positions']}, mt5={payload['mt5_connected']}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Heartbeat failed: {e}")


def get_next_signal() -> Optional[dict[str, Any]]:
    """Poll VPS for next pending signal."""
    def _get():
        resp = requests.get(
            f"{API_BASE}/api/worker/next-signal",
            params={"worker_id": WORKER_ID},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    try:
        signal_data = retry_request(_get)
        if signal_data:
            logger.info(f"Received signal: id={signal_data.get('id')}, symbol={signal_data.get('symbol')}, side={signal_data.get('side')}")
        return signal_data
    except requests.exceptions.RequestException as e:
        logger.warning(f"Signal poll failed: {e}")
        return None


def report(signal_id: str, status: str, message: str, **extra: Any) -> None:
    """Report execution status back to VPS."""
    payload = {
        "signal_id": signal_id,
        "worker_id": WORKER_ID,
        "status": status,
        "message": message,
        "dry_run": DRY_RUN,
        **extra,
    }

    def _report():
        resp = requests.post(
            f"{API_BASE}/api/worker/execution-report",
            json=payload,
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()

    try:
        retry_request(_report)
        logger.info(f"Reported signal {signal_id}: status={status}, message={message}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to report signal {signal_id}: {e} (status={status}, message={message})")


def execute_signal(signal: dict[str, Any]) -> None:
    """Execute a trading signal on MT5."""
    global _mt5_state

    signal_id = signal.get("id", "unknown")
    logger.info(f"Executing signal: {signal}")
    action = str(signal.get("action", "open")).lower()

    if DRY_RUN:
        # Dry-run mode: accept signal but don't place real order
        logger.info(
            f"[DRY_RUN] Would execute signal {signal_id}: action={action} side={signal.get('side').upper()} "
            f"lots={signal.get('lots')} symbol={signal.get('symbol')} ticket={signal.get('position_ticket')}"
        )
        report(signal_id, "filled", "DRY_RUN accepted signal; no MT5 order sent", lots=signal.get("lots"))
        return

    if not _mt5_state.ensure_initialized():
        report(signal_id, "rejected", "MT5 not connected or initialization failed")
        return

    account_ok, account_error = validate_expected_account()
    if not account_ok:
        report(signal_id, "rejected", account_error or "MT5 account login validation failed")
        return

    request: dict[str, Any]
    symbol = signal["symbol"]
    lots = float(signal["lots"])
    price: float

    if action == "close":
        position_ticket = signal.get("position_ticket")
        if position_ticket is None:
            report(signal_id, "rejected", "close signal missing position_ticket")
            return
        positions = mt5.positions_get(ticket=int(position_ticket)) or []
        if not positions:
            report(signal_id, "rejected", f"Position {position_ticket} not found")
            return
        position = positions[0]
        symbol = getattr(position, "symbol", symbol)
        if not mt5.symbol_select(symbol, True):
            error = mt5.last_error()
            report(signal_id, "rejected", f"symbol_select failed for {symbol}: {error}")
            return
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            report(signal_id, "rejected", f"no tick for {symbol}")
            return

        position_type = getattr(position, "type", None)
        # Close BUY with SELL at bid, close SELL with BUY at ask.
        if position_type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(getattr(position, "volume", lots)),
            "type": order_type,
            "position": int(position_ticket),
            "price": price,
            "deviation": 20,
            "magic": MAGIC,
            "comment": _mt5_safe_comment("vps_forex_close"),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
    elif action == "cancel":
        order_ticket = signal.get("order_ticket")
        if order_ticket is None:
            report(signal_id, "rejected", "cancel signal missing order_ticket")
            return
        orders = mt5.orders_get(ticket=int(order_ticket)) or []
        if not orders:
            report(signal_id, "rejected", f"Pending order {order_ticket} not found")
            return
        order = orders[0]
        symbol = getattr(order, "symbol", symbol)
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": int(order_ticket),
            "symbol": symbol,
            "magic": MAGIC,
            "comment": _mt5_safe_comment("vps_forex_cancel"),
        }
        price = float(getattr(order, "price_open", 0.0) or 0.0)
    else:
        if not mt5.symbol_select(symbol, True):
            error = mt5.last_error()
            report(signal_id, "rejected", f"symbol_select failed for {symbol}: {error}")
            return

        side = str(signal["side"]).lower()
        requested_order_type = str(signal.get("order_type") or "market").lower()
        comment = "vps_forex_brain"
        grid_id = signal.get("grid_id")
        grid_index = signal.get("grid_index")
        if grid_id:
            index_suffix = "" if grid_index is None else f":{grid_index}"
            comment = f"grid:{grid_id}{index_suffix}"
        comment = _mt5_safe_comment(comment)

        if requested_order_type == "limit":
            limit_price = signal.get("limit_price")
            if limit_price is None:
                report(signal_id, "rejected", "limit order missing limit_price")
                return
            price = float(limit_price)
            order_type = mt5.ORDER_TYPE_BUY_LIMIT if side == "buy" else mt5.ORDER_TYPE_SELL_LIMIT
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": lots,
                "type": order_type,
                "price": price,
                "sl": signal.get("stop_loss") or 0.0,
                "tp": signal.get("take_profit") or 0.0,
                "deviation": 20,
                "magic": MAGIC,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": getattr(mt5, "ORDER_FILLING_RETURN", mt5.ORDER_FILLING_IOC),
            }
        else:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                report(signal_id, "rejected", f"no tick for {symbol}")
                return

            order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
            price = tick.ask if side == "buy" else tick.bid
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": lots,
                "type": order_type,
                "price": price,
                "sl": signal.get("stop_loss") or 0.0,
                "tp": signal.get("take_profit") or 0.0,
                "deviation": 20,
                "magic": MAGIC,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

    result = mt5.order_send(request)
    if result is None:
        report(signal_id, "rejected", f"order_send returned None: {mt5.last_error()}")
        return

    success_retcodes = {mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_PLACED", mt5.TRADE_RETCODE_DONE)}
    if result.retcode not in success_retcodes:
        report(signal_id, "rejected", f"MT5 retcode={result.retcode}, comment={result.comment}")
        return

    logger.info(f"Order accepted: {signal_id} -> order_id={result.order}, price={price}")
    if action == "close":
        report(
            signal_id,
            "filled",
            "MT5 position closed",
            broker_order_id=str(result.order),
            executed_price=price,
            lots=float(request.get("volume", lots)),
        )
        return
    if action == "cancel":
        report(
            signal_id,
            "cancelled",
            "MT5 pending order cancelled",
            broker_order_id=str(signal.get("order_ticket") or result.order),
            executed_price=price,
            lots=float(request.get("volume", lots)),
        )
        return

    if request["action"] == mt5.TRADE_ACTION_PENDING:
        report(
            signal_id,
            "executing",
            "MT5 pending order placed",
            broker_order_id=str(result.order),
            executed_price=price,
            lots=float(signal["lots"]),
        )
        return
    report(signal_id, "filled", "MT5 order filled", broker_order_id=str(result.order), executed_price=price, lots=float(signal["lots"]))


def main() -> None:
    """Main worker loop."""
    global _mt5_state, _shutdown_requested

    logger.info(f"Starting Windows MT5 worker")
    logger.info(f"  Env File:  {ENV_FILE}")
    logger.info(f"  Worker ID: {WORKER_ID}")
    logger.info(f"  VPS API:   {API_BASE}")
    logger.info(f"  Dry Run:   {DRY_RUN}")
    logger.info(f"  Expected MT5 Login: {EXPECTED_MT5_LOGIN or 'not enforced'}")
    logger.info(f"  Poll Interval: {POLL_SECONDS}s")

    # Initial MT5 check
    if _mt5_state.ensure_initialized():
        account_ok, account_error = validate_expected_account()
        account = mt5.account_info()
        logger.info(f"MT5 connected: login={getattr(account, 'login', 'N/A')}, server={getattr(account, 'server', 'N/A')}, balance={getattr(account, 'balance', 'N/A')}")
        if not account_ok:
            logger.error("MT5 account validation failed at startup: %s", account_error)

    last_hb = 0.0

    while not _shutdown_requested:
        now = time.time()

        # Send heartbeat every 10 seconds
        if now - last_hb > 10:
            try:
                send_heartbeat()
                last_hb = now
            except Exception as exc:
                logger.error(f"Heartbeat error: {exc}")

        # Poll for signals
        try:
            signal = get_next_signal()
            if signal:
                execute_signal(signal)
        except Exception as exc:
            logger.error(f"Signal processing error: {exc}")

        # Sleep in small increments to respond to shutdown faster
        for _ in range(int(POLL_SECONDS * 10)):
            if _shutdown_requested:
                break
            time.sleep(0.1)

    # Cleanup
    logger.info("Worker shutting down...")
    _mt5_state.shutdown()
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
