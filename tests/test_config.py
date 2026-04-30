from pathlib import Path

import pytest

from lib import config
from lib.errors import ConfigError


def test_load_settings_with_relative_path(tmp_path, monkeypatch):
    project_root = tmp_path
    env_file = project_root / ".env"
    secrets_dir = project_root / "secrets"
    secrets_dir.mkdir()
    service_account = secrets_dir / "google.json"
    service_account.write_text("{}", encoding="utf-8")
    env_file.write_text(
        "GOOGLE_SERVICE_ACCOUNT_FILE=./secrets/google.json\n"
        "GOOGLE_SPREADSHEET_ID=spreadsheet-123\n"
        "ADSPOWER_API_BASE=http://127.0.0.1:50325\n"
        "ADSPOWER_API_KEY=test-key\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "_project_root", lambda: project_root)
    config.reset_settings_cache()

    settings = config.load_settings()

    assert settings.project_root == project_root
    assert settings.google_service_account_file == service_account.resolve()
    assert settings.google_spreadsheet_id == "spreadsheet-123"
    assert settings.adspower_api_base == "http://127.0.0.1:50325"
    assert settings.adspower_api_key == "test-key"


def test_load_settings_missing_file(tmp_path, monkeypatch):
    project_root = tmp_path
    env_file = project_root / ".env"
    env_file.write_text(
        "GOOGLE_SERVICE_ACCOUNT_FILE=./secrets/missing.json\n"
        "GOOGLE_SPREADSHEET_ID=spreadsheet-123\n"
        "ADSPOWER_API_BASE=http://127.0.0.1:50325\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "_project_root", lambda: project_root)
    config.reset_settings_cache()

    with pytest.raises(ConfigError):
        config.load_settings()


def test_load_settings_missing_adspower_api_base(tmp_path, monkeypatch):
    project_root = tmp_path
    env_file = project_root / ".env"
    secrets_dir = project_root / "secrets"
    secrets_dir.mkdir()
    service_account = secrets_dir / "google.json"
    service_account.write_text("{}", encoding="utf-8")
    env_file.write_text(
        "GOOGLE_SERVICE_ACCOUNT_FILE=./secrets/google.json\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "_project_root", lambda: project_root)
    monkeypatch.delenv("ADSPOWER_API_BASE", raising=False)
    monkeypatch.delenv("ADSPOWER_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    config.reset_settings_cache()

    with pytest.raises(ConfigError):
        config.load_settings()


def test_load_settings_missing_spreadsheet_id(tmp_path, monkeypatch):
    project_root = tmp_path
    env_file = project_root / ".env"
    secrets_dir = project_root / "secrets"
    secrets_dir.mkdir()
    service_account = secrets_dir / "google.json"
    service_account.write_text("{}", encoding="utf-8")
    env_file.write_text(
        "GOOGLE_SERVICE_ACCOUNT_FILE=./secrets/google.json\n"
        "ADSPOWER_API_BASE=http://127.0.0.1:50325\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "_project_root", lambda: project_root)
    monkeypatch.delenv("GOOGLE_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("ADSPOWER_API_BASE", raising=False)
    monkeypatch.delenv("ADSPOWER_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    config.reset_settings_cache()

    with pytest.raises(ConfigError):
        config.load_settings()
