# Forex MT5 Bot

Linux VPS strategy brain + Windows local MT5 execution worker.

## macOS production path

MetaTrader 5 on macOS runs inside the app's bundled Wine prefix. The official
`MetaTrader5` Python package only ships Windows wheels, so the practical macOS
deployment model is:

- Run the brain/API natively on macOS Python.
- Run the existing `windows_mt5_worker.py` inside the MT5 Wine prefix using the
  bundled `wine64`.

This repo includes helper scripts for that flow:

```bash
cd ~/Downloads/mt5-worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-brain.txt

./scripts/setup_macos_mt5_worker.sh
# edit mt5-worker/.env

./scripts/run_macos_brain.sh
./scripts/run_macos_mt5_worker.sh
```

`run_macos_brain.sh` prefers a native macOS Python 3.10+ virtualenv. If this
machine only has Python 3.9, it falls back to the Windows Python installed
inside the MT5 Wine prefix so the stack still runs locally.

The worker `.env` should normally point at the local API:

```env
VPS_API_BASE=http://127.0.0.1:8780
WORKER_TOKEN=CHANGE_ME_LONG_RANDOM_TOKEN
WORKER_ID=macos-mt5-local-01
DRY_RUN=true
```

## Quick test live public FX data

```bash
cd ~/.hermes/projects/forex-mt5-bot
source venv/bin/activate
PYTHONPATH=. python brain/data/forex_data.py
```

## Run the VPS brain API locally

```bash
cd ~/.hermes/projects/forex-mt5-bot
source venv/bin/activate
PYTHONPATH=. python -m uvicorn brain.api.server:app --host 0.0.0.0 --port 8780
```

Then test:

```bash
curl http://127.0.0.1:8780/health
curl http://127.0.0.1:8780/api/market/quotes
curl -X POST http://127.0.0.1:8780/api/scan
curl -X POST http://127.0.0.1:8780/api/grid-strike/scan
curl -X POST http://127.0.0.1:8780/api/grid-strike/plan
```

## Grid Strike scalping filter

The first forex strategy is the Grid Strike system: it scans configured FX pairs,
rejects markets that are too flat, too wide, or too one-directional, ranks the
remaining symbols, and builds symmetric buy/sell strike levels around the current
mid price for paper/demo testing.

Key files:

- `brain/signals/grid_strike.py` — Grid Strike scoring, currency filter, and grid plan builder.
- `config/settings.yaml` → `grid_strike:` — score thresholds, range limits, grid density, spacing, and lot size.
- `tests/test_grid_strike.py` and `tests/test_grid_strike_api.py` — regression tests.

## Windows worker

Copy `mt5-worker/windows_mt5_worker.py` to the Windows machine with MT5 installed.

Create `.env` on Windows:

```env
VPS_API_BASE=http://YOUR_VPS_IP:8780
WORKER_TOKEN=CHANGE_ME_LONG_RANDOM_TOKEN
WORKER_ID=windows-mt5-local-01
DRY_RUN=true
```

Start in DRY_RUN first. Then demo. Only then live.

## Go Live Checklist (Auto-Loop + Windows Pull)

This release adds an automatic strategy scan loop in the VPS brain. It only runs
when `app.mode` is set to `live`.

### 1) VPS: enable auto-loop and restart brain

On the VPS repository (`~/.hermes/projects/forex-mt5-bot`):

1. In `config/settings.yaml`, set:
   - `app.mode: live`
   - `market_data.symbols: [BTCUSD, ETHUSD]`
2. Restart the brain service/container.
3. Verify health:

```bash
curl http://127.0.0.1:8780/health
```

Expected response includes `\"mode\":\"live\"`.

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

Foreground:

```cmd
cd C:\mt5-worker
venv\Scripts\python windows_mt5_worker.py
```

Background:

```cmd
taskkill /f /im python.exe
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
