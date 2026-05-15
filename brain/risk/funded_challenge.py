from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from shared.settings import RiskSettings


def entry_risk_budget(balance: float, risk: RiskSettings) -> float:
    """Return the maximum dollars allowed at risk for a single entry.

    Funded challenge mode treats `max_risk_per_trade_pct` as a hard per-entry
    cap. A 2% entry rule on $10,000 is $200, but the portfolio guardrails below
    must still prevent too many entries from stacking into a 20% account loss.
    """

    if balance <= 0:
        return 0.0
    pct = max(0.0, risk.max_risk_per_trade_pct)
    return round(balance * (pct / 100.0), 2)


def max_drawdown_budget(balance: float, risk: RiskSettings) -> float:
    """Return the total funded-challenge loss budget in account currency."""

    if balance <= 0:
        return 0.0
    pct = max(0.0, risk.max_total_drawdown_pct)
    return round(balance * (pct / 100.0), 2)


def daily_loss_budget(balance: float, risk: RiskSettings, days: int) -> float:
    """Return an even daily burn budget for preserving the account over N days."""

    if days <= 0:
        return 0.0
    return round(max_drawdown_budget(balance, risk) / days, 2)


def per_grid_level_risk_budget(balance: float, risk: RiskSettings, total_levels: int) -> float:
    """Return max risk per grid level if every level could be filled and stopped.

    This is intentionally much smaller than the 2% per-entry ceiling for a dense
    1000-level grid. The bot should use the lower of this budget, broker minimum
    lot constraints, and active-window risk caps before placing orders.
    """

    if total_levels <= 0:
        return 0.0
    return round(max_drawdown_budget(balance, risk) / total_levels, 2)


@dataclass(frozen=True)
class PositionExposure:
    symbol: str
    side: str
    lots: float
    entry_price: float | None = None
    current_price: float | None = None


@dataclass(frozen=True)
class AccountRiskSnapshot:
    balance: float
    equity: float
    positions: Sequence[PositionExposure]


@dataclass(frozen=True)
class EntryGuardDecision:
    allowed: bool
    reason: str = ""


def estimate_margin_usage_pct(
    snapshot: AccountRiskSnapshot,
    risk: RiskSettings,
    pending_position: PositionExposure | None = None,
) -> float:
    if snapshot.equity <= 0:
        return 0.0

    leverage = max(risk.leverage, 1e-9)
    margin_used = 0.0
    for position in snapshot.positions:
        if position.lots <= 0:
            continue
        reference_price = position.entry_price or position.current_price or 0.0
        if reference_price <= 0:
            continue
        margin_used += abs(reference_price * position.lots) / leverage
    if pending_position is not None and pending_position.lots > 0:
        reference_price = pending_position.entry_price or pending_position.current_price or 0.0
        if reference_price > 0:
            margin_used += abs(reference_price * pending_position.lots) / leverage
    return round((margin_used / snapshot.equity) * 100.0, 4)


def evaluate_entry_guard(
    symbol: str,
    side: str,
    snapshot: AccountRiskSnapshot,
    risk: RiskSettings,
    pending_position: PositionExposure | None = None,
) -> EntryGuardDecision:
    symbol_key = symbol.upper().replace("/", "")
    side_key = side.lower()
    total_positions = len(snapshot.positions)
    symbol_positions = sum(1 for position in snapshot.positions if position.symbol == symbol_key)
    same_side_positions = sum(1 for position in snapshot.positions if position.side.lower() == side_key)
    opposite_side_positions = sum(1 for position in snapshot.positions if position.side.lower() != side_key)

    current_equity = min(snapshot.balance, snapshot.equity)
    if risk.funded_challenge_mode and current_equity <= 0:
        return EntryGuardDecision(False, "entry blocked: no positive account equity available")

    if risk.max_open_positions > 0 and total_positions >= risk.max_open_positions:
        return EntryGuardDecision(False, f"entry blocked: max open positions reached ({total_positions}/{risk.max_open_positions})")

    if risk.max_positions_per_symbol > 0 and symbol_positions >= risk.max_positions_per_symbol:
        return EntryGuardDecision(
            False,
            f"entry blocked: max positions reached for {symbol_key} ({symbol_positions}/{risk.max_positions_per_symbol})",
        )

    if risk.max_same_side_positions > 0 and same_side_positions >= risk.max_same_side_positions:
        return EntryGuardDecision(
            False,
            f"entry blocked: max {side_key} inventory reached ({same_side_positions}/{risk.max_same_side_positions})",
        )

    next_skew = abs((same_side_positions + 1) - opposite_side_positions)
    if risk.max_directional_skew > 0 and next_skew > risk.max_directional_skew:
        return EntryGuardDecision(
            False,
            f"entry blocked: directional skew would reach {next_skew} (limit {risk.max_directional_skew})",
        )

    total_drawdown_limit = risk.starting_balance * (1 - max(risk.max_total_drawdown_pct, 0.0) / 100.0)
    if risk.max_total_drawdown_pct > 0 and current_equity <= total_drawdown_limit:
        return EntryGuardDecision(False, "entry blocked: total drawdown circuit breaker active")

    daily_loss_limit = min(
        max(risk.daily_loss_budget, 0.0),
        max(risk.starting_balance * (max(risk.max_daily_loss_pct, 0.0) / 100.0), 0.0),
    )
    if daily_loss_limit > 0:
        floating_or_realized_loss = max(risk.starting_balance - current_equity, 0.0)
        if floating_or_realized_loss >= daily_loss_limit:
            return EntryGuardDecision(
                False,
                f"entry blocked: daily drawdown circuit breaker active ({floating_or_realized_loss:.2f}/{daily_loss_limit:.2f})",
            )

    margin_usage_pct = estimate_margin_usage_pct(snapshot, risk, pending_position=pending_position)
    if risk.max_margin_usage_pct > 0 and margin_usage_pct >= risk.max_margin_usage_pct:
        return EntryGuardDecision(
            False,
            f"entry blocked: margin usage too high ({margin_usage_pct:.2f}%/{risk.max_margin_usage_pct:.2f}%)",
        )

    return EntryGuardDecision(True)
