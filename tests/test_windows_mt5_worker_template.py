from pathlib import Path


def test_windows_worker_reads_worker_token_from_env_cleanly():
    worker_lines = Path("mt5-worker/windows_mt5_worker.py").read_text().splitlines()

    token_lines = [line.strip() for line in worker_lines if line.strip().startswith("TOKEN")]
    assert len(token_lines) == 1
    assert token_lines[0] == 'TOKEN = os.getenv("WORKER_TOKEN", "")'


def test_worker_env_example_contains_safe_placeholders_without_corruption():
    text = Path("mt5-worker/.env.example").read_text()

    assert "WORKER_TOKEN=CHANGE_ME_TO_A_STRONG_RANDOM_TOKEN" in text
    assert "CHANGE...OKEN" not in text
