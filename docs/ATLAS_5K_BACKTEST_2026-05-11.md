# Atlas 5K Backtest Sweep — 2026-05-11

## Goal
Find a BTCUSD-only config for the new Atlas 5k funded instance that stays below the daily 2% loss rule while remaining net positive.

## Method
- Data source: Bybit v5 BTCUSD hourly candles
- Lookback: 1000 hourly bars (~41.7 days)
- Account size: $5,000
- Safety limits used for selection:
  - Max total drawdown <= 5%
  - Worst intraday equity loss < 2%
  - Positive realized PnL
  - No simulator stop event

## Matrix 1 — Base sweep
Tested combinations:
- Grid spacing: 300, 350, 400, 500, 600
- TP: 2x grid
- SL: 1x grid
- Risk per order: $5, $7.5, $10
- Daily loss budget: $50, $75, $90, $100
- Trend guard: 2%
- Max new orders per bar: 1

Best base result:
- Grid: 600
- TP / SL: 1200 / 600
- Risk per order: $10
- Monthly return: 3.11%
- Max drawdown: 1.42%
- Worst day loss: 0.61%
- Margin used: 7.9%

## Matrix 2 — Focused sweep around the winner
Tested combinations:
- Grid spacing: 550, 600, 650, 700, 750, 800
- Risk per order: $10 only
- Max new orders per bar: 1, 2, 3
- Trend guard: 1.5%, 2.0%, 2.5%
- Daily loss budget: $90

Best focused result:
- Grid: 600
- TP / SL: 1200 / 600
- Risk per order: $10
- Max new orders per bar: 3
- Trend guard: 2.0%
- Monthly return: 3.65%
- Realized PnL over sample: $253.25
- Max drawdown: 1.83%
- Worst day loss: 0.61%
- Margin used: 7.9%
- Orders opened: 107

## Suggested live drawdown auto-close
The simulator does not directly model `auto_close_loss_pct`, so this was mapped from the winning SL distance.

For grid=600 and SL=600:
- 80% of SL ~= 480 adverse BTC move
- Sample average BTC price ~= 75,057
- Approx adverse move percent ~= 0.64%

Suggested live `auto_close_loss_pct` range:
- Conservative: 0.55%
- Balanced: 0.60% to 0.65%
- Aggressive: 0.70%

Interpretation:
- At 0.60% to 0.65%, the worker should usually cut losers before the full 600-point SL, which helps keep each grid loss in the rough $8-$10 range once spread/slippage are included.

## Recommendation at the time (2026-05-11)
Primary candidate from that earlier sweep:
- grid_spacing: 600
- take_profit_spacing: 1200
- stop_loss_spacing: 600
- risk_per_order: 10
- max_new_orders_per_bar: 3
- trend_guard_pct: 2.0
- daily_loss_budget: 90
- max_daily_loss_pct: 2.0
- max_total_drawdown_pct: 5.0
- auto_close_loss_pct: 0.60 to 0.65

Safer fallback from that earlier sweep:
- Same config, but risk_per_order: 7.5
- Use if the user wants lower per-grid realized loss and slower growth.

## Follow-up rerun for the deployed isolated 5k profile (2026-05-18)

To align with the user's recovery-first preference and the actual isolated Windows worker setup, the live 5k profile was later pinned to:

- grid_spacing: 600
- take_profit_spacing: 1200
- stop_loss_spacing: 600
- risk_per_order: 7.5
- max_new_orders_per_bar: 1
- trend_guard_pct: 2.0
- daily_loss_budget: 75
- max_daily_loss_pct: 2.0
- max_total_drawdown_pct: 4.0
- auto_close_loss_pct: 0.0
- fixed BTC lot: 0.01

Focused rerun on ~1000 BTCUSD hourly bars (~41.7 days):
- Realized PnL: $94.95
- Normalized monthly return: 1.37%
- Max drawdown: 0.49%
- Worst intraday equity loss: 0.37%
- Orders opened: 87
- Max margin used: 4.74%
- Stop event: none

Important caveat:
- Because BTC is forced to 0.01 lots in the current MT5 profile, the simulator shows `risk_per_order: 7.5` and `risk_per_order: 10.0` landing on the same effective order size at this stop distance.
- A `max_new_orders_per_bar: 3` variant improved normalized return to ~1.78%/month, but the slower `1` order/bar profile remains the recommended deployment because this is a new login account being brought up in isolation while the old login keeps running.
