# Atlas 50k BTCUSD backtest note — 2026-05-18

Purpose: validate a **new isolated 50k login** profile that does not interfere with the old/default runtime or the Atlas 5k runtime.

## Test setup

- Market data: Bybit BTCUSD proxy candles
- Window: `30d`
- Interval: `1h`
- Account balance: `$50,000`
- Guardrails:
  - daily loss budget: `$600`
  - total drawdown cap: `5%`
  - leverage: `10x`
  - trend guard: `2%`
  - max new orders per bar: `1`
  - BTC only

## Compared candidates

### Recommended shipped profile
- Grid / TP / SL: `900 / 1800 / 900`
- Risk per order: `$125`
- Active orders: `6`
- Effective live shape: `3` levels each side
- BTC lot template: `0.12`
- Approx modeled stop risk from lot floor: about `$108` per order (`0.12 * 900 * $1/pip`)

### Comparison results
- `candidate_900_1800_r125_a6`
  - Realized PnL: `$413.00`
  - End balance: `$50,413.00`
  - End equity: `$50,380.51`
  - Max DD: `$156.03` (`0.312%`)
  - Orders opened: `12`
  - TP / SL: `5 / 6`
  - Pause events: `0`
  - Margin block events: `0`
  - Max margin used: `$3,091.53`
  - Stopped: `false`

- `wider_1200_2400_r150_a6`
  - Realized PnL: `$253.00`
  - End balance: `$50,253.00`
  - End equity: `$50,259.01`
  - Max DD: `$369.78` (`0.740%`)
  - Orders opened: `8`
  - TP / SL: `3 / 4`
  - Pause events: `0`
  - Margin block events: `0`
  - Max margin used: `$2,858.83`
  - Stopped: `false`

- `tighter_750_1500_r100_a8`
  - Realized PnL: `-$237.50`
  - End balance: `$49,762.50`
  - End equity: `$49,710.51`
  - Max DD: `$307.50` (`0.615%`)
  - Orders opened: `29`
  - TP / SL: `9 / 19`
  - Pause events: `0`
  - Margin block events: `0`
  - Max margin used: `$2,060.94`
  - Stopped: `false`

## Conclusion

Ship the isolated Atlas 50k BTC-only profile with:
- `grid_spacing: 900`
- `take_profit_spacing: 1800`
- `stop_loss_spacing: 900`
- `risk_per_order: 125`
- `levels_each_side: 3`
- `max_positions_per_symbol: 6`
- `max_same_side_positions: 3`
- `symbol_lots.BTCUSD: 0.12`

Reason:
- best realized PnL of the tested set
- lowest drawdown of the profitable candidates
- no daily-budget pauses
- no margin-block events
- conservative enough to keep the 50k runtime clearly separated from the more aggressive placeholder draft

## Deployment note

This profile is for a **new login account**.
Keep the old login/worker/runtime unchanged.
Launch it with its own:
- `config/settings.atlas-50k-instant.yaml`
- `docker-compose.atlas-50k-instant.yml`
- worker example `mt5-worker/.env.atlas-50k.example`
- API port `8783`
- magic `552650`
- worker ID `windows-mt5-atlas-50k-01`
