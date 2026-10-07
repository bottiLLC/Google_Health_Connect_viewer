"""Persistent settings manager for Google Health Connect dashboard.

Provides deterministic and fail-safe loading and saving of user dashboard preferences
stored in ./data/dashboard_settings.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from domain_models import DashboardSettings

_SETTINGS_FILE: Final[Path] = Path(__file__).resolve().parent / "data" / "dashboard_settings.json"


def get_settings_file_path() -> Path:
    """Return resolved path to persistent dashboard settings JSON file."""
    return _SETTINGS_FILE


def load_dashboard_settings() -> DashboardSettings:
    """Load dashboard settings from persistent JSON file with automatic fallback.

    Returns:
        DashboardSettings instance loaded from file, or default settings if file is absent or corrupted.
    """
    if not _SETTINGS_FILE.exists():
        return DashboardSettings()

    try:
        content = _SETTINGS_FILE.read_text(encoding="utf-8")
        data = json.loads(content)
        if not isinstance(data, dict):
            return DashboardSettings()
        return DashboardSettings.model_validate(data)
    except OSError, json.JSONDecodeError, ValueError:
        return DashboardSettings()


def save_dashboard_settings(settings: DashboardSettings) -> bool:
    """Persist dashboard settings atomically to ./data/dashboard_settings.json.

    Args:
        settings: DashboardSettings model to persist.

    Returns:
        True if settings were successfully written, False otherwise.
    """
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = _SETTINGS_FILE.with_suffix(".tmp")
        temp_file.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        temp_file.replace(_SETTINGS_FILE)
        return True
    except OSError:
        return False


def reset_dashboard_settings() -> DashboardSettings:
    """Reset persistent dashboard settings to default configuration.

    Returns:
        Default DashboardSettings instance after removing or resetting file.
    """
    default_settings = DashboardSettings()
    save_dashboard_settings(default_settings)
    return default_settings
