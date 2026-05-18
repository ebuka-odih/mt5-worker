from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_readme_atlas_5k_windows_section_uses_5k_runtime_values() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "For the **new Atlas 5k login**, do not reuse the old worker's live `.env`." in readme
    assert "balance=5000.0" in readme
    assert "Configured in `config/settings.atlas-5k.yaml`:" in readme
    assert "- **Starting balance:** $5,000" in readme
    assert "- **Daily loss budget:** $75" in readme
    assert "- **Risk per order:** $7.5" in readme
    assert "- **Grid:** 600 spacing / 1200 TP / 600 SL" in readme
    assert "- **Symbols:** BTCUSD only" in readme


def test_atlas_5k_docs_are_deploy_ready_for_isolated_windows_env() -> None:
    root_readme = (PROJECT_ROOT / "README.md").read_text()
    worker_readme = (PROJECT_ROOT / "mt5-worker" / "README.md").read_text()
    setup_doc = (PROJECT_ROOT / "docs" / "ATLAS_5K_SECOND_INSTANCE_SETUP.md").read_text()
    combined = "\n".join([root_readme, worker_readme, setup_doc])

    assert "copy .env.atlas-5k.example .env.atlas-5k" in combined
    assert "windows_mt5_worker.py --env-file .env.atlas-5k" in combined
    assert "EXPECTED_MT5_LOGIN=<exact-new-atlas-5k-mt5-login>" in combined
    assert "DRY_RUN=true until the first connection/heartbeat is established" in combined
    assert "Do not use `taskkill /f /im python.exe` for this rollout" in combined
    assert "nssm install MT5WorkerAtlas5K" in combined
    assert "schtasks /create /tn \"MT5WorkerAtlas5K\"" in combined


def test_atlas_5k_docs_do_not_overwrite_old_worker_env_for_new_login() -> None:
    setup_doc = (PROJECT_ROOT / "docs" / "ATLAS_5K_SECOND_INSTANCE_SETUP.md").read_text()
    worker_readme = (PROJECT_ROOT / "mt5-worker" / "README.md").read_text()
    root_readme = (PROJECT_ROOT / "README.md").read_text()

    for text in (setup_doc, worker_readme, root_readme):
        assert "copy .env.atlas-5k.example .env\n" not in text
        assert "venv\\Scripts\\python windows_mt5_worker.py\n" not in text
