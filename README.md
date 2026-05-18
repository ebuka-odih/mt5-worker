# Forex MT5 Bot — Atlas Funded Grid-Strike System

Linux VPS strategy brain + Windows local MT5 execution worker.
Designed for **Atlas Funded** $400k challenge (4% DD, 10% monthly target).

## Architecture

```
┌─────────────────────┐         ┌──────────────────────────┐
│  VPS Brain (Linux)  │◄────────│  MT5 Worker (Windows)    │
│  Port 8780          │  polls  │  MetaTrader 5 terminal   │
│  Grid-Strike engine │────────►│  Atlas funded account    │
│  Signal generation   │  exec  │  Order execution         │
└─────────────────────┘         └──────────────────────────┘
        ▲
        │ Cloudflare Tunnel
        ▼
https://<fresh-cloudflare-tunnel>.trycloudflare.com
```

## VPS Brain Setup

```bash
cd ~/.hermes/projects/forex-mt5-bot
source venv/bin/activate
PYTHONPATH=. python -m uvicorn brain.api.server:app --host 0.0.0.0 --port 8780
```

### Quick API Tests

```bash
curl http://127.0.0.1:8780/health
curl http://127.0.0.1:8780/api/market/quotes
curl -X POST http://127.0.0.1:8780/api/grid-strike/scan
curl -X POST http://127.0.0.1:8780/api/grid-strike/scan-all
curl -X POST http://127.0.0.1:8780/api/grid-strike/plan
curl "http://127.0.0.1:8780/api/diagnostics/summary?worker_token=<TOKEN>"
```

### Worker Position State Endpoints

Use the worker token from `config/settings.yaml` as `worker_token` query param.

```bash
curl "http://127.0.0.1:8780/api/workers?worker_token=<TOKEN>"
curl "http://127.0.0.1:8780/api/workers/windows-mt5-atlas-01?worker_token=<TOKEN>"
curl "http://127.0.0.1:8780/api/workers/windows-mt5-atlas-01/positions?worker_token=<TOKEN>"
curl "http://127.0.0.1:8780/api/workers/windows-mt5-atlas-01/diagnostics?worker_token=<TOKEN>"
curl "http://127.0.0.1:8780/api/orders?worker_token=<TOKEN>&worker_id=windows-mt5-atlas-01&limit=20"
curl -X POST "http://127.0.0.1:8780/api/workers/windows-mt5-atlas-01/auto-close?worker_token=<TOKEN>&profit_pct=3.0"
```

`/api/workers/{worker_id}/auto-close` creates close signals for positions whose
floating gain is at or above `profit_pct`; after a close fill, the brain
automatically queues a new open signal in the same direction when
`mt5_worker.auto_reopen_after_close: true`.

`/api/diagnostics/summary` exposes:
- entry block counts by reason
- grid rejection counts by reason
- close reason counts
- cooldown state per symbol
- basket net PnL per worker

`/api/workers/{worker_id}/diagnostics` exposes per-position net PnL, profit
percent, and age in minutes for that worker.

## Windows MT5 Worker Setup

### Atlas 5k second login / second instance

If you are bringing up the **new Atlas 5k login** while keeping the old Atlas login live, use the isolated second-instance profile:

- VPS config: `config/settings.atlas-5k.yaml`
- VPS compose: `docker-compose.atlas-5k.yml`
- Windows template: `mt5-worker/.env.atlas-5k.example`
- API port: `8782`
- MT5 magic: `552701`
- Worker ID: `windows-mt5-atlas-5k-01`

Do **not** replace the old worker `.env` or stop the original port `8780` service. Full deployment steps are in `docs/ATLAS_5K_SECOND_INSTANCE_SETUP.md`.

Pre-flight check before restarting the Windows worker for the new 5k login:
- old login runtime should answer on `http://127.0.0.1:8780/health`
- new 5k runtime should answer on `http://127.0.0.1:8782/health`
- if `8780` is down, recover the old/default stack separately before touching the new 5k worker

On the VPS, launch the second instance with its own compose project name so the old stack stays untouched:

```bash
docker compose -p atlas-5k -f docker-compose.atlas-5k.yml up -d --build
```

### Prerequisites

- Windows 10/11 with Python 3.9+
- MetaTrader 5 installed and logged into your Atlas funded account
- MT5 must be **open and connected** for the worker to trade

### Step-by-Step Setup

**1. Clone the repo on Windows:**

```cmd
git clone https://github.com/ebuka-odih/mt5-worker.git C:\forex-mt5-bot
cd C:\forex-mt5-bot\mt5-worker
```

**2. Create virtual environment and install dependencies:**

```cmd
cd C:\forex-mt5-bot\mt5-worker
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**3. Configure the worker:**

For the **new Atlas 5k login**, do not reuse the old worker's live `.env`. Create the new worker env from the dedicated Atlas 5k template instead:

```cmd
copy .env.atlas-5k.example .env
notepad .env
```

Edit `.env` with these values:

```env
# VPS Brain URL (use the active Atlas 5k tunnel or direct 8782 host)
# Tunnel example: https://<fresh-atlas-5k-tunnel>.trycloudflare.com
# Direct host example: http://<vps-host-or-ip>:8782
VPS_API_BASE=https://<fresh-atlas-5k-tunnel>.trycloudflare.com

# Worker auth token (MUST match deployed Atlas 5k VPS config; do not commit real tokens)
WORKER_TOKEN=<set-to-atlas-5k-worker-token>

# Dedicated worker identity for the new 5k login
WORKER_ID=windows-mt5-atlas-5k-01
MT5_MAGIC=552701

# Start with DRY_RUN=true, then false for live
DRY_RUN=true
```

**4. Test in dry-run mode first:**

```cmd
venv\Scripts\python windows_mt5_worker.py
```

You should see:
```
[INFO] mt5-worker: Starting Windows MT5 worker
[INFO] mt5-worker:   VPS API:   https://<fresh-atlas-5k-tunnel>.trycloudflare.com
[INFO] mt5-worker:   Dry Run:   True
[INFO] mt5-worker: MT5 connected: login=XXXXX, server=AtlasFunded, balance=5000.0
```

**5. Go live (only after dry-run looks good):**

Edit `.env`:
```env
DRY_RUN=false
```

Restart the worker.

**6. Pull future updates on Windows:**

```cmd
cd C:\forex-mt5-bot
git pull
cd mt5-worker
venv\Scripts\python windows_mt5_worker.py
```

For this Atlas 5k rollout, restart only the **new** 5k worker/service after `git pull`. Leave the old login worker/service untouched.

If the old login already runs under NSSM or Task Scheduler, create a **separate** service/task name for the new login worker (for example `MT5WorkerAtlas5K`) instead of reusing the old one. After `git pull`, restart only that Atlas 5k service/task and leave the old login service running unchanged.

### Running in Background

**Option A — Simple background:**
```cmd
start /b venv\Scripts\python windows_mt5_worker.py >> worker.log 2>&1
```

**Option B — Windows Service with NSSM:**
```cmd
nssm install MT5Worker "C:\forex-mt5-bot\mt5-worker\venv\Scripts\python.exe" "C:\forex-mt5-bot\mt5-worker\windows_mt5_worker.py"
nssm set MT5Worker AppDirectory "C:\forex-mt5-bot\mt5-worker"
nssm set MT5Worker AppStdout "C:\forex-mt5-bot\mt5-worker\worker.log"
nssm set MT5Worker AppStderr "C:\forex-mt5-bot\mt5-worker\worker.log"
nssm set MT5Worker AppRotateFiles 1
nssm start MT5Worker
```

**Option C — Task Scheduler (auto-start on boot):**
```cmd
schtasks /create /tn "MT5 Worker" /tr "C:\forex-mt5-bot\mt5-worker\venv\Scripts\python.exe C:\forex-mt5-bot\mt5-worker\windows_mt5_worker.py" /sc onstart /rl limited
```

## Configuration Reference

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `VPS_API_BASE` | ✅ | VPS brain URL (tunnel) | `http://127.0.0.1:8780` |
| `WORKER_TOKEN` | ✅ | Auth token (must match VPS) | — |
| `WORKER_ID` | No | Worker identifier | `windows-mt5-local-01` |
| `DRY_RUN` | No | `true`=test, `false`=live | `true` |
| `MT5_MAGIC` | No | Magic number for orders | `552501` |
| `POLL_SECONDS` | No | Signal poll interval | `1` |

## Risk Parameters (Atlas 5k isolated login)

Configured in `config/settings.atlas-5k.yaml`:

- **Starting balance:** $5,000
- **Internal max daily loss cap:** 2% ($100)
- **Daily loss budget:** $75
- **Risk per order:** $7.5
- **Leverage:** 10x max
- **Grid:** 600 spacing / 1200 TP / 600 SL
- **Levels:** 5 each side
- **Trend guard:** 2.0%
- **Symbols:** BTCUSD only
- **Loss policy:** `auto_close_loss_pct: 0.0` to preserve recovery-first behavior while underwater

## Grid-Strike Strategy

Scans configured FX pairs, rejects flat/trending/wide markets, ranks by score,
and builds symmetric buy/sell grid levels around current price.

Key files:
- `brain/signals/grid_strike.py` — scoring, filter, grid plan builder
- `config/settings.yaml` → `grid_strike:` section
- `brain/simulation/grid_dry_run.py` — backtester
- `portfolio_sim.py` — portfolio simulation

## Troubleshooting

For deployment and pre-live checks, use `docs/DEPLOYMENT_CHECKLIST.md`.

### Worker can't connect to VPS
```cmd
curl https://<fresh-atlas-5k-tunnel>.trycloudflare.com/health
```
If the 5k tunnel is stale, regenerate it on the VPS against the isolated port: `cloudflared tunnel --url http://localhost:8782`

### MT5 not connecting
- Ensure MT5 is open and logged into the **new Atlas 5k account**
- Check account balance is around $5k for this isolated login
- Verify `BTCUSD` is available in Market Watch

### No signals coming through
- Check the isolated 5k VPS brain is running on port `8782`
- Verify `WORKER_TOKEN` matches between `config/settings.atlas-5k.yaml` on the VPS and the Windows worker `.env`
- Check `worker.log` for errors

### Token mismatch
The token must be identical on both sides:
- **Windows** `.env`: `WORKER_TOKEN=<token>`
- **VPS** `.env`: `VPS_WORKER_TOKEN=<same token>`

## Quick Reference Commands

```cmd
:: Start worker
venv\Scripts\python windows_mt5_worker.py

:: View logs
type worker.log

:: Check if running
tasklist | findstr python

:: Stop worker
taskkill /f /im python.exe

:: Restart
taskkill /f /im python.exe && venv\Scripts\python windows_mt5_worker.py
```

## Go Live Checklist (Auto-Loop + Windows Pull)

This release adds an automatic strategy scan loop in the VPS brain. It only runs
when `app.mode` is set to `live`.

### 1) VPS: enable auto-loop and restart brain

On the VPS repository (`~/.hermes/projects/forex-mt5-bot`):

1. In `config/settings.yaml`, set:
   - `app.mode: live`
   - `market_data.symbols` to `BTCUSD` and `ETHUSD` only
2. Restart the brain service/container.
3. Verify health:

```bash
curl http://127.0.0.1:8780/health
```

Expected response includes `"mode":"live"`.

### 2) Windows: pull latest worker/bridge code

If the full repo is cloned on Windows:

```cmd
cd C:\forex-mt5-bot
git pull
```

If you run a standalone worker folder (`C:\mt5-worker`), copy updated files from
the repo to that folder after pulling.

### 3) Windows: verify `.env` for live execution

In `C:\mt5-worker\.env` confirm:

```env
VPS_API_BASE=https://<your-cloudflare-or-vps-url>
WORKER_TOKEN=<must match VPS token>
WORKER_ID=windows-mt5-local-01
DRY_RUN=false
```

### 4) Windows: restart worker

```cmd
taskkill /f /im python.exe
cd C:\mt5-worker
start /b venv\Scripts\python windows_mt5_worker.py >> worker.log 2>&1
```

### 5) Confirm end-to-end flow

1. Windows log should show:
   - `MT5 connected`
   - `Received signal: ... side=buy|sell`
   - `Order filled` or explicit rejection reason
2. VPS should show worker heartbeats and non-zero signal activity:

```bash
curl http://127.0.0.1:8780/health
curl http://127.0.0.1:8780/api/signals
```
