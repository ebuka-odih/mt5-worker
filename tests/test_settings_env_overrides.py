import os

from shared.settings import load_settings


def test_load_settings_allows_worker_token_env_override(monkeypatch, tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        """
api:
  worker_token: CHANGE_ME_ATLAS_50K_INSTANT_WORKER_TOKEN
""".strip()
    )
    monkeypatch.setenv("WORKER_TOKEN", "runtime-secret-token")

    settings = load_settings(settings_path)

    assert settings.api.worker_token == "runtime-secret-token"


def test_load_settings_prefers_api_worker_token_over_worker_token(monkeypatch, tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        """
api:
  worker_token: CHANGE_ME_ATLAS_50K_INSTANT_WORKER_TOKEN
""".strip()
    )
    monkeypatch.setenv("WORKER_TOKEN", "generic-worker-token")
    monkeypatch.setenv("API_WORKER_TOKEN", "api-specific-token")

    settings = load_settings(settings_path)

    assert settings.api.worker_token == "api-specific-token"
