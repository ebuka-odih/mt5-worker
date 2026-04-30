# Forex MT5 Bot

Linux VPS strategy brain + Windows local MT5 execution worker.

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
