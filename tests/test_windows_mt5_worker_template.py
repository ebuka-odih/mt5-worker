from pathlib import Path


def test_windows_worker_reads_worker_token_from_env_cleanly():
    worker_lines = Path("mt5-worker/windows_mt5_worker.py").read_text().splitlines()

    token_lines = [line.strip() for line in worker_lines if line.strip().startswith("TOKEN")]
    assert len(token_lines) == 1
    assert "os.getenv" in token_lines[0]
    assert "WORKER_TOKEN" in token_lines[0]
    assert "..." not in token_lines[0]
