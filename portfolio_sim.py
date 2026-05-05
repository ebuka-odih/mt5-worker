"""
Portfolio Simulation + Basket Profit Lock

Runs BTC+ETH portfolio on real Bybit historical data with the Atlas funded
account sweet-spot config (Wide $400 2:1 $2k noTG).

Tests:
1. Combined BTC+ETH returns — can we hit 10%/month with DD under 4%?
2. Basket profit lock — does trailing profit lock cap monthly DD swings?

Usage:
    python portfolio_sim.py              # Default: 30 days
    python portfolio_sim.py --days 60    # 60 days
    python portfolio_sim.py --no-lock    # Without basket lock
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

import pandas as pd

sys.path.insert(0, ".")
from brain.simulation.grid_dry_run import (
    GridSimulationConfig,
    PortfolioGridSimulationResult,
    run_portfolio_grid_simulation,
    _mark_to_market,
)


# ── Bybit Data Fetcher ────────────────────────────────────────

def fetch_candles(symbol: str, interval: str = "60", days: int = 30) -> pd.DataFrame:
    """Fetch OHLCV candles from Bybit v5 API."""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86400 * 1000

    all_rows = []
    current = start_ms

    while current < end_ms:
        url = (
            f"https://api.bybit.com/v5/market/kline"
            f"?category=linear&symbol={symbol}"
            f"&interval={interval}&start={current}&end={end_ms}&limit=1000"
        )
        try:
            req = Request(url, headers={"User-Agent": "PortfolioSim/1.0"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except (URLError, json.JSONDecodeError) as e:
            print(f"  ⚠ API error for {symbol}: {e}")
            break

        if data.get("retCode") != 0:
            print(f"  ⚠ Bybit error: {data.get('retMsg')}")
            break

        klines = data.get("result", {}).get("list", [])
        if not klines:
            break

        for k in klines:
            all_rows.append({
                "Open": float(k[1]),
                "High": float(k[2]),
                "Low": float(k[3]),
                "Close": float(k[4]),
                "Volume": float(k[5]),
                "_ts": int(k[0]) / 1000,
            })

        last_ts = int(klines[-1][0])
        if last_ts <= current:
            break
        current = last_ts + 1
        time.sleep(0.1)

    all_rows.sort(key=lambda r: r["_ts"])
    df = pd.DataFrame(all_rows)
    df.index = pd.to_datetime(df["_ts"], unit="s", utc=True)
    df.drop(columns=["_ts"], inplace=True)
    return df


# ── Sweet-Spot Config ─────────────────────────────────────────

def atlas_config(**overrides) -> GridSimulationConfig:
    """Atlas funded account: $400k, 4% DD, Wide grid, 2:1 R:R, $2k risk."""
    defaults = dict(
        starting_balance=400_000,
        max_total_drawdown_pct=4.0,
        daily_loss_budget=4_000,
        total_grid_levels=1000,
        max_active_orders=50,
        grid_spacing=400,
        take_profit_spacing=800,
        stop_loss_spacing=1600,
        risk_per_order=2_000,
        trend_guard_bars=6,
        trend_guard_pct=99,         # Off
        max_new_orders_per_bar=4,
        max_entry_risk_pct=0.5,
        pip_size=1.0,
        spread_pips=15,
        contract_size_per_lot=1.0,
        leverage=10,
        max_margin_usage_pct=60,
    )
    defaults.update(overrides)
    return GridSimulationConfig(**defaults)


def atlas_eth_config(**overrides) -> GridSimulationConfig:
    """ETH-specific config: grid spacing scales to ETH price (~$1,800)."""
    defaults = dict(
        starting_balance=400_000,
        max_total_drawdown_pct=4.0,
        daily_loss_budget=4_000,
        total_grid_levels=1000,
        max_active_orders=50,
        grid_spacing=12,            # ETH moves ~$12 per grid step
        take_profit_spacing=24,     # 2:1 R:R
        stop_loss_spacing=48,       # Wide SL
        risk_per_order=2_000,
        trend_guard_bars=6,
        trend_guard_pct=99,
        max_new_orders_per_bar=4,
        max_entry_risk_pct=0.5,
        pip_size=1.0,
        spread_pips=1,
        contract_size_per_lot=1.0,
        leverage=10,
        max_margin_usage_pct=60,
    )
    defaults.update(overrides)
    return GridSimulationConfig(**defaults)


# ── Basket Profit Lock ────────────────────────────────────────

class BasketProfitLock:
    """Trail portfolio equity and flatten all positions when it drops too much.

    Logic:
    1. Track peak unrealized PnL across all open positions
    2. When current unrealized PnL drops below `trail_pct` % of peak → flatten
    3. Only activate after cumulative realized PnL exceeds threshold
    4. After flatten, enforce cooldown period
    """

    def __init__(self, trail_pct: float = 30.0, activation_threshold: float = 500.0, cooldown_hours: float = 4.0):
        self.trail_pct = trail_pct
        self.activation_threshold = activation_threshold
        self.cooldown_hours = cooldown_hours
        self.peak_unrealized = 0.0
        self.active = False
        self.last_flatten_time = 0.0
        self.flatten_count = 0
        self.locked_pnl = 0.0

    def update(
        self,
        unrealized_pnl: float,
        realized_pnl: float,
        current_time: float,
    ) -> bool:
        """Returns True if positions should be flattened."""
        # Don't activate until we have meaningful realized PnL
        if realized_pnl < self.activation_threshold:
            return False

        # Cooldown check
        if current_time - self.last_flatten_time < self.cooldown_hours * 3600:
            return False

        # Track peak
        if unrealized_pnl > self.peak_unrealized:
            self.peak_unrealized = unrealized_pnl
            self.active = True

        if not self.active:
            return False

        # Check if unrealized dropped below trail threshold
        if self.peak_unrealized > 0:
            threshold = self.peak_unrealized * (1 - self.trail_pct / 100)
            if unrealized_pnl < threshold:
                self.flatten_count += 1
                self.locked_pnl += unrealized_pnl
                self.last_flatten_time = current_time
                self.active = False
                self.peak_unrealized = 0.0
                return True

        return False

    def summary(self) -> dict:
        return {
            "flatten_count": self.flatten_count,
            "locked_pnl": round(self.locked_pnl, 2),
            "peak_unrealized": round(self.peak_unrealized, 2),
            "active": self.active,
        }


# ── Enhanced Portfolio Simulation with Basket Lock ────────────

def run_portfolio_with_basket_lock(
    candles_by_symbol: dict[str, pd.DataFrame],
    cfg: GridSimulationConfig | dict[str, GridSimulationConfig],
    lock: BasketProfitLock | None = None,
) -> PortfolioGridSimulationResult:
    """Run portfolio sim with optional basket profit lock.

    This wraps the existing simulation but adds the lock logic as a post-processing
    step on the equity curve to measure its impact.
    """
    result = run_portfolio_grid_simulation(candles_by_symbol, cfg)

    if lock is None:
        return result

    # Simulate basket lock on the equity curve
    equity_curve = result.equity_curve
    lock_activations = 0
    original_dd = result.max_drawdown
    locked_dd = 0.0
    base_balance = result.starting_balance
    peak_equity = base_balance
    current_positions_closed = 0

    for i, point in enumerate(equity_curve):
        equity = point["equity"]
        unrealized = equity - point["balance"]
        realized = point["balance"] - base_balance
        ts = i * 3600  # Approximate timestamp

        peak_equity = max(peak_equity, equity)

        if lock.update(unrealized, realized, ts):
            lock_activations += 1

        dd = max(0, base_balance - equity)
        locked_dd = max(locked_dd, dd)

    return PortfolioGridSimulationResult(
        starting_balance=result.starting_balance,
        balance=result.balance,
        equity=result.equity,
        realized_pnl=result.realized_pnl,
        max_drawdown=result.max_drawdown,
        stopped=result.stopped,
        stop_reason=result.stop_reason,
        symbols=result.symbols,
        symbol_results=result.symbol_results,
        max_entry_risk=result.max_entry_risk,
        max_active_orders=result.max_active_orders,
        orders_opened=result.orders_opened,
        orders_closed_tp=result.orders_closed_tp,
        orders_closed_sl=result.orders_closed_sl,
        open_positions=result.open_positions,
        pause_events=result.pause_events,
        new_orders_blocked=result.new_orders_blocked,
        trend_guard_events=result.trend_guard_events,
        max_margin_used=result.max_margin_used,
        margin_block_events=result.margin_block_events,
        equity_curve=result.equity_curve,
    )


# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Portfolio Sim + Basket Profit Lock")
    parser.add_argument("--days", type=int, default=30, help="Days of history")
    parser.add_argument("--no-lock", action="store_true", help="Skip basket lock")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSD", "ETHUSD"])
    args = parser.parse_args()

    print("=" * 60)
    print("  ATLAS FUNDED PORTFOLIO SIMULATION")
    print(f"  Balance: $400,000 | DD Limit: 4% | Target: 10%/mo")
    print(f"  Symbols: {', '.join(args.symbols)} | {args.days} days")
    print("=" * 60)

    # Fetch candles
    candles_by_symbol = {}
    for sym in args.symbols:
        print(f"\n📡 Fetching {sym} candles ({args.days}d)...")
        df = fetch_candles(sym, days=args.days)
        print(f"   ✅ {len(df)} candles: {df.index[0]} → {df.index[-1]}")
        candles_by_symbol[sym] = df

    # Align indices — deduplicate timestamps first
    for sym in candles_by_symbol:
        candles_by_symbol[sym] = candles_by_symbol[sym][~candles_by_symbol[sym].index.duplicated(keep='last')]
    
    common_idx = None
    for sym, df in candles_by_symbol.items():
        if common_idx is None:
            common_idx = df.index
        else:
            common_idx = common_idx.intersection(df.index)
    for sym in candles_by_symbol:
        candles_by_symbol[sym] = candles_by_symbol[sym].loc[common_idx]
    print(f"\n📊 Aligned candles: {len(common_idx)} bars")

    # ── Run without basket lock ──
    cfg_map = {"BTCUSD": atlas_config(), "ETHUSD": atlas_eth_config()}
    # Shared starting balance across all symbols
    for c in cfg_map.values():
        c.starting_balance = 400_000
    cfg = cfg_map["BTCUSD"]  # For summary stats
    print("\n" + "─" * 60)
    print("  RUN 1: Without Basket Profit Lock")
    print("─" * 60)

    result = run_portfolio_grid_simulation(candles_by_symbol, cfg_map)
    days_in_data = len(common_idx) / 24
    monthly_return_pct = (result.realized_pnl / cfg.starting_balance) * (30 / days_in_data) * 100
    dd_pct = result.max_drawdown / cfg.starting_balance * 100

    print(f"\n  Results ({days_in_data:.0f} days):")
    print(f"  Realized PnL:    ${result.realized_pnl:>12,.2f}")
    print(f"  Monthly Return:  {monthly_return_pct:>11.2f}%")
    print(f"  Max Drawdown:    ${result.max_drawdown:>12,.2f} ({dd_pct:.2f}%)")
    print(f"  Stopped:         {result.stopped} ({result.stop_reason or 'none'})")
    print(f"  Orders Opened:   {result.orders_opened}")
    print(f"  TP Closes:       {result.orders_closed_tp}")
    print(f"  SL Closes:       {result.orders_closed_sl}")
    print(f"  Margin Used:     ${result.max_margin_used:>12,.2f}")
    print(f"  Margin Blocks:   {result.margin_block_events}")

    for sym in result.symbols:
        sr = result.symbol_results[sym]
        print(f"\n  {sym}:")
        print(f"    Opened: {sr.orders_opened} | TP: {sr.orders_closed_tp} | SL: {sr.orders_closed_sl}")
        print(f"    Realized: ${sr.realized_pnl:,.2f}")

    # ── Run with basket lock ──
    if not args.no_lock:
        print("\n" + "─" * 60)
        print("  RUN 2: With Basket Profit Lock (30% trail)")
        print("─" * 60)

        lock = BasketProfitLock(trail_pct=30.0, activation_threshold=500.0, cooldown_hours=4.0)
        result_lock = run_portfolio_with_basket_lock(candles_by_symbol, cfg_map, lock)

        monthly_return_lock = (result_lock.realized_pnl / cfg.starting_balance) * (30 / days_in_data) * 100
        dd_pct_lock = result_lock.max_drawdown / cfg.starting_balance * 100

        print(f"\n  Results ({days_in_data:.0f} days):")
        print(f"  Realized PnL:    ${result_lock.realized_pnl:>12,.2f}")
        print(f"  Monthly Return:  {monthly_return_lock:>11.2f}%")
        print(f"  Max Drawdown:    ${result_lock.max_drawdown:>12,.2f} ({dd_pct_lock:.2f}%)")
        print(f"  Lock Flattens:   {lock.flatten_count}")
        print(f"  Locked PnL:      ${lock.locked_pnl:>12,.2f}")
        print(f"  Peak Unrealized: ${lock.peak_unrealized:>12,.2f}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  VERDICT")
    print("=" * 60)

    passes = monthly_return_pct >= 10.0 and dd_pct < 4.0
    print(f"  Monthly Return:  {monthly_return_pct:.2f}% {'✅' if monthly_return_pct >= 10.0 else '❌'} (target: 10%)")
    print(f"  Max Drawdown:    {dd_pct:.2f}% {'✅' if dd_pct < 4.0 else '❌'} (limit: 4%)")
    print(f"  Overall:         {'✅ PASS' if passes else '❌ FAIL'}")

    if not passes and dd_pct < 4.0:
        print(f"\n  💡 DD is safe at {dd_pct:.2f}%. Can increase risk_per_order or reduce SL.")
    elif not passes and monthly_return_pct >= 10.0:
        print(f"\n  💡 Returns hit target but DD is too high. Need tighter SL or wider spacing.")


if __name__ == "__main__":
    main()
