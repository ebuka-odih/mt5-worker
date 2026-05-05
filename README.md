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
https://jake-divisions-vanilla-cradle.trycloudflare.com
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
curl -X POST http://127.0.0.1:8780/api/grid-strike/plan
```

## Windows MT5 Worker Setup

### Prerequisites

- Windows 10/11 with Python 3.9+
- MetaTrader 5 installed and logged into your Atlas funded account
- MT5 must be **open and connected** for the worker to trade

### Step-by-Step Setup

**1. Copy the worker files to Windows:**

```cmd
mkdir C:\mt5-worker
copy \\vps\path\mt5-worker\windows_mt5_worker.py C:\mt5-worker\
copy \\vps\path\mt5-worker\requirements.txt C:\mt5-worker\
copy \\vps\path\mt5-worker\.env.example C:\mt5-worker\
```

Or clone the repo on Windows:
```cmd
git clone https://github.com/YOUR_USER/forex-mt5-bot.git C:\forex-mt5-bot
cd C:\forex-mt5-bot\mt5-worker
```

**2. Create virtual environment and install dependencies:**

```cmd
cd C:\mt5-worker
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**3. Configure the worker:**

```cmd
copy .env.example .env
notepad .env
```

Edit `.env` with these values:

```env
# VPS Brain URL (Cloudflare tunnel — refresh if stale)
VPS_API_BASE=https://jake-divisions-vanilla-cradle.trycloudflare.com

# Worker auth token (MUST match VPS config)
WORKER_TOKEN=991403c231352264deb0d3e949324189eff63f08ede89901d0dc22a3e152a693

# Worker ID (for multi-worker setups)
WORKER_ID=windows-mt5-local-01

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
[INFO] mt5-worker:   VPS API:   https://jake-divisions-vanilla-cradle.trycloudflare.com
[INFO] mt5-worker:   Dry Run:   True
[INFO] mt5-worker: MT5 connected: login=XXXXX, server=AtlasFunded, balance=400000.0
```

**5. Go live (only after dry-run looks good):**

Edit `.env`:
```env
DRY_RUN=false
```

Restart the worker.

### Running in Background

**Option A — Simple background:**
```cmd
start /b venv\Scripts\python windows_mt5_worker.py >> worker.log 2>&1
```

**Option B — Windows Service with NSSM:**
```cmd
nssm install MT5Worker "C:\mt5-worker\venv\Scripts\python.exe" "C:\mt5-worker\windows_mt5_worker.py"
nssm set MT5Worker AppDirectory "C:\mt5-worker"
nssm set MT5Worker AppStdout "C:\mt5-worker\worker.log"
nssm set MT5Worker AppStderr "C:\mt5-worker\worker.log"
nssm set MT5Worker AppRotateFiles 1
nssm start MT5Worker
```

**Option C — Task Scheduler (auto-start on boot):**
```cmd
schtasks /create /tn "MT5 Worker" /tr "C:\mt5-worker\venv\Scripts\python.exe C:\mt5-worker\windows_mt5_worker.py" /sc onstart /rl limited
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

## Risk Parameters (Atlas Funded)

Configured in `config/settings.yaml`:

- **Starting balance:** $400,000
- **Max drawdown:** 4% ($16,000)
- **Daily loss budget:** $4,000 (1%)
- **Risk per order:** $1,750
- **Leverage:** 10x max
- **Grid:** 500 levels each side
- **TP/SL:** 1000/500 pips (1:2 R:R)
- **Symbols:** BTCUSD, ETHUSD

## Grid-Strike Strategy

Scans configured FX pairs, rejects flat/trending/wide markets, ranks by score,
and builds symmetric buy/sell grid levels around current price.

Key files:
- `brain/signals/grid_strike.py` — scoring, filter, grid plan builder
- `config/settings.yaml` → `grid_strike:` section
- `brain/simulation/grid_dry_run.py` — backtester
- `portfolio_sim.py` — portfolio simulation

## Troubleshooting

### Worker can't connect to VPS
```cmd
curl https://jake-divisions-vanilla-cradle.trycloudflare.com/health
```
If tunnel is stale, regenerate on VPS: `cloudflared tunnel --url http://localhost:8780`

### MT5 not connecting
- Ensure MT5 is open and logged into Atlas funded account
- Check account balance is $400k
- Verify symbols (BTCUSD, ETHUSD) are available

### No signals coming through
- Check VPS brain is running on port 8780
- Verify `WORKER_TOKEN` matches in both `.env` files
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
