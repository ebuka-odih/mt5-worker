from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from starlette.responses import PlainTextResponse

from brain.data.bybit_data import BybitMarketDataProvider, BybitWebhookCache
from brain.data.forex_data import YFinanceForexProvider
from brain.risk.funded_challenge import AccountRiskSnapshot, PositionExposure, evaluate_entry_guard
from brain.signals.grid_strike import GridPlan, GridStrikeCandidate, build_grid_plan, score_grid_candidate
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
LAST_CLOSE_TIMES: Dict[str, datetime] = {}
ENTRY_BLOCK_COUNTS: Counter[str] = Counter()
GRID_REJECTION_COUNTS: Counter[str] = Counter()
CLOSE_REASON_COUNTS: Counter[str] = Counter()
GRID_RECYCLE_COUNTS: Counter[str] = Counter()
SCAN_STOP_EVENT = threading.Event()
SCAN_THREAD: Optional[threading.Thread] = None


class CreateSignalRequest(BaseModel):
    symbol: str
    side: str = "buy"
    action: str = "open"
    lots: Optional[float] = None
    position_ticket: Optional[int] = None
    limit_price: Optional[float] = None
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


def _bump_counter_locked(counter: Counter[str], reason: str) -> None:
    if reason:
        counter[reason] += 1


def _bucket_reason(reason: str) -> str:
    if not reason:
        return "unknown"
    return reason.split(":", 1)[0].strip()


def _cooldown_remaining_seconds_locked(symbol: str) -> int:
    last_close = LAST_CLOSE_TIMES.get(symbol)
    cooldown_seconds = max(int(settings.mt5_worker.reentry_cooldown_seconds), 0)
    if not last_close or cooldown_seconds <= 0:
        return 0
    elapsed = (datetime.now(timezone.utc) - last_close).total_seconds()
    return max(int(cooldown_seconds - elapsed), 0)


def _basket_net_profit(worker: WorkerHeartbeat) -> float:
    return round(sum(position.net_profit for position in worker.positions), 2)


def _should_enqueue_signal_locked(
    signal: Signal,
    extra_positions: Optional[list[PositionExposure]] = None,
    bypass_cooldown: bool = False,
) -> bool:
    if signal.action == SignalAction.CLOSE:
        return True

    symbol = _symbol_key(signal.symbol)
    is_grid_signal = bool(signal.grid_id)

    if not is_grid_signal and _has_pending_signal_locked(symbol):
        _bump_counter_locked(ENTRY_BLOCK_COUNTS, "pending-signal")
        return False
    if not bypass_cooldown and _cooldown_remaining_seconds_locked(symbol) > 0:
        _bump_counter_locked(ENTRY_BLOCK_COUNTS, "reentry-cooldown")
        logger.info("entry blocked for %s by cooldown", symbol)
        return False

    current = VIRTUAL_POSITIONS.get(symbol)
    if current is not None and not is_grid_signal:
        # Keep one directional exposure per symbol for legacy single-entry flow.
        # Opposite side is allowed to flip (close existing and reopen new
        # direction on netting accounts). Grid plans intentionally bypass this
        # gate so they can stage multiple buy/sell ladder levels.
        if current.side == signal.side:
            _bump_counter_locked(ENTRY_BLOCK_COUNTS, "same-side-virtual-position")
            return False

    guard = _entry_guard_locked(signal, extra_positions=extra_positions)
    if not guard.allowed:
        _bump_counter_locked(ENTRY_BLOCK_COUNTS, _bucket_reason(guard.reason))
        logger.info("entry blocked for %s:%s - %s", signal.symbol, signal.side.value, guard.reason)
        return False
    return True


def _position_exposures_from_heartbeats_locked() -> list[PositionExposure]:
    exposures: list[PositionExposure] = []
    for heartbeat in HEARTBEATS.values():
        for position in heartbeat.positions:
            exposures.append(
                PositionExposure(
                    symbol=_symbol_key(position.symbol),
                    side=position.side.value,
                    lots=float(position.lots),
                    entry_price=position.entry_price,
                    current_price=position.current_price,
                )
            )
    return exposures


def _pending_open_signal_exposures_locked() -> list[PositionExposure]:
    exposures: list[PositionExposure] = []
    active_statuses = {SignalStatus.CREATED, SignalStatus.CLAIMED, SignalStatus.EXECUTING}
    for signal in SIGNALS.values():
        if signal.action != SignalAction.OPEN or signal.status not in active_statuses:
            continue
        reference_price = signal.limit_price
        exposures.append(
            PositionExposure(
                symbol=_symbol_key(signal.symbol),
                side=signal.side.value,
                lots=float(signal.lots),
                entry_price=reference_price,
                current_price=reference_price,
            )
        )
    return exposures


def _risk_snapshot_locked(extra_positions: Optional[list[PositionExposure]] = None) -> AccountRiskSnapshot:
    latest_heartbeat = max(HEARTBEATS.values(), key=lambda hb: hb.timestamp, default=None)
    balance = float(latest_heartbeat.balance) if latest_heartbeat and latest_heartbeat.balance is not None else settings.risk.starting_balance
    equity = float(latest_heartbeat.equity) if latest_heartbeat and latest_heartbeat.equity is not None else balance

    positions = _position_exposures_from_heartbeats_locked()
    if not positions:
        positions = [
            PositionExposure(symbol=symbol, side=position.side.value, lots=float(position.lots))
            for symbol, position in VIRTUAL_POSITIONS.items()
        ]

    positions.extend(_pending_open_signal_exposures_locked())
    if extra_positions:
        positions.extend(extra_positions)

    return AccountRiskSnapshot(balance=balance, equity=equity, positions=positions)


def _entry_guard_locked(signal: Signal, extra_positions: Optional[list[PositionExposure]] = None):
    return evaluate_entry_guard(
        symbol=_symbol_key(signal.symbol),
        side=signal.side.value,
        snapshot=_risk_snapshot_locked(extra_positions=extra_positions),
        risk=settings.risk,
    )


def _position_profit_pct(position: WorkerPosition) -> Optional[float]:
    if position.entry_price in (None, 0.0) or position.current_price is None:
        return None
    entry = float(position.entry_price)
    current = float(position.current_price)
    if position.side == SignalSide.BUY:
        return ((current - entry) / entry) * 100.0
    return ((entry - current) / entry) * 100.0


def _position_net_profit(position: WorkerPosition) -> float:
    return position.net_profit


def _position_age_minutes(position: WorkerPosition) -> Optional[float]:
    if position.opened_at is None:
        return None
    opened_at = position.opened_at if position.opened_at.tzinfo else position.opened_at.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - opened_at).total_seconds() / 60.0, 0.0)


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
    basket_net_profit = sum(_position_net_profit(position) for position in worker.positions)
    basket_take_profit = max(float(settings.mt5_worker.basket_take_profit_usd), 0.0)
    emergency_pct = max(float(settings.mt5_worker.volatility_spike_close_pct), 0.0)
    stale_minutes = max(int(settings.mt5_worker.stale_position_minutes), 0)
    close_loss_pct = max(float(settings.mt5_worker.auto_close_loss_pct), 0.0)
    for position in worker.positions:
        if position.ticket is None:
            continue
        position_profit_pct = _position_profit_pct(position)
        if position_profit_pct is None:
            continue
        ticket = int(position.ticket)
        if _has_pending_close_signal_locked(worker_id, ticket):
            continue

        close_reason: Optional[str] = None
        net_profit = _position_net_profit(position)
        age_minutes = _position_age_minutes(position)
        adverse_move_pct = max(-position_profit_pct, 0.0)
        stale_threshold_hit = stale_minutes > 0 and age_minutes is not None and age_minutes >= stale_minutes

        if position_profit_pct >= profit_pct:
            close_reason = f"net-tp-hit:{position_profit_pct:.4f}% >= {profit_pct:.4f}%"
        elif close_loss_pct > 0 and adverse_move_pct >= close_loss_pct:
            close_reason = f"net-sl-hit:{adverse_move_pct:.4f}% >= {close_loss_pct:.4f}%"
        elif basket_take_profit > 0 and basket_net_profit >= basket_take_profit:
            close_reason = f"basket-tp-hit:{basket_net_profit:.2f} >= {basket_take_profit:.2f}"
        elif stale_threshold_hit and net_profit >= 0:
            close_reason = f"stale-exit:{age_minutes:.1f}m >= {stale_minutes}m"
        elif emergency_pct > 0 and adverse_move_pct >= emergency_pct:
            close_reason = f"volatility-spike:{adverse_move_pct:.4f}% >= {emergency_pct:.4f}%"

        if close_reason is None:
            if stale_threshold_hit and net_profit < 0:
                logger.info(
                    "auto-close blocked worker=%s symbol=%s ticket=%s reason=stale-loss-blocked age_minutes=%.1f stale_minutes=%s net_pnl=%.2f profit_pct=%.4f adverse_move_pct=%.4f",
                    worker_id,
                    position.symbol,
                    ticket,
                    age_minutes,
                    stale_minutes,
                    net_profit,
                    position_profit_pct,
                    adverse_move_pct,
                )
            continue

        close_side = SignalSide.SELL if position.side == SignalSide.BUY else SignalSide.BUY
        close_signal = Signal(
            symbol=_symbol_key(position.symbol),
            side=close_side,
            action=SignalAction.CLOSE,
            lots=float(position.lots),
            position_ticket=ticket,
            confidence=1.0,
            reason=f"auto-close:{close_reason}; net_pnl={net_profit:.2f}",
            close_reason=close_reason,
            target_worker_id=worker_id,
        )
        SIGNALS[close_signal.id] = close_signal
        _bump_counter_locked(CLOSE_REASON_COUNTS, _bucket_reason(close_reason))
        logger.info(
            "auto-close queued worker=%s symbol=%s ticket=%s reason=%s basket_net_pnl=%.2f net_pnl=%.2f profit_pct=%.4f adverse_move_pct=%.4f age_minutes=%s stale_minutes=%s",
            worker_id,
            position.symbol,
            ticket,
            close_reason,
            basket_net_profit,
            net_profit,
            position_profit_pct,
            adverse_move_pct,
            f"{age_minutes:.1f}" if age_minutes is not None else "n/a",
            stale_minutes,
        )
        created.append(close_signal)
    return created


def _enqueue_reopen_after_close_locked(signal: Signal, report: ExecutionReport) -> Optional[Signal]:
    if signal.action != SignalAction.CLOSE:
        return None
    if report.status != SignalStatus.FILLED:
        return None
    LAST_CLOSE_TIMES[_symbol_key(signal.symbol)] = report.reported_at
    if not settings.mt5_worker.auto_reopen_after_close:
        return None

    reopen_side = SignalSide.BUY if signal.side == SignalSide.SELL else SignalSide.SELL
    reopen_signal = Signal(
        symbol=_symbol_key(signal.symbol),
        side=reopen_side,
        action=SignalAction.OPEN,
        lots=float(report.lots if report.lots is not None else signal.lots),
        confidence=1.0,
        reason=f"auto-reopen-after-close:{signal.id}",
        target_worker_id=signal.target_worker_id or report.worker_id,
    )

    if not _should_enqueue_signal_locked(reopen_signal, bypass_cooldown=True):
        return None
    SIGNALS[reopen_signal.id] = reopen_signal
    _bump_counter_locked(GRID_RECYCLE_COUNTS, "auto-reopen-after-close")
    return reopen_signal


def _parse_positions_json(raw_payload: Optional[str]) -> list[WorkerPosition]:
    if not raw_payload:
        return []
    try:
        payload = json.loads(raw_payload)
    except Exception as exc:
        logger.warning("heartbeat-ping positions_json parse failed: %s", exc)
        return []

    if not isinstance(payload, list):
        logger.warning("heartbeat-ping positions_json is not a list")
        return []

    positions: list[WorkerPosition] = []
    for idx, row in enumerate(payload):
        if not isinstance(row, dict):
            logger.warning("heartbeat-ping positions_json row[%d] ignored (not object)", idx)
            continue
        try:
            positions.append(WorkerPosition.model_validate(row))
        except Exception as exc:
            logger.warning("heartbeat-ping positions_json row[%d] validation failed: %s", idx, exc)
    return positions


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


def _signal_matches_position(signal: Signal, worker_id: str, position: WorkerPosition) -> bool:
    if signal.action != SignalAction.OPEN:
        return False
    if signal.status != SignalStatus.EXECUTING:
        return False
    target_worker_id = signal.worker_id or signal.target_worker_id
    if target_worker_id not in (None, worker_id):
        return False
    if _symbol_key(signal.symbol) != _symbol_key(position.symbol):
        return False
    if signal.side != position.side:
        return False
    if signal.grid_id and signal.grid_index is not None:
        expected_comment = f"grid:{signal.grid_id}:{signal.grid_index}"
        if position.comment.strip() != expected_comment:
            return False
    elif signal.limit_price is not None and position.entry_price is not None:
        if abs(float(signal.limit_price) - float(position.entry_price)) > 1e-6:
            return False
    return True


def _sync_executing_signals_from_positions_locked(hb: WorkerHeartbeat) -> None:
    for position in hb.positions:
        for signal in SIGNALS.values():
            if not _signal_matches_position(signal, hb.worker_id, position):
                continue
            if any(
                report.signal_id == signal.id
                and report.worker_id == hb.worker_id
                and report.status == SignalStatus.FILLED
                and report.message == "position confirmed by heartbeat"
                for report in EXECUTIONS
            ):
                break
            report = ExecutionReport(
                signal_id=signal.id,
                worker_id=hb.worker_id,
                status=SignalStatus.FILLED,
                broker_order_id=str(position.ticket) if position.ticket is not None else None,
                executed_price=position.entry_price,
                lots=float(position.lots),
                message="position confirmed by heartbeat",
            )
            EXECUTIONS.append(report)
            signal.status = SignalStatus.FILLED
            _update_virtual_position_on_fill(report, signal)
            break


def _grid_level_to_signal(plan: GridPlan, level, grid_id: str) -> Signal:
    side = SignalSide(level.side.lower())
    stop_loss = getattr(level, "stop_loss", None)
    take_profit = getattr(level, "take_profit", None)
    return Signal(
        symbol=_symbol_key(plan.symbol),
        side=side,
        order_type="limit",
        action=SignalAction.OPEN,
        lots=float(level.lots),
        limit_price=float(level.price),
        stop_loss=float(stop_loss) if stop_loss is not None else None,
        take_profit=float(take_profit) if take_profit is not None else None,
        confidence=float(plan.score),
        reason=f"grid-strike:{plan.reason}",
        grid_id=grid_id,
        grid_index=int(level.index),
    )


def _grid_plan_signals_locked(plan: GridPlan) -> list[Signal]:
    created: list[Signal] = []
    staged_positions: list[PositionExposure] = []
    grid_id = f"{_symbol_key(plan.symbol)}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"

    for level in [*plan.buy_levels, *plan.sell_levels]:
        signal = _grid_level_to_signal(plan, level, grid_id)
        projected = staged_positions + [
            PositionExposure(
                symbol=_symbol_key(signal.symbol),
                side=signal.side.value,
                lots=float(signal.lots),
                entry_price=signal.limit_price,
                current_price=signal.limit_price,
            )
        ]
        if not _should_enqueue_signal_locked(signal, extra_positions=projected):
            continue
        SIGNALS[signal.id] = signal
        staged_positions.append(projected[-1])
        created.append(signal)
    return created


def _run_strategy_scan_once() -> list[Signal]:
    created: list[Signal] = []
    for symbol in settings.market_data.symbols:
        try:
            candles = provider.fetch_candles(
                symbol,
                period=settings.market_data.candles_period,
                interval=settings.market_data.candles_interval,
            )

            if settings.grid_strike.enabled:
                candidate = score_grid_candidate(symbol, candles, settings.grid_strike)
                if candidate.tradeable:
                    plan = build_grid_plan(candidate, mid_price=candidate.mid_price, settings=settings.grid_strike)
                    with STATE_LOCK:
                        planned = _grid_plan_signals_locked(plan)
                    created.extend(planned)
                    continue
                else:
                    with STATE_LOCK:
                        _bump_counter_locked(GRID_REJECTION_COUNTS, _bucket_reason(candidate.reason))

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
    all_candidates = [score_grid_candidate(symbol, candles, settings.grid_strike) for symbol, candles in _load_grid_strike_candles().items()]
    for candidate in all_candidates:
        if not candidate.tradeable:
            reason = candidate.reason or "not-tradeable"
            _bump_counter_locked(GRID_REJECTION_COUNTS, _bucket_reason(reason))
            logger.info("grid candidate rejected symbol=%s reason=%s", candidate.symbol, reason)
    tradeable = [candidate for candidate in all_candidates if candidate.tradeable]
    return sorted(tradeable, key=lambda candidate: candidate.score, reverse=True)


@app.post("/api/grid-strike/scan-all", response_model=list[GridStrikeCandidate])
def grid_strike_scan_all() -> list[GridStrikeCandidate]:
    if not settings.grid_strike.enabled:
        return []
    candidates = [score_grid_candidate(symbol, candles, settings.grid_strike) for symbol, candles in _load_grid_strike_candles().items()]
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


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
    symbol_key = _symbol_key(req.symbol)
    lots = req.lots if req.lots is not None else settings.grid_strike.get_lots(symbol_key)
    signal = Signal(
        symbol=symbol_key,
        side=SignalSide(req.side.lower()),
        action=SignalAction(req.action.lower()),
        lots=lots,
        position_ticket=req.position_ticket,
        limit_price=req.limit_price,
        stop_loss=req.stop_loss,
        take_profit=req.take_profit,
        confidence=0.95,
        reason="manual-create",
        target_worker_id=req.target_worker_id,
    )
    with STATE_LOCK:
        guard = _entry_guard_locked(signal)
        if signal.action == SignalAction.OPEN and not guard.allowed:
            raise HTTPException(status_code=409, detail=guard.reason)
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
                    "close_reason": signal.close_reason if signal else None,
                }
            )
            if len(rows) >= limit:
                break
        return rows


@app.get("/api/workers", response_model=list[WorkerHeartbeat])
def list_workers(_: None = Depends(require_worker_token)) -> list[WorkerHeartbeat]:
    with STATE_LOCK:
        return sorted(HEARTBEATS.values(), key=lambda hb: hb.timestamp, reverse=True)


@app.get("/api/diagnostics/summary")
def diagnostics_summary(_: None = Depends(require_worker_token)) -> dict[str, Any]:
    with STATE_LOCK:
        workers = [
            {
                "worker_id": worker.worker_id,
                "basket_net_pnl": _basket_net_profit(worker),
                "open_positions": len(worker.positions),
                "equity": worker.equity,
                "balance": worker.balance,
                "last_heartbeat": worker.timestamp.isoformat(),
            }
            for worker in sorted(HEARTBEATS.values(), key=lambda hb: hb.timestamp, reverse=True)
        ]
        cooldowns = {
            symbol: {
                "last_close_at": last_close.isoformat(),
                "cooldown_remaining_seconds": _cooldown_remaining_seconds_locked(symbol),
            }
            for symbol, last_close in LAST_CLOSE_TIMES.items()
        }
        return {
            "time": datetime.now(timezone.utc).isoformat(),
            "entry_block_counts": dict(ENTRY_BLOCK_COUNTS),
            "grid_rejection_counts": dict(GRID_REJECTION_COUNTS),
            "close_reason_counts": dict(CLOSE_REASON_COUNTS),
            "grid_recycle_counts": dict(GRID_RECYCLE_COUNTS),
            "cooldowns": cooldowns,
            "workers": workers,
        }


@app.get("/api/workers/{worker_id}/diagnostics")
def worker_diagnostics(worker_id: str, _: None = Depends(require_worker_token)) -> dict[str, Any]:
    with STATE_LOCK:
        worker = HEARTBEATS.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")

    return {
        "worker_id": worker.worker_id,
        "basket_net_pnl": _basket_net_profit(worker),
        "positions": [
            {
                "ticket": position.ticket,
                "symbol": position.symbol,
                "side": position.side.value,
                "net_profit": position.net_profit,
                "profit_pct": _position_profit_pct(position),
                "age_minutes": _position_age_minutes(position),
            }
            for position in worker.positions
        ],
    }


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
    position_ticket = "" if signal.position_ticket is None else str(signal.position_ticket)
    return "|".join(
        [
            signal.id,
            signal.symbol,
            signal.side.value,
            str(signal.lots),
            stop_loss,
            take_profit,
            signal.action.value,
            position_ticket,
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
            _enqueue_reopen_after_close_locked(signal, report)
        report_count = len(EXECUTIONS)
    return {"ok": True, "reports": report_count}


@app.post("/api/worker/heartbeat")
def heartbeat(hb: WorkerHeartbeat, _: None = Depends(require_worker_token)) -> dict:
    with STATE_LOCK:
        HEARTBEATS[hb.worker_id] = hb
        _sync_executing_signals_from_positions_locked(hb)
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
    positions_json: Optional[str] = None,
    _: None = Depends(require_worker_token),
) -> str:
    positions = _parse_positions_json(positions_json)
    with STATE_LOCK:
        HEARTBEATS[worker_id] = WorkerHeartbeat(
            worker_id=worker_id,
            mt5_connected=mt5_connected,
            account_login=account_login,
            broker=broker,
            balance=balance,
            equity=equity,
            open_positions=max(open_positions, len(positions)),
            positions=positions,
        )
        _sync_executing_signals_from_positions_locked(HEARTBEATS[worker_id])
        if mt5_connected and settings.mt5_worker.auto_close_enabled:
            _enqueue_auto_close_signals_locked(worker_id, settings.mt5_worker.auto_close_profit_pct)
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
            _enqueue_reopen_after_close_locked(signal, report)
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
