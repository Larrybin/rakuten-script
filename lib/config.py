import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from lib.errors import ConfigError

_SETTINGS = None


@dataclass(frozen=True)
class Settings:
    project_root: Path
    google_service_account_file: Path
    google_spreadsheet_id: str
    adspower_api_base: str
    adspower_api_key: str


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _normalize_path(project_root: Path, value: str) -> Path:
    raw = (value or "").strip()
    if not raw:
        raise ConfigError("缺少 GOOGLE_SERVICE_ACCOUNT_FILE")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (project_root / path).resolve()
    return path


def load_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is not None:
        return _SETTINGS

    project_root = _project_root()
    load_dotenv(project_root / ".env")

    google_file = _normalize_path(project_root, os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", ""))
    if not google_file.exists():
        raise ConfigError(f"Google Service Account 文件不存在: {google_file}")
    if not google_file.is_file():
        raise ConfigError(f"Google Service Account 路径不是文件: {google_file}")

    api_base = (os.getenv("ADSPOWER_API_BASE") or "").strip()
    if not api_base:
        raise ConfigError("缺少 ADSPOWER_API_BASE")
    spreadsheet_id = (os.getenv("GOOGLE_SPREADSHEET_ID") or "").strip()
    if not spreadsheet_id:
        raise ConfigError("缺少 GOOGLE_SPREADSHEET_ID")

    _SETTINGS = Settings(
        project_root=project_root,
        google_service_account_file=google_file,
        google_spreadsheet_id=spreadsheet_id,
        adspower_api_base=api_base.rstrip("/"),
        adspower_api_key=(os.getenv("ADSPOWER_API_KEY") or "").strip(),
    )
    return _SETTINGS


def reset_settings_cache():
    global _SETTINGS
    _SETTINGS = None


def get_project_root() -> Path:
    return load_settings().project_root


def get_google_service_account_file() -> Path:
    return load_settings().google_service_account_file


def get_adspower_api_base() -> str:
    return load_settings().adspower_api_base


def get_adspower_api_key() -> str:
    return load_settings().adspower_api_key


def get_google_spreadsheet_id() -> str:
    return load_settings().google_spreadsheet_id
