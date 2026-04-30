from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class SignalSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class SignalStatus(str, Enum):
    CREATED = "created"
    CLAIMED = "claimed"
    EXECUTING = "executing"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ForexQuote(BaseModel):
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: float
    timestamp: datetime
    source: str


class Signal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    side: SignalSide
    order_type: str = "market"
    lots: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 0.0
    reason: str = ""
    status: SignalStatus = SignalStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    claimed_at: Optional[datetime] = None
    worker_id: Optional[str] = None


class ExecutionReport(BaseModel):
    signal_id: str
    worker_id: str
    status: SignalStatus
    broker_order_id: Optional[str] = None
    executed_price: Optional[float] = None
    lots: Optional[float] = None
    message: str = ""
    reported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkerHeartbeat(BaseModel):
    worker_id: str
    mt5_connected: bool
    account_login: Optional[int] = None
    broker: Optional[str] = None
    balance: Optional[float] = None
    equity: Optional[float] = None
    open_positions: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
