"""Trade data logger for offline analysis.

Logs every trade + market context to JSONL files. No LLM dependency —
pure data collection. Later, agents can analyze these files to find
patterns, optimize parameters, and improve the grid strategy.

Usage:
    from brain.data.trade_logger import TradeLogger
    logger = TradeLogger("BTCUSD")
    logger.log_fill(fill_event)
    logger.log_close(close_event)
    logger.flush()
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path.home() / ".hermes" / "projects" / "forex-mt5-bot" / "data" / "trades"


class TradeLogger:
    """Append-only JSONL trade logger."""

    def __init__(self, symbol: str, log_dir: Path | str | None = None):
        self.symbol = symbol
        self.log_dir = Path(log_dir) if log_dir else LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._fills_path = self.log_dir / f"{symbol}_fills.jsonl"
        self._closes_path = self.log_dir / f"{symbol}_closes.jsonl"
        self._equity_path = self.log_dir / f"{symbol}_equity.jsonl"
        self._buffer: list[dict] = []

    def log_fill(self, side: str, entry: float, tp: float, sl: float,
                 lot_size: float, risk: float, timestamp: str | None = None,
                 **extra):
        """Log a grid order fill."""
        event = {
            "type": "fill",
            "symbol": self.symbol,
            "side": side,
            "entry": round(entry, 2),
            "tp": round(tp, 2),
            "sl": round(sl, 2),
            "lot_size": round(lot_size, 6),
            "risk": round(risk, 2),
            "tp_dist": round(abs(tp - entry), 2),
            "sl_dist": round(abs(sl - entry), 2),
            "rr_ratio": round(abs(tp - entry) / max(abs(sl - entry), 1e-9), 2),
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            **extra,
        }
        self._append(self._fills_path, event)

    def log_close(self, side: str, entry: float, exit_price: float,
                  pnl: float, close_reason: str, hold_bars: int = 0,
                  timestamp: str | None = None, **extra):
        """Log a position close (TP, SL, or manual)."""
        event = {
            "type": "close",
            "symbol": self.symbol,
            "side": side,
            "entry": round(entry, 2),
            "exit": round(exit_price, 2),
            "pnl": round(pnl, 2),
            "close_reason": close_reason,
            "hold_bars": hold_bars,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            **extra,
        }
        self._append(self._closes_path, event)

    def log_equity(self, balance: float, equity: float, open_positions: int,
                   price: float, timestamp: str | None = None, **extra):
        """Log equity snapshot per bar."""
        event = {
            "type": "equity",
            "symbol": self.symbol,
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "open_positions": open_positions,
            "price": round(price, 2),
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            **extra,
        }
        self._append(self._equity_path, event)

    def _append(self, path: Path, event: dict):
        self._buffer.append((path, event))
        if len(self._buffer) >= 50:
            self.flush()

    def flush(self):
        """Write buffered events to disk."""
        by_file: dict[Path, list[dict]] = {}
        for path, event in self._buffer:
            by_file.setdefault(path, []).append(event)
        for path, events in by_file.items():
            with open(path, "a") as f:
                for event in events:
                    f.write(json.dumps(event, default=str) + "\n")
        self._buffer.clear()


def load_fills(symbol: str, log_dir: Path | str | None = None) -> list[dict]:
    """Load all fill events for a symbol."""
    path = (Path(log_dir) if log_dir else LOG_DIR) / f"{symbol}_fills.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_closes(symbol: str, log_dir: Path | str | None = None) -> list[dict]:
    """Load all close events for a symbol."""
    path = (Path(log_dir) if log_dir else LOG_DIR) / f"{symbol}_closes.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_equity(symbol: str, log_dir: Path | str | None = None) -> list[dict]:
    """Load all equity snapshots for a symbol."""
    path = (Path(log_dir) if log_dir else LOG_DIR) / f"{symbol}_equity.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarize(symbol: str, log_dir: Path | str | None = None) -> dict:
    """Quick summary of logged trade data."""
    closes = load_closes(symbol, log_dir)
    if not closes:
        return {"symbol": symbol, "trades": 0}

    wins = [c for c in closes if c["pnl"] > 0]
    losses = [c for c in closes if c["pnl"] <= 0]
    total_pnl = sum(c["pnl"] for c in closes)
    tp_closes = [c for c in closes if c["close_reason"] == "tp"]
    sl_closes = [c for c in closes if c["close_reason"] == "sl"]

    return {
        "symbol": symbol,
        "trades": len(closes),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closes) * 100, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_win": round(sum(c["pnl"] for c in wins) / max(len(wins), 1), 2),
        "avg_loss": round(sum(c["pnl"] for c in losses) / max(len(losses), 1), 2),
        "tp_exits": len(tp_closes),
        "sl_exits": len(sl_closes),
        "avg_hold_bars": round(sum(c.get("hold_bars", 0) for c in closes) / len(closes), 1),
    }
