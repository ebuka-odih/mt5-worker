from pathlib import Path

from scripts.sync_mt5_config import read_existing_dry_run, read_existing_env


def test_read_existing_dry_run_defaults_true_when_env_missing(tmp_path: Path) -> None:
    assert read_existing_dry_run(tmp_path) is True


def test_read_existing_dry_run_reads_false_from_worker_env(tmp_path: Path) -> None:
    env_path = tmp_path / "mt5-worker" / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("DRY_RUN=false\n")

    assert read_existing_dry_run(tmp_path) is False


def test_read_existing_env_returns_worker_values(tmp_path: Path) -> None:
    env_path = tmp_path / "mt5-worker" / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("VPS_API_BASE=https://example.com\nWORKER_ID=test-worker\n")

    assert read_existing_env(tmp_path) == {
        "VPS_API_BASE": "https://example.com",
        "WORKER_ID": "test-worker",
    }
