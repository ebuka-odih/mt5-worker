# Deployment Checklist

Use this before pushing the MT5 brain changes to the VPS and before enabling live execution.

## 1. Local verification

- Confirm the working branch is the intended branch:
  - `git branch --show-current`
- Run the touched test slice:
  - `./.venv/bin/python -m pytest tests/test_month_grid_risk.py tests/test_signal_cycle_loop.py tests/test_worker_state_api.py tests/test_grid_strike_api.py tests/test_grid_strike.py -q`
- Verify there are no unreviewed local diffs beyond the intended files:
  - `git status --short`

## 2. Config review

Review [config/settings.yaml](/Users/gnosis/Herd/mt5-worker/config/settings.yaml) before push:

- `app.mode`
- `market_data.symbols`
- `grid_strike.session_start_hour_utc`
- `grid_strike.session_end_hour_utc`
- `grid_strike.max_spread_pips`
- `grid_strike.atr_spacing_multiplier`
- `mt5_worker.auto_close_profit_pct`
- `mt5_worker.auto_close_loss_pct`
- `mt5_worker.basket_take_profit_usd`
- `mt5_worker.stale_position_minutes`
- `mt5_worker.volatility_spike_close_pct`
- `mt5_worker.reentry_cooldown_seconds`

Do not push with placeholder values you do not intend to trade.

## 3. Git push

- Push the current branch:
  - `git push origin $(git branch --show-current)`

## 4. VPS update

On the VPS repo at `/home/forge1/.hermes/projects/forex-mt5-bot`:

```bash
cd /home/forge1/.hermes/projects/forex-mt5-bot
git status --short
git branch --show-current
git pull --ff-only origin <branch>
```

If the VPS has local changes, stop and reconcile them before pulling.

## 5. Brain restart

- Activate the environment and restart the API process or container.
- Verify the brain responds:

```bash
curl http://127.0.0.1:8780/health
curl -X POST http://127.0.0.1:8780/api/grid-strike/scan
curl "http://127.0.0.1:8780/api/diagnostics/summary?worker_token=<TOKEN>"
```

## 6. Worker and tunnel verification

- Confirm the Cloudflare URL or VPS URL is current.
- Confirm the Windows worker `.env` token matches the VPS token.
- Confirm `DRY_RUN=true` for the first post-deploy verification run.
- Confirm MT5 is connected to the correct funded account.

## 7. Dry-run smoke test

Check these after the worker has been running for several minutes:

- `/api/workers`
- `/api/workers/<worker_id>/positions`
- `/api/workers/<worker_id>/diagnostics`
- `/api/orders`
- `/api/diagnostics/summary`

Expected signals:

- worker heartbeat timestamp updates
- `basket_net_pnl` is visible
- `cooldowns` populate after close fills
- `grid_rejection_counts` increments when setups are filtered out
- `close_reason_counts` increments when close signals are created

## 8. Pre-live gate

Do not switch to live execution until all are true:

- worker heartbeat is stable
- no duplicate close signals for the same ticket
- cooldown blocks immediate reopen churn
- session/spread filters behave as expected
- diagnostics counters reflect expected reasons, not random noise
- manual close and report flows still work

## 9. Live switch

Only after the dry-run pass is clean:

- set Windows worker `DRY_RUN=false`
- restart the worker
- monitor `/api/diagnostics/summary` and `/api/orders` continuously during the first live session
