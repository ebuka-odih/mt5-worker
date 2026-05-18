# Atlas 50k second-login Windows deployment note

This profile is for a **new login account**.

Keep the **old login** and its existing worker/service running unchanged.
Do not overwrite the old worker .env.
Use a separate Windows worker config for the new 50k login.

## VPS-side isolated runtime

Dedicated files:
- `config/settings.atlas-50k-instant.yaml`
- `docker-compose.atlas-50k-instant.yml`

Dedicated runtime identity:
- API port: `8783`
- MT5 magic: `552650`
- Comment prefix: `vps_forex_brain_atlas50k`
- Worker token placeholder: `CHANGE_ME_ATLAS_50K_INSTANT_WORKER_TOKEN`

This new login must run as its own isolated instance so it cannot interfere with the old account's risk state, cooldowns, or worker routing.

## Windows update path for the new login only

From the Windows repo checkout:

```powershell
cd C:\forex-mt5-bot
git pull
cd mt5-worker
copy .env.atlas-50k.example .env.atlas-50k
notepad .env.atlas-50k
```

Fill in the new-login values in `.env.atlas-50k`:
- `VPS_API_BASE=https://CHANGE_ME_ATLAS_50K_TUNNEL_OR_HOST`
- `WORKER_TOKEN=CHANGE_ME_ATLAS_50K_INSTANT_WORKER_TOKEN`
- `WORKER_ID=windows-mt5-atlas-50k-01`
- `DRY_RUN=false` only when you are ready for live placement on the new login
- `MT5_MAGIC=552650`

Then start the **new** worker from the dedicated env.
Do **not** overwrite the old worker `.env` and do not restart the old worker in place.
The goal is: keep the old worker/service running unchanged while launching a second worker for the new login account.

Example launch pattern using the same worker code with the new 50k config file:

```powershell
cd C:\forex-mt5-bot\mt5-worker
venv\Scripts\activate
python windows_mt5_worker.py --env-file .env.atlas-50k
```

Do not copy `.env.atlas-50k` over `.env` unless this Windows checkout is dedicated to the new 50k login only.

If the old worker is already running as a service or in another terminal session, leave it alone.
Start this new login worker separately.

## Operator pre-flight before restarting the new worker

Verify both runtimes independently:
- old/default runtime health endpoint stays healthy on its current port
- new 50k runtime responds on `http://127.0.0.1:8783/health`
- if the old runtime is down, recover it separately first instead of replacing it with the new login stack

## 50k BTC-only starting profile shipped in this repo

- Balance: `50000`
- Symbols: `BTCUSD` only
- Daily loss cap: `3%`
- Total drawdown cap: `5%`
- Internal daily loss budget: `$600`
- Risk per order budget: `$125`
- Grid: `900 / 1800 / 900`
- Levels each side: `3`
- BTC lots: `0.12`

This note is intentionally scoped to the **new login account** deployment.
It does not replace or modify the old account setup.
