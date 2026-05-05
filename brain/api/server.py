from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from starlette.responses import PlainTextResponse

from brain.data.bybit_data import BybitMarketDataProvider, BybitWebhookCache
from brain.data.forex_data import YFinanceForexProvider
from brain.signals.grid_strike import GridPlan, GridStrikeCandidate, build_grid_plan, scan_grid_candidates
from brain.signals.simple_strategy import simple_signal
from shared.models import ExecutionReport, ForexQuote, Signal, SignalAction, SignalSide, SignalStatus, WorkerHeartbeat, WorkerPosition
from shared.settings import load_settings

settings = load_settings()
app = FastAPI(title="Forex MT5 Bot Brain", version="0.1.0")
logger = logging.getLogger("forex-brain")


def create_market_data_provider():
    if settings.market_data.provider.lower() == "bybit":
        return BybitMarketDataProvider()
    return YFinanceForexProvider()


provider = create_market_data_provider()
bybit_webhook_cache = BybitWebhookCache()

SIGNALS: Dict[str, Signal] = {}
EXECUTIONS: List[ExecutionReport] = []
HEARTBEATS: Dict[str, WorkerHeartbeat] = {}
STATE_LOCK = threading.RLock()


@dataclass
class VirtualPosition:
    symbol: str
    side: SignalSide
    lots: float
    updated_at: datetime


VIRTUAL_POSITIONS: Dict[str, VirtualPosition] = {}
SCAN_STOP_EVENT = threading.Event()
SCAN_THREAD: Optional[threading.Thread] = None


class CreateSignalRequest(BaseModel):
    symbol: str
    side: str = "buy"
    action: str = "open"
    lots: float = 0.01
    position_ticket: Optional[int] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    target_worker_id: Optional[str] = None


class BybitWebhookPayload(BaseModel):
    symbol: str = "BTCUSD"
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    timestamp: Optional[datetime] = None


def _symbol_key(symbol: str) -> str:
    return symbol.upper().replace("/", "")


def _has_pending_signal_locked(symbol: str) -> bool:
    return any(
        s.symbol == symbol and s.status in {SignalStatus.CREATED, SignalStatus.CLAIMED, SignalStatus.EXECUTING}
        for s in SIGNALS.values()
    )


def _should_enqueue_signal_locked(signal: Signal) -> bool:
    if signal.action == SignalAction.CLOSE:
        return True
    symbol = _symbol_key(signal.symbol)
    if _has_pending_signal_locked(symbol):
        return False
    current = VIRTUAL_POSITIONS.get(symbol)
    if current is None:
        return True
    # Keep one directional exposure per symbol. Opposite side is allowed to
    # flip (close existing and reopen new direction on netting accounts).
    return current.side != signal.side


def _position_profit_pct(position: WorkerPosition) -> Optional[float]:
    if position.entry_price in (None, 0.0) or position.current_price is None:
        return None
    entry = float(position.entry_price)
    current = float(position.current_price)
    if position.side == SignalSide.BUY:
        return ((current - entry) / entry) * 100.0
    return ((entry - current) / entry) * 100.0


def _has_pending_close_signal_locked(worker_id: str, ticket: int) -> bool:
    for signal in SIGNALS.values():
        if signal.action != SignalAction.CLOSE:
            continue
        if signal.position_ticket != ticket:
            continue
        if signal.target_worker_id not in (None, worker_id):
            continue
        if signal.status in {SignalStatus.CREATED, SignalStatus.CLAIMED, SignalStatus.EXECUTING}:
            return True
    return False


def _enqueue_auto_close_signals_locked(worker_id: str, profit_pct: float) -> list[Signal]:
    worker = HEARTBEATS.get(worker_id)
    if worker is None:
        return []

    created: list[Signal] = []
    for position in worker.positions:
        if position.ticket is None:
            continue
        position_profit_pct = _position_profit_pct(position)
        if position_profit_pct is None or position_profit_pct < profit_pct:
            continue
        ticket = int(position.ticket)
        if _has_pending_close_signal_locked(worker_id, ticket):
            continue

        close_side = SignalSide.SELL if position.side == SignalSide.BUY else SignalSide.BUY
        close_signal = Signal(
            symbol=_symbol_key(position.symbol),
            side=close_side,
            action=SignalAction.CLOSE,
            lots=float(position.lots),
            position_ticket=ticket,
            confidence=1.0,
            reason=f"auto-close-profit: {position_profit_pct:.4f}% >= {profit_pct:.4f}%",
            target_worker_id=worker_id,
        )
        SIGNALS[close_signal.id] = close_signal
        created.append(close_signal)
    return created


def _update_virtual_position_on_fill(report: ExecutionReport, signal: Signal) -> None:
    if report.status != SignalStatus.FILLED:
        return

    symbol = _symbol_key(signal.symbol)
    filled_lots = float(report.lots if report.lots is not None else signal.lots)
    if filled_lots <= 0:
        return

    now = datetime.now(timezone.utc)
    current = VIRTUAL_POSITIONS.get(symbol)
    if current is None:
        VIRTUAL_POSITIONS[symbol] = VirtualPosition(
            symbol=symbol,
            side=signal.side,
            lots=filled_lots,
            updated_at=now,
        )
        return

    if current.side == signal.side:
        current.lots += filled_lots
        current.updated_at = now
        return

    remaining = current.lots - filled_lots
    if remaining > 1e-9:
        current.lots = remaining
        current.updated_at = now
        return
    if remaining < -1e-9:
        VIRTUAL_POSITIONS[symbol] = VirtualPosition(
            symbol=symbol,
            side=signal.side,
            lots=abs(remaining),
            updated_at=now,
        )
        return
    VIRTUAL_POSITIONS.pop(symbol, None)


def _run_strategy_scan_once() -> list[Signal]:
    created: list[Signal] = []
    for symbol in settings.market_data.symbols:
        try:
            candles = provider.fetch_candles(
                symbol,
                period=settings.market_data.candles_period,
                interval=settings.market_data.candles_interval,
            )
            signal = simple_signal(symbol, candles, settings)
            if signal is None:
                continue

            signal.symbol = _symbol_key(signal.symbol)
            with STATE_LOCK:
                if not _should_enqueue_signal_locked(signal):
                    continue
                SIGNALS[signal.id] = signal
            created.append(signal)
        except Exception as exc:
            logger.warning("scan failed for %s: %s", symbol, exc)
    return created


def _strategy_scan_loop() -> None:
    interval = max(1, int(settings.market_data.refresh_seconds))
    logger.info("auto-scan loop started (interval=%ss, symbols=%s)", interval, ",".join(settings.market_data.symbols))
    while not SCAN_STOP_EVENT.is_set():
        created = _run_strategy_scan_once()
        if created:
            logger.info(
                "auto-scan created %d signal(s): %s",
                len(created),
                ", ".join(f"{s.symbol}:{s.side.value}" for s in created),
            )
        SCAN_STOP_EVENT.wait(interval)
    logger.info("auto-scan loop stopped")


@app.on_event("startup")
def startup_strategy_loop() -> None:
    global SCAN_THREAD
    live_mode = settings.app.mode.lower() == "live"
    if not live_mode or not settings.strategy.enabled:
        logger.info("auto-scan loop disabled (mode=%s, strategy.enabled=%s)", settings.app.mode, settings.strategy.enabled)
        return
    if SCAN_THREAD and SCAN_THREAD.is_alive():
        return
    SCAN_STOP_EVENT.clear()
    SCAN_THREAD = threading.Thread(target=_strategy_scan_loop, name="strategy-scan-loop", daemon=True)
    SCAN_THREAD.start()


@app.on_event("shutdown")
def shutdown_strategy_loop() -> None:
    SCAN_STOP_EVENT.set()
    if SCAN_THREAD and SCAN_THREAD.is_alive():
        SCAN_THREAD.join(timeout=3)


def require_worker_token(
    x_worker_token: str = Header(default=""),
    worker_token: str = Query(default=""),
) -> None:
    if settings.api.worker_token == "CHANGE_ME_LONG_RANDOM_TOKEN":
        # Allow local testing until token is changed.
        return
    if x_worker_token != settings.api.worker_token and worker_token != settings.api.worker_token:
        raise HTTPException(status_code=401, detail="invalid worker token")


@app.get("/health")
def health() -> dict:
    with STATE_LOCK:
        signal_count = len(SIGNALS)
        worker_count = len(HEARTBEATS)
        virtual_positions = len(VIRTUAL_POSITIONS)
    return {
        "ok": True,
        "mode": settings.app.mode,
        "signals": signal_count,
        "workers": worker_count,
        "virtual_positions": virtual_positions,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/market/quotes", response_model=list[ForexQuote])
def quotes() -> list[ForexQuote]:
    cached = bybit_webhook_cache.fetch_quotes(settings.market_data.symbols)
    if cached and settings.market_data.provider.lower() == "bybit":
        return cached
    return provider.fetch_quotes(settings.market_data.symbols)


@app.post("/api/market/bybit-webhook")
def bybit_market_webhook(payload: BybitWebhookPayload) -> dict:
    quote = bybit_webhook_cache.update_quote(
        symbol=payload.symbol,
        price=payload.price,
        bid=payload.bid,
        ask=payload.ask,
        timestamp=payload.timestamp,
    )
    return {"ok": True, "quote": quote.model_dump(mode="json")}


@app.post("/api/scan", response_model=list[Signal])
def scan() -> list[Signal]:
    return _run_strategy_scan_once()


def _load_grid_strike_candles() -> dict[str, object]:
    candles_by_symbol: dict[str, object] = {}
    for symbol in settings.market_data.symbols:
        try:
            candles_by_symbol[symbol] = provider.fetch_candles(
                symbol,
                period=settings.market_data.candles_period,
                interval=settings.market_data.candles_interval,
            )
        except Exception as exc:
            print(f"WARN grid strike candle load failed for {symbol}: {exc}")
    return candles_by_symbol


@app.post("/api/grid-strike/scan", response_model=list[GridStrikeCandidate])
def grid_strike_scan() -> list[GridStrikeCandidate]:
    """Rank currency pairs that currently look suitable for grid scalping."""
    if not settings.grid_strike.enabled:
        return []
    return scan_grid_candidates(_load_grid_strike_candles(), settings.grid_strike)


@app.post("/api/grid-strike/plan", response_model=Optional[GridPlan])
def grid_strike_plan() -> Optional[GridPlan]:
    """Build a buy/sell strike grid for the best currently tradeable pair."""
    candidates = grid_strike_scan()
    if not candidates:
        return None
    best = candidates[0]
    return build_grid_plan(best, mid_price=best.mid_price, settings=settings.grid_strike)


@app.post("/api/signals/create", response_model=Signal)
def create_signal_from_grid(req: CreateSignalRequest = Body(...)) -> Signal:
    """Create a signal directly (for testing or manual trading)."""
    signal = Signal(
        symbol=_symbol_key(req.symbol),
        side=SignalSide(req.side.lower()),
        action=SignalAction(req.action.lower()),
        lots=req.lots,
        position_ticket=req.position_ticket,
        stop_loss=req.stop_loss,
        take_profit=req.take_profit,
        confidence=0.95,
        reason="manual-create",
        target_worker_id=req.target_worker_id,
    )
    with STATE_LOCK:
        SIGNALS[signal.id] = signal
    return signal


@app.get("/api/signals", response_model=list[Signal])
def list_signals() -> list[Signal]:
    with STATE_LOCK:
        return list(SIGNALS.values())


@app.get("/api/orders")
def list_orders(
    limit: int = Query(default=100, ge=1, le=1000),
    worker_id: Optional[str] = None,
    status: Optional[SignalStatus] = None,
    _: None = Depends(require_worker_token),
) -> list[dict[str, Any]]:
    with STATE_LOCK:
        reports = sorted(EXECUTIONS, key=lambda row: row.reported_at, reverse=True)
        rows: list[dict[str, Any]] = []
        for report in reports:
            if worker_id and report.worker_id != worker_id:
                continue
            if status and report.status != status:
                continue
            signal = SIGNALS.get(report.signal_id)
            rows.append(
                {
                    "signal_id": report.signal_id,
                    "worker_id": report.worker_id,
                    "status": report.status.value,
                    "broker_order_id": report.broker_order_id,
                    "executed_price": report.executed_price,
                    "lots": report.lots,
                    "message": report.message,
                    "reported_at": report.reported_at.isoformat(),
                    "symbol": signal.symbol if signal else None,
                    "side": signal.side.value if signal else None,
                    "action": signal.action.value if signal else None,
                    "position_ticket": signal.position_ticket if signal else None,
                    "reason": signal.reason if signal else None,
                }
            )
            if len(rows) >= limit:
                break
        return rows


@app.get("/api/workers", response_model=list[WorkerHeartbeat])
def list_workers(_: None = Depends(require_worker_token)) -> list[WorkerHeartbeat]:
    with STATE_LOCK:
        return sorted(HEARTBEATS.values(), key=lambda hb: hb.timestamp, reverse=True)


@app.get("/api/workers/{worker_id}", response_model=WorkerHeartbeat)
def get_worker(worker_id: str, _: None = Depends(require_worker_token)) -> WorkerHeartbeat:
    with STATE_LOCK:
        worker = HEARTBEATS.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    return worker


@app.get("/api/workers/{worker_id}/positions", response_model=list[WorkerPosition])
def get_worker_positions(worker_id: str, _: None = Depends(require_worker_token)) -> list[WorkerPosition]:
    with STATE_LOCK:
        worker = HEARTBEATS.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    return worker.positions


@app.post("/api/workers/{worker_id}/auto-close")
def execute_auto_close(
    worker_id: str,
    profit_pct: float = Query(default=3.0, gt=0.0),
    _: None = Depends(require_worker_token),
) -> dict[str, Any]:
    with STATE_LOCK:
        worker = HEARTBEATS.get(worker_id)
        if worker is None:
            raise HTTPException(status_code=404, detail="worker not found")
        created = _enqueue_auto_close_signals_locked(worker_id, profit_pct)
        return {
            "ok": True,
            "worker_id": worker_id,
            "profit_pct": profit_pct,
            "positions_seen": len(worker.positions),
            "close_signals_created": len(created),
            "signal_ids": [signal.id for signal in created],
        }


def _claim_next_signal(worker_id: str) -> Optional[Signal]:
    with STATE_LOCK:
        for signal in SIGNALS.values():
            if signal.target_worker_id and signal.target_worker_id != worker_id:
                continue
            if signal.status == SignalStatus.CREATED:
                signal.status = SignalStatus.CLAIMED
                signal.worker_id = worker_id
                signal.claimed_at = datetime.now(timezone.utc)
                return signal
    return None


@app.get("/api/worker/next-signal", response_model=Optional[Signal])
def next_signal(worker_id: str, _: None = Depends(require_worker_token)) -> Optional[Signal]:
    return _claim_next_signal(worker_id)


@app.get("/api/worker/next-signal-plain", response_class=PlainTextResponse)
def next_signal_plain(worker_id: str, _: None = Depends(require_worker_token)) -> str:
    signal = _claim_next_signal(worker_id)
    if signal is None:
        return ""
    stop_loss = "" if signal.stop_loss is None else str(signal.stop_loss)
    take_profit = "" if signal.take_profit is None else str(signal.take_profit)
    return "|".join(
        [
            signal.id,
            signal.symbol,
            signal.side.value,
            str(signal.lots),
            stop_loss,
            take_profit,
        ]
    )


@app.post("/api/worker/execution-report")
def execution_report(report: ExecutionReport, _: None = Depends(require_worker_token)) -> dict:
    with STATE_LOCK:
        EXECUTIONS.append(report)
        signal = SIGNALS.get(report.signal_id)
        if signal:
            signal.status = report.status
            _update_virtual_position_on_fill(report, signal)
        report_count = len(EXECUTIONS)
    return {"ok": True, "reports": report_count}


@app.post("/api/worker/heartbeat")
def heartbeat(hb: WorkerHeartbeat, _: None = Depends(require_worker_token)) -> dict:
    with STATE_LOCK:
        HEARTBEATS[hb.worker_id] = hb
        created = []
        if hb.mt5_connected and settings.mt5_worker.auto_close_enabled:
            created = _enqueue_auto_close_signals_locked(hb.worker_id, settings.mt5_worker.auto_close_profit_pct)
            if created:
                logger.info(
                    "auto-close created %d close signal(s) for worker=%s",
                    len(created),
                    hb.worker_id,
                )
    return {"ok": True, "server_time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/worker/heartbeat-ping", response_class=PlainTextResponse)
def heartbeat_ping(
    worker_id: str,
    mt5_connected: bool,
    account_login: Optional[int] = None,
    broker: Optional[str] = None,
    balance: Optional[float] = None,
    equity: Optional[float] = None,
    open_positions: int = 0,
    _: None = Depends(require_worker_token),
) -> str:
    with STATE_LOCK:
        HEARTBEATS[worker_id] = WorkerHeartbeat(
            worker_id=worker_id,
            mt5_connected=mt5_connected,
            account_login=account_login,
            broker=broker,
            balance=balance,
            equity=equity,
            open_positions=open_positions,
        )
    return "ok"


@app.get("/api/worker/execution-report-ping", response_class=PlainTextResponse)
def execution_report_ping(
    signal_id: str,
    worker_id: str,
    status: SignalStatus,
    broker_order_id: Optional[str] = None,
    executed_price: Optional[float] = None,
    lots: Optional[float] = None,
    message: str = "",
    _: None = Depends(require_worker_token),
) -> str:
    report = ExecutionReport(
        signal_id=signal_id,
        worker_id=worker_id,
        status=status,
        broker_order_id=broker_order_id,
        executed_price=executed_price,
        lots=lots,
        message=message,
    )
    with STATE_LOCK:
        EXECUTIONS.append(report)
        signal = SIGNALS.get(report.signal_id)
        if signal:
            signal.status = report.status
            _update_virtual_position_on_fill(report, signal)
    return "ok"


@app.post("/api/worker/test-signal")
def create_test_signal(
    symbol: str,
    side: str,
    lots: float,
    worker_id: str = "test-worker",
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
) -> Signal:
    """Create a test signal for worker verification."""
    signal = Signal(
        symbol=_symbol_key(symbol),
        side=SignalSide(side.lower()),
        action=SignalAction.OPEN,
        lots=lots,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=0.95,
        reason="test-signal",
    )
    with STATE_LOCK:
        SIGNALS[signal.id] = signal
    return signal
