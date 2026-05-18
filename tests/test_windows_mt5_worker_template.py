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


def test_windows_worker_can_load_profile_specific_env_file():
    text = Path("mt5-worker/windows_mt5_worker.py").read_text()

    assert "--env-file" in text
    assert "WORKER_ENV_FILE" in text
    assert "load_dotenv(ENV_FILE)" in text


def test_profile_env_examples_require_expected_mt5_login_validation():
    atlas_5k = Path("mt5-worker/.env.atlas-5k.example").read_text()
    atlas_50k = Path("mt5-worker/.env.atlas-50k.example").read_text()

    assert "EXPECTED_MT5_LOGIN=" in atlas_5k
    assert "EXPECTED_MT5_LOGIN=" in atlas_50k
    assert "EXPECTED_MT5_LOGIN=CHANGE_ME_ATLAS_5K_LOGIN" in atlas_5k
    assert "EXPECTED_MT5_LOGIN=CHANGE_ME_ATLAS_50K_LOGIN" in atlas_50k


def test_worker_docs_show_one_script_profile_env_and_login_validation():
    readme = Path("mt5-worker/README.md").read_text()

    assert "one shared `windows_mt5_worker.py`" in readme
    assert "--env-file .env.atlas-5k" in readme
    assert "--env-file .env.atlas-50k" in readme
    assert "EXPECTED_MT5_LOGIN" in readme
    assert "Expected MT5 login" in readme
