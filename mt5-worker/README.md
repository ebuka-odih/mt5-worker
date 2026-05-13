# Windows MT5 Worker

A lightweight Windows worker that connects MetaTrader 5 to the VPS forex brain. The worker polls the VPS for trading signals and executes them on the local MT5 terminal.

## Quick Start

### Atlas 5k second-login deployment note

For the **new Atlas 5k login account**, use the dedicated template `mt5-worker/.env.atlas-5k.example` and point it at the Atlas 5k VPS profile on port `8782`.

Keep the old login's worker/service running separately. Do not overwrite the existing live `.env` used by the old account.

If the repo is checked out at `C:\forex-mt5-bot`, start the new worker from `C:\forex-mt5-bot\mt5-worker` so it uses the new Atlas 5k `.env` instead of the old worker folder.

### Prerequisites

- Windows 10/11 with Python 3.9+
- MetaTrader 5 installed and logged into your funded trading account

### Setup

1. **Install Python dependencies:**
   ```cmd
   cd C:\mt5-worker
   py -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure the worker:**
   ```cmd
   copy .env.example .env
   notepad .env
   ```
   
   Edit `.env` and set:
   - `VPS_API_BASE` - Your Cloudflare tunnel URL from the VPS
   - `WORKER_TOKEN` - A strong random token (must match VPS)

3. **Generate a strong token:**
   ```cmd
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Copy the output to `WORKER_TOKEN` in both:
   - Windows worker `.env`
   - VPS `.env` (as `VPS_WORKER_TOKEN`)

### Running the Worker

**Start the worker:**
```cmd
venv\Scripts\python windows_mt5_worker.py
```

**Run in background (persistent):**
```cmd
start /b venv\Scripts\python windows_mt5_worker.py >> worker.log 2>&1
```

**Check if running:**
```cmd
tasklist | findstr python
```

**View logs:**
```cmd
type worker.log
```

**Stop the worker:**
```cmd
taskkill /f /im python.exe
```

## Configuration Reference

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `VPS_API_BASE` | Yes | VPS API URL (Cloudflare tunnel) | `http://127.0.0.1:8780` |
| `WORKER_TOKEN` | Yes | Shared secret for auth | - |
| `WORKER_ID` | No | Worker identifier | `windows-mt5-local-01` |
| `DRY_RUN` | No | `true`=test, `false`=live | `true` |
| `MT5_MAGIC` | No | Magic number for orders | `552501` |
| `POLL_SECONDS` | No | Signal poll interval | `1` |
| `MAX_RETRIES` | No | HTTP retry attempts | `3` |
| `RETRY_DELAY` | No | Base delay for retries (s) | `2` |

## Dry-Run Testing

To test the full signal flow without placing real orders:

1. Ensure `DRY_RUN=true` in `.env`
2. Start the worker: `venv\Scripts\python windows_mt5_worker.py`
3. The worker will log `[DRY_RUN] Would execute signal...` for each signal

### Inject a Test Signal (from VPS)

From the VPS, you can send a test signal via the API:

```bash
curl -X POST "https://your-tunnel-url/api/worker/test-signal?symbol=BTCUSD&side=buy&lots=0.01&worker_id=windows-mt5-local-01"
```

The worker will:
1. Poll and receive the signal
2. Log: `Received signal: id=..., symbol=BTCUSD, side=buy`
3. Log: `[DRY_RUN] Would execute signal...`
4. Report back: `status=filled, message=DRY_RUN accepted signal...`

## Position Telemetry

Every heartbeat now sends detailed open position data (ticket, symbol, side,
lots, entry/current price, floating PnL, magic, comment) to the VPS brain.
You can query this from VPS using:

```bash
curl "http://127.0.0.1:8780/api/workers?worker_token=<TOKEN>"
curl "http://127.0.0.1:8780/api/workers/<WORKER_ID>/positions?worker_token=<TOKEN>"
curl "http://127.0.0.1:8780/api/orders?worker_token=<TOKEN>&worker_id=<WORKER_ID>"
curl -X POST "http://127.0.0.1:8780/api/workers/<WORKER_ID>/auto-close?worker_token=<TOKEN>&profit_pct=3.0"
```

When `mt5_worker.auto_reopen_after_close=true`, a filled auto-close signal also
queues a new open signal so the worker can re-enter immediately.

## Production Deployment (Optional)

### Using NSSM (Non-Sucking Service Manager)

Download NSSM from https://nssm.cc/download and install as a Windows service:

```cmd
nssm install MT5Worker "C:\mt5-worker\venv\Scripts\python.exe" "C:\mt5-worker\windows_mt5_worker.py"
nssm set MT5Worker AppDirectory "C:\mt5-worker"
nssm set MT5Worker AppStdout "C:\mt5-worker\worker.log"
nssm set MT5Worker AppStderr "C:\mt5-worker\worker.log"
nssm set MT5Worker AppRotateFiles 1
nssm set MT5Worker AppRotateOnline 1
nssm set MT5Worker AppRotateSeconds 86400
nssm start MT5Worker
```

### Using Task Scheduler

Create a scheduled task to run on Windows startup:

```cmd
schtasks /create /tn "MT5 Worker" /tr "C:\mt5-worker\venv\Scripts\python.exe C:\mt5-worker\windows_mt5_worker.py" /sc onstart /rl limited
```

## Go Live With VPS Auto-Loop

The VPS brain can now auto-generate signals in live mode. To use it safely:

1. **On VPS, set live mode**
   - In `config/settings.yaml`, set `app.mode: live`.
   - Keep trade symbols restricted to `BTCUSD` and `ETHUSD`.
   - Restart the VPS brain container/service.

2. **On Windows, pull latest code**
   ```cmd
   cd C:\forex-mt5-bot
   git pull
   ```
   If you use `C:\mt5-worker` as a standalone folder, update it from the pulled files.

3. **Set worker live env**
   ```env
   VPS_API_BASE=https://<your-vps-url>
   WORKER_TOKEN=<must match VPS token>
   WORKER_ID=windows-mt5-local-01
   DRY_RUN=false
   ```

4. **Restart the worker**
   ```cmd
   taskkill /f /im python.exe
   cd C:\mt5-worker
   start /b venv\Scripts\python windows_mt5_worker.py >> worker.log 2>&1
   ```

5. **Verify logs**
   - `Received signal ... side=buy|sell`
   - `Order filled ...` (or a clear MT5 rejection reason)

## Troubleshooting

### MT5 Connection Issues

- Ensure MT5 is logged in and connected
- Check that the account is funded (required for live trading)
- Verify the symbol is available in MT5

### VPS Connection Issues

- Verify the Cloudflare tunnel is running on VPS: `curl https://your-tunnel-url/health`
- Check the token matches in both `.env` files
- Ensure port 443 is not blocked by firewall

### Worker Not Responding

1. Check if Python is running: `tasklist | findstr python`
2. View recent logs: `type worker.log | findstr /c:"ERROR" /c:"WARNING"`
3. Restart the worker: `taskkill /f /im python.exe` then start again

## Log Output Format

```
2026-04-30 12:00:00 [INFO] mt5-worker: Starting Windows MT5 worker
2026-04-30 12:00:00 [INFO] mt5-worker:   Worker ID: windows-mt5-local-01
2026-04-30 12:00:00 [INFO] mt5-worker:   VPS API:   https://xxx.trycloudflare.com
2026-04-30 12:00:00 [INFO] mt5-worker:   Dry Run:   True
2026-04-30 12:00:01 [INFO] mt5-worker: MT5 connected: login=12345, server=ICMarkets-Demo, balance=10000.0
2026-04-30 12:00:05 [INFO] mt5-worker: Received signal: id=abc123, symbol=BTCUSD, side=buy
2026-04-30 12:00:05 [INFO] mt5-worker: [DRY_RUN] Would execute signal abc123: BUY 0.01 BTCUSD
2026-04-30 12:00:05 [INFO] mt5-worker: Reported signal abc123: status=filled, message=DRY_RUN accepted signal...
```

## File Structure

```
C:\mt5-worker\
├── windows_mt5_worker.py   # Main worker script
├── .env                    # Configuration (create from .env.example)
├── .env.example            # Template for configuration
├── requirements.txt        # Python dependencies
├── README.md               # This file
└── worker.log              # Log output (created on first run)
```
