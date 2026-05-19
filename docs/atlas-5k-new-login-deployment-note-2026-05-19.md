# Atlas 5k new-login deployment note — 2026-05-19

This note is for the **new Atlas 5k MT5 login account**. It must not replace or interrupt the older/default MT5 login.

## Isolation summary

- Old/default VPS brain: keep running on `http://127.0.0.1:8780` using the default profile.
- New Atlas 5k VPS brain: separate Docker Compose project/profile on `http://127.0.0.1:8782`.
- New Atlas 5k config: `config/settings.atlas-5k.yaml`.
- New Atlas 5k compose file: `docker-compose.atlas-5k.yml`.
- New Atlas 5k Windows template: `mt5-worker/.env.atlas-5k.example`.
- New Atlas 5k worker ID: `windows-mt5-atlas-5k-01`.
- New Atlas 5k MT5 magic: `552701`.
- Do not edit the old worker `.env` in place.
- Do not stop or reuse the old Windows worker service/task.

## VPS pre-flight before touching Windows

Verify both runtimes before restarting the new login worker:

```bash
docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' | grep 'forex-brain' || true
python3 - <<'PY'
import urllib.request
for url in ['http://127.0.0.1:8780/health', 'http://127.0.0.1:8782/health']:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            print(url, r.status, r.read().decode())
    except Exception as e:
        print(url, 'ERROR', e)
PY
```

Expected meaning:

- `8780` healthy: old/default login brain is still running.
- `8782` healthy: new Atlas 5k brain is running.
- `8782` with `workers: 0`: VPS profile is up but the Windows 5k worker is not connected yet.
- If `8780` is down, recover the old/default stack separately first; do not solve that by changing the 5k profile.

## Windows setup for the new login

Use the repo checkout path and a dedicated profile env file:

```cmd
cd C:\forex-mt5-bot
git pull
cd mt5-worker
copy .env.atlas-5k.example .env.atlas-5k
notepad .env.atlas-5k
```

Set the new profile values only in `.env.atlas-5k`:

```env
VPS_API_BASE=https://<fresh-atlas-5k-tunnel-or-direct-host>
WORKER_TOKEN=<atlas-5k-worker-token>
WORKER_ID=windows-mt5-atlas-5k-01
DRY_RUN=false
POLL_SECONDS=1
MT5_MAGIC=552701
EXPECTED_MT5_LOGIN=<new-5k-mt5-login-number>
```

Notes:

- If `VPS_API_BASE` is a Cloudflare quick tunnel, use only `https://<tunnel-host>`; do not append `:8782` to the tunnel URL.
- Keep committed docs/templates on placeholders. Do not commit live tunnel URLs, worker tokens, MT5 passwords, or login secrets.
- Confirm the Windows MT5 terminal is logged into the **new 5k account** before launching this worker.
- `EXPECTED_MT5_LOGIN` is the safety gate: if Windows is logged into the wrong MT5 account, the worker rejects signals instead of trading the wrong login.

Start only the new 5k worker:

```cmd
cd C:\forex-mt5-bot\mt5-worker
venv\Scripts\python windows_mt5_worker.py --env-file .env.atlas-5k
```

If using NSSM or Task Scheduler, create a separate service/task such as `MT5WorkerAtlas5K`. Leave the old login service/task running unchanged.

## Monitoring endpoints

Use these against the 5k base URL (`http://<host>:8782` or the fresh 5k tunnel URL):

- `/health`
- `/api/signals`
- `/api/orders?worker_token=<TOKEN>&worker_id=windows-mt5-atlas-5k-01`
- `/api/workers?worker_token=<TOKEN>`
- `/api/workers/windows-mt5-atlas-5k-01/positions?worker_token=<TOKEN>`
- `/api/workers/windows-mt5-atlas-5k-01/diagnostics?worker_token=<TOKEN>`
- `/api/diagnostics/summary?worker_token=<TOKEN>`

These show whether the new login worker is connected, which signals are queued/executing/filled, current MT5 positions, and rejection/cooldown/close-reason counters.

## Live verification snapshot

Verified from the VPS at `2026-05-19T11:13:57Z`:

- `forex-brain` old/default container: healthy on port `8780`.
- `forex-brain-atlas-5k` new Atlas 5k container: healthy on port `8782`.
- `http://127.0.0.1:8780/health`: HTTP 200, mode `live`.
- `http://127.0.0.1:8782/health`: HTTP 200, mode `live`, `workers: 1`.

This confirms the new 5k runtime is separate and the old/default runtime is still running at the time of this note.
