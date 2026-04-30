# Forex MT5 Bot Architecture

Goal: keep the strategy brain on this Linux VPS while executing orders through a local Windows machine running MetaTrader 5.

## Recommended topology

```text
Linux VPS: forex-mt5-bot brain
├── live forex market data fetcher
├── scanner + strategy logic
├── risk manager
├── signal queue API
├── logs/database/Telegram alerts later
└── HTTPS endpoint polled by Windows worker

Windows local machine: MT5 execution worker
├── MetaTrader 5 terminal installed and logged into broker
├── Python MetaTrader5 package or MQL5 EA bridge
├── outbound poll/WebSocket to VPS API
├── executes orders locally in MT5
└── posts fills/positions/account state back to VPS
```

## Why Windows should initiate the connection

A local Windows system is normally behind a router/firewall/NAT. The VPS may not be able to call the Windows machine directly unless you set up port forwarding, VPN, or tunnel. Safer default:

1. VPS creates signals and stores them in a queue.
2. Windows worker makes outbound HTTPS requests to the VPS every 1-2 seconds.
3. Worker pulls pending signals, executes them in MT5, and posts execution results back.

This avoids opening inbound ports on the Windows machine.

## Data sources

Before MT5 broker connection is live, the VPS can use public FX feeds for market understanding:

- `yfinance` FX tickers for near-real-time quotes and candles (free, delayed/variable reliability).
- Later: MT5 broker quotes from the Windows worker become the execution-grade source of truth.
- Optional later: paid data provider (TwelveData, Polygon, OANDA, ForexFeed) if we need reliable low-latency data.

## Security

- VPS API requires `X-Worker-Token` header.
- Windows worker should store token in `.env`, not hardcoded.
- No MT5 password/private broker credentials should be stored on VPS.
- VPS only receives account snapshots/position state, not broker login secrets.

## Signal lifecycle

```text
created → claimed_by_worker → executing → filled/rejected/cancelled
```

## Minimum viable flow

1. VPS fetches EURUSD/GBPUSD/USDJPY candles.
2. Brain creates paper signal when criteria match.
3. Signal is queued on VPS.
4. Windows worker polls `/api/worker/next-signal`.
5. Worker executes in MT5 paper/demo account.
6. Worker posts `/api/worker/execution-report`.
7. VPS tracks result and updates risk state.

## Live-trading rule

Do not enable live order execution until:

- Data feed has been stable for 24h.
- Windows worker heartbeat is reliable.
- Demo account order execution works.
- Risk manager enforces daily loss, max positions, lot sizing, SL/TP.
