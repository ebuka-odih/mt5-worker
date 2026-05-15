# Atlas 5k second instance setup

This profile runs **alongside** the existing MT5 brain without touching the old instance.

## Files
- VPS config: `config/settings.atlas-5k.yaml`
- VPS compose stack: `docker-compose.atlas-5k.yml`
- Private worker env: `mt5-worker/.env.atlas-5k`
- Safe template to send elsewhere: `mt5-worker/.env.atlas-5k.example`

## Isolation values
- API port: `8782`
- Container name: `forex-brain-atlas-5k`
- Data dir: `./data-atlas-5k`
- MT5 magic number: `552701`
- MT5 comment prefix: `vps_forex_brain_atlas_5k`
- Worker token: keep the repo config on placeholder `CHANGE_ME_ATLAS_5K_WORKER_TOKEN`; put the real secret only in the deployed VPS config and the Windows worker `.env`

## Atlas Instant rule alignment used here
- Starting balance: `$5,000`
- Internal daily loss budget: `$75`
- Internal max daily loss cap: `2%`
- Atlas max daily loss rule: `3%`
- Atlas max trailing drawdown rule: `5%`
- Single-worker symbol set: `BTCUSD` only
- Leverage cap: `10x`

## Behavior choices
- **Positive PnL auto-close remains enabled** via `auto_close_profit_pct: 0.6`
- **Negative DD auto-close is disabled** via `auto_close_loss_pct: 0.0` so losers are not force-closed before recovery.
- Basket take profit is tightened to `$12`.

## Current de-risked 5k live profile
- `risk_per_order: 7.5`
- `grid_spacing / TP / SL = 600 / 1200 / 600`
- `trend_guard_pct: 2.0`
- `max_new_orders_per_bar: 1`
- `levels_each_side: 5`
- `BTCUSD lots: 0.01` *(0.005 was rejected live by MT5 as invalid volume; 0.01 is the accepted floor)*

This is the safer profile for the **new** 5k login. The old login continues on its separate runtime unchanged.

## VPS launch
```bash
docker compose -p atlas-5k -f docker-compose.atlas-5k.yml up -d --build
curl http://127.0.0.1:8782/health
```

## New computer / Windows worker setup
This is for the **new Atlas 5k login account**, not the old funded login. Leave the old worker/service running on its existing profile.

1. Pull the latest repo on the Windows machine:

```cmd
cd C:\forex-mt5-bot
git pull
cd mt5-worker
```

2. Copy the safe template to `.env` and edit it:

```cmd
copy .env.atlas-5k.example .env
notepad .env
```

3. Set these values in `.env`:
   - `VPS_API_BASE=https://<active-atlas-5k-tunnel-or-host>:8782` *(use the current live Atlas 5k endpoint; do not hardcode an expired quick-tunnel URL into git)*
   - `WORKER_TOKEN` = the same real token you placed in the deployed VPS copy of `config/settings.atlas-5k.yaml`
   - `WORKER_ID=windows-mt5-atlas-5k-01`
   - `MT5_MAGIC=552701`
   - `DRY_RUN=false` only when you want live execution on the new 5k account

   Example:
   ```env
   VPS_API_BASE=https://<active-atlas-5k-tunnel-or-host>
   WORKER_TOKEN=<same-token-as-config/settings.atlas-5k.yaml>
   WORKER_ID=windows-mt5-atlas-5k-01
   DRY_RUN=false
   MT5_MAGIC=552701
   POLL_SECONDS=1
   HEARTBEAT_SECONDS=10
   REQUEST_TIMEOUT_MS=5000
   ```

4. Ensure the MT5 terminal is logged into the **new Atlas 5k funded account**.
5. Start the worker:

```cmd
cd C:\forex-mt5-bot\mt5-worker
venv\Scripts\python windows_mt5_worker.py
```

## Verification
- VPS health: `curl http://127.0.0.1:8782/health`
- Worker log should show `Worker ID: windows-mt5-atlas-5k-01`
- Worker log should show `MT5 connected`
- Orders for this account should carry magic `552701`
- Existing instance continues using port `8780` / magic `552501`

## Monitoring endpoints to keep for live tuning

Use the Atlas 5k base URL plus the same worker token from the VPS config.

- `GET /health` — quick liveness and connected worker count
- `GET /api/signals` — raw signal queue/history
- `GET /api/orders?worker_token=<TOKEN>&worker_id=windows-mt5-atlas-5k-01` — execution reports for the 5k worker
- `GET /api/workers?worker_token=<TOKEN>` — latest worker heartbeats
- `GET /api/workers/windows-mt5-atlas-5k-01/positions?worker_token=<TOKEN>` — live positions seen from MT5
- `GET /api/workers/windows-mt5-atlas-5k-01/diagnostics?worker_token=<TOKEN>` — per-position PnL/age diagnostics
- `GET /api/diagnostics/summary?worker_token=<TOKEN>` — aggregate rejection, close-reason, cooldown, and basket stats to spot where the live bot diverges from config

These endpoints are the fastest way to verify whether the bot is actually behaving like the 5k profile and to see what needs improving next.

## Deployment note
- Do **not** stop or reconfigure the original Atlas worker that is already tied to the old login.
- The new 5k login should use only the `atlas-5k` profile files, port `8782`, magic `552701`, and worker ID `windows-mt5-atlas-5k-01`.
- If the Windows box runs the worker as NSSM or Task Scheduler, restart only the new Atlas 5k worker after updating `.env`.
- Use the dedicated compose project name `atlas-5k` so compose does not try to replace the original `forex-brain` stack.

## Latest pushed runtime note for local AI

Committed in `cc4d27d` (`feat: add atlas 5k recycle runtime metrics`).

What changed in code:
- `brain/api/server.py` now increments `grid_recycle_counts["auto-reopen-after-close"]` when a filled close successfully spawns its immediate replacement open signal.
- `/api/diagnostics/summary?worker_token=<TOKEN>` now returns `grid_recycle_counts` alongside `entry_block_counts`, `grid_rejection_counts`, and `close_reason_counts`.
- Regression coverage lives in:
  - `tests/test_worker_state_api.py`
  - `tests/test_signal_cycle_loop.py`

How the local AI should use this:
- Treat `grid_recycle_counts` as the runtime proof that close-triggered grid slot replacement is actually happening on the isolated 5k brain.
- When tuning the 5k profile for higher trade cadence, compare:
  - `GET /api/signals`
  - `GET /api/orders?worker_token=<TOKEN>&worker_id=windows-mt5-atlas-5k-01`
  - `GET /api/diagnostics/summary?worker_token=<TOKEN>`
- If positive closes occur but `grid_recycle_counts.auto-reopen-after-close` does not rise, inspect the close->reopen path in `brain/api/server.py` before changing strategy parameters.
- Keep this behavior isolated to the new 5k runtime; do not move the new login onto the old profile or overwrite the old worker `.env`.

Validation used for this pushed change:
```bash
venv/bin/python -m pytest tests/test_atlas_5k_instance.py tests/test_grid_strike.py tests/test_btc_funded_challenge.py tests/test_worker_state_api.py tests/test_signal_cycle_loop.py -q
```
Expected monitoring reality after deployment:
- `http://127.0.0.1:8782/health` should be healthy for the Atlas 5k runtime.
- The old runtime must be checked separately on its own port/profile; do not assume it is still running just because the files are separate.
