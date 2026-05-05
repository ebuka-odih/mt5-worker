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


class SignalAction(str, Enum):
    OPEN = "open"
    CLOSE = "close"


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
    action: SignalAction = SignalAction.OPEN
    lots: float
    position_ticket: Optional[int] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 0.0
    reason: str = ""
    status: SignalStatus = SignalStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    claimed_at: Optional[datetime] = None
    worker_id: Optional[str] = None
    target_worker_id: Optional[str] = None


class ExecutionReport(BaseModel):
    signal_id: str
    worker_id: str
    status: SignalStatus
    broker_order_id: Optional[str] = None
    executed_price: Optional[float] = None
    lots: Optional[float] = None
    message: str = ""
    reported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkerPosition(BaseModel):
    ticket: Optional[int] = None
    symbol: str
    side: SignalSide
    lots: float
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    profit: Optional[float] = None
    swap: Optional[float] = None
    commission: Optional[float] = None
    opened_at: Optional[datetime] = None
    magic: Optional[int] = None
    comment: str = ""


class WorkerHeartbeat(BaseModel):
    worker_id: str
    mt5_connected: bool
    account_login: Optional[int] = None
    broker: Optional[str] = None
    balance: Optional[float] = None
    equity: Optional[float] = None
    open_positions: int = 0
    positions: list[WorkerPosition] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
