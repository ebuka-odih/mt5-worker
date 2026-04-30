from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from brain.data.bybit_data import BybitMarketDataProvider, BybitWebhookCache
from brain.data.forex_data import YFinanceForexProvider
from brain.signals.grid_strike import GridPlan, GridStrikeCandidate, build_grid_plan, scan_grid_candidates
from brain.signals.simple_strategy import simple_signal
from shared.models import ExecutionReport, ForexQuote, Signal, SignalSide, SignalStatus, WorkerHeartbeat
from shared.settings import load_settings

settings = load_settings()
app = FastAPI(title="Forex MT5 Bot Brain", version="0.1.0")


def create_market_data_provider():
    if settings.market_data.provider.lower() == "bybit":
        return BybitMarketDataProvider()
    return YFinanceForexProvider()


provider = create_market_data_provider()
bybit_webhook_cache = BybitWebhookCache()

SIGNALS: Dict[str, Signal] = {}
EXECUTIONS: List[ExecutionReport] = []
HEARTBEATS: Dict[str, WorkerHeartbeat] = {}


class CreateSignalRequest(BaseModel):
    symbol: str
    side: str = "buy"
    lots: float = 0.01
    stop_loss: float | None = None
    take_profit: float | None = None


class BybitWebhookPayload(BaseModel):
    symbol: str = "BTCUSD"
    price: float
    bid: float | None = None
    ask: float | None = None
    timestamp: datetime | None = None


def require_worker_token(x_worker_token: str = Header(default="")) -> None:
    if settings.api.worker_token == "CHANGE_ME_LONG_RANDOM_TOKEN":
        # Allow local testing until token is changed.
        return
    if x_worker_token != settings.api.worker_token:
        raise HTTPException(status_code=401, detail="invalid worker token")


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "mode": settings.app.mode,
        "signals": len(SIGNALS),
        "workers": len(HEARTBEATS),
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
    created: list[Signal] = []
    for symbol in settings.market_data.symbols:
        try:
            candles = provider.fetch_candles(
                symbol,
                period=settings.market_data.candles_period,
                interval=settings.market_data.candles_interval,
            )
            signal = simple_signal(symbol, candles, settings)
            if signal:
                SIGNALS[signal.id] = signal
                created.append(signal)
        except Exception as exc:
            print(f"WARN scan failed for {symbol}: {exc}")
    return created


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


@app.post("/api/grid-strike/plan", response_model=GridPlan | None)
def grid_strike_plan() -> GridPlan | None:
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
        symbol=req.symbol,
        side=SignalSide(req.side.lower()),
        lots=req.lots,
        stop_loss=req.stop_loss,
        take_profit=req.take_profit,
        confidence=0.95,
        reason="manual-create",
    )
    SIGNALS[signal.id] = signal
    return signal


@app.get("/api/signals", response_model=list[Signal])
def list_signals() -> list[Signal]:
    return list(SIGNALS.values())


@app.get("/api/worker/next-signal", response_model=Signal | None)
def next_signal(worker_id: str, _: None = Depends(require_worker_token)) -> Signal | None:
    for signal in SIGNALS.values():
        if signal.status == SignalStatus.CREATED:
            signal.status = SignalStatus.CLAIMED
            signal.worker_id = worker_id
            signal.claimed_at = datetime.now(timezone.utc)
            return signal
    return None


@app.post("/api/worker/execution-report")
def execution_report(report: ExecutionReport, _: None = Depends(require_worker_token)) -> dict:
    EXECUTIONS.append(report)
    signal = SIGNALS.get(report.signal_id)
    if signal:
        signal.status = report.status
    return {"ok": True, "reports": len(EXECUTIONS)}


@app.post("/api/worker/heartbeat")
def heartbeat(hb: WorkerHeartbeat, _: None = Depends(require_worker_token)) -> dict:
    HEARTBEATS[hb.worker_id] = hb
    return {"ok": True, "server_time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/worker/test-signal")
def create_test_signal(
    symbol: str,
    side: str,
    lots: float,
    worker_id: str = "test-worker",
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> Signal:
    """Create a test signal for worker verification."""
    signal = Signal(
        symbol=symbol,
        side=SignalSide(side.lower()),
        lots=lots,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=0.95,
        reason="test-signal",
    )
    SIGNALS[signal.id] = signal
    return signal
