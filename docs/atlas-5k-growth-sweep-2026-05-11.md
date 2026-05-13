# Atlas 5K growth sweep — 2026-05-11

## Goal
Push the isolated Atlas 5K BTCUSD profile from the earlier ~3.65% monthly tune into the user's requested 5-10% monthly return band while keeping internal safety limits tighter than the official account rules:
- worst intraday equity loss: under 2%
- max total drawdown: under 4%
- no simulator stop event

## Data and method
- Market: Bybit `BTCUSD`
- Timeframe: 1h candles
- Sample: 1000 hourly bars (~41.7 days)
- Account modeled: `$5,000`
- Leverage modeled: `10x`
- Common structure:
  - `TP = 2 x SL`
  - `trend_guard_bars = 6`
  - `max_entry_risk_pct = 0.6`
  - `spread_pips = 15`
  - `max_margin_usage_pct = 35`

## Best-fit candidate with safety margin
This was the strongest balance of growth vs cushion:
- `grid_spacing: 750`
- `take_profit_spacing: 1500`
- `stop_loss_spacing: 750`
- `risk_per_order: 30`
- `max_new_orders_per_bar: 2`
- `trend_guard_pct: 1.5`
- `daily_loss_budget: 90`
- `max_daily_loss_pct: 2.0`
- `max_total_drawdown_pct: 4.0`
- `max_margin_usage_pct: 35.0`
- live `BTCUSD` lots reduced for conservative 5k sizing: `0.01`

### Observed metrics
- monthly return: `9.07%`
- realized PnL over sample: `$630.00`
- max total drawdown: `2.85%`
- worst day loss: `1.34%`
- worst calendar-month drawdown from month start: `1.95%`
- peak margin used: `23.81%`
- orders opened: `50`
- pause events: `0`
- simulator stop events: `0`

## Higher-return variant
If the user wants to push right up near the top of the 5-10% band, this was the best raw-return setup that still passed the tighter filters:
- `grid_spacing: 800`
- `take_profit_spacing: 1600`
- `stop_loss_spacing: 800`
- `risk_per_order: 30`
- `max_new_orders_per_bar: 3`
- `trend_guard_pct: 2.0`

Metrics:
- monthly return: `10.00%`
- max total drawdown: `3.76%`
- worst day loss: `1.60%`
- monthly drawdown: `3.17%`
- margin used: `23.87%`

This one is valid, but it leaves less headroom below the 4% drawdown ceiling than the recommended `750 / 30 / 1.5 / 2` profile.

## Balanced alternatives
### Variant A — 800 / 25 / 2.0 / 3
- monthly return: `8.34%`
- max DD: `3.13%`
- worst day: `1.34%`
- monthly DD: `2.64%`
- margin used: `19.89%`

### Variant B — 750 / 25 / 1.5 / 3
- monthly return: `8.27%`
- max DD: `3.57%`
- worst day: `1.12%`
- monthly DD: `1.63%`
- margin used: `19.84%`

## Why the winner was chosen
The recommended `750 / 30 / 1.5 / 2` profile beat the other balanced variants on the key trade-off:
- materially higher return than the 25-risk variants
- lower max drawdown than the 800/30 aggressive profile
- lower monthly drawdown than the 800/30 aggressive profile
- zero pause events in the sampled run
- still well below the user's 10x leverage cap and below the 2%/4% internal drawdown guardrails

## Live config mapping
For the isolated Atlas 5K runtime, the config was updated to:
- tighten risk caps to `2% daily` / `4% total`
- set `risk_per_order: 30`
- set `grid_spacing / TP / SL = 750 / 1500 / 750`
- set `trend_guard_pct: 1.5`
- set `max_new_orders_per_bar: 2`
- set `BTCUSD` lot size to `0.01`

The user prefers recovery-first loss handling, so negative auto-close remains effectively disabled:
- `auto_close_loss_pct: 99.0`
- `auto_close_profit_pct: 0.6`

## Caveat
This is still a single-market, single-sample backtest over ~41.7 days of BTCUSD hourly data. Treat it as a better starting envelope for the second funded account, not proof of production robustness. Before increasing beyond this, run the same candidate on additional date windows and ideally replay MT5-realistic execution costs/slippage.
