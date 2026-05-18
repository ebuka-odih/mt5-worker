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
