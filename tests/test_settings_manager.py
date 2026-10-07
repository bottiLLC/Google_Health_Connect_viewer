from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from domain_models import DEFAULT_VISIBLE_TABS, DashboardSettings, SummaryItemKey
from settings_manager import (
    load_dashboard_settings,
    reset_dashboard_settings,
    save_dashboard_settings,
)


def test_load_dashboard_settings_default_when_no_file(tmp_path: Path) -> None:
    """Ensure absent configuration file falls back to default settings."""
    fake_file = tmp_path / "dashboard_settings.json"
    with patch("settings_manager._SETTINGS_FILE", fake_file):
        settings = load_dashboard_settings()
        assert settings.visible_tabs == list(DEFAULT_VISIBLE_TABS)
        assert len(settings.visible_summary_items) == len(SummaryItemKey)


def test_save_and_load_dashboard_settings_roundtrip(tmp_path: Path) -> None:
    """Verify settings can be saved and accurately reloaded."""
    fake_file = tmp_path / "dashboard_settings.json"
    custom_settings = DashboardSettings(
        visible_tabs=["📊 サマリー", "😴 睡眠"],
        visible_summary_items=[SummaryItemKey.METRIC_SLEEP.value],
    )
    with patch("settings_manager._SETTINGS_FILE", fake_file):
        ok = save_dashboard_settings(custom_settings)
        assert ok is True
        assert fake_file.exists()

        reloaded = load_dashboard_settings()
        assert reloaded.visible_tabs == ["📊 サマリー", "😴 睡眠"]
        assert reloaded.visible_summary_items == [SummaryItemKey.METRIC_SLEEP.value]


def test_load_dashboard_settings_corrupted_json_fallback(tmp_path: Path) -> None:
    """Verify corrupted JSON gracefully falls back to default settings without crashing."""
    fake_file = tmp_path / "dashboard_settings.json"
    fake_file.write_text("{invalid_json_syntax...", encoding="utf-8")

    with patch("settings_manager._SETTINGS_FILE", fake_file):
        settings = load_dashboard_settings()
        assert settings.visible_tabs == list(DEFAULT_VISIBLE_TABS)


def test_load_dashboard_settings_non_dict_fallback(tmp_path: Path) -> None:
    """Verify non-dictionary JSON gracefully falls back to default settings."""
    fake_file = tmp_path / "dashboard_settings.json"
    fake_file.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

    with patch("settings_manager._SETTINGS_FILE", fake_file):
        settings = load_dashboard_settings()
        assert settings.visible_tabs == list(DEFAULT_VISIBLE_TABS)


def test_reset_dashboard_settings(tmp_path: Path) -> None:
    """Verify reset restores and writes default configuration."""
    fake_file = tmp_path / "dashboard_settings.json"
    fake_file.write_text(
        json.dumps({"visible_tabs": [], "visible_summary_items": []}), encoding="utf-8"
    )

    with patch("settings_manager._SETTINGS_FILE", fake_file):
        reset_settings = reset_dashboard_settings()
        assert reset_settings.visible_tabs == list(DEFAULT_VISIBLE_TABS)
        assert fake_file.exists()
        reloaded = load_dashboard_settings()
        assert reloaded.visible_tabs == list(DEFAULT_VISIBLE_TABS)


def test_save_dashboard_settings_os_error_handling(tmp_path: Path) -> None:
    """Verify filesystem permission failure during save returns False safely."""
    fake_file = tmp_path / "dashboard_settings.json"
    with (
        patch("settings_manager._SETTINGS_FILE", fake_file),
        patch.object(Path, "write_text", side_effect=OSError("Permission denied")),
    ):
        ok = save_dashboard_settings(DashboardSettings())
        assert ok is False
