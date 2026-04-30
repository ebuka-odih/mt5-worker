from __future__ import annotations

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
