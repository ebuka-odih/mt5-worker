# macOS Setup

## Architecture

On macOS, MetaTrader 5 is not a native Python host. The MT5 app bundle ships a
Wine runtime and creates a prefix at:

`~/Library/Application Support/net.metaquotes.wine.metatrader5`

The official `MetaTrader5` Python package is Windows-only, so the supported
deployment shape for this repo on macOS is:

1. Native macOS Python for the brain/API.
2. Windows Python inside the MT5 Wine prefix for the execution worker.

## One-time setup

```bash
cd ~/Downloads/mt5-worker

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-brain.txt

chmod +x scripts/*.sh
./scripts/setup_macos_mt5_worker.sh
```

If your local `python3` is older than 3.10, `run_macos_brain.sh` will fall back
to the Windows Python inside the MT5 Wine prefix.

Then edit:

`mt5-worker/.env`

Suggested local values:

```env
VPS_API_BASE=http://127.0.0.1:8780
WORKER_TOKEN=CHANGE_ME_LONG_RANDOM_TOKEN
WORKER_ID=macos-mt5-local-01
DRY_RUN=true
```

## Run locally

Terminal 1:

```bash
cd ~/Downloads/mt5-worker
./scripts/run_macos_brain.sh
```

Terminal 2:

```bash
cd ~/Downloads/mt5-worker
./scripts/run_macos_mt5_worker.sh
```

## Smoke test

Create a signal:

```bash
curl -X POST http://127.0.0.1:8780/api/signals/create \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSD","side":"buy","lots":0.01,"stop_loss":0,"take_profit":0}'
```

Check health:

```bash
curl http://127.0.0.1:8780/health
```

If `DRY_RUN=true`, the worker should accept the signal without placing a real
order.
