from __future__ import annotations

from pathlib import Path

import pytest

from analytics_service import HealthConnectAnalyticsService
from db_engine import HealthConnectDbEngine
from domain_models import DashboardFilterParams


def test_live_database_smoke() -> None:
    """Verify live database integration against health_connect_export.db."""
    live_db = Path(__file__).resolve().parent.parent / "data" / "health_connect_export.db"
    if not live_db.exists():
        pytest.skip("Live database file not found")

    engine = HealthConnectDbEngine(live_db)
    analytics = HealthConnectAnalyticsService(engine)

    # 1. Date range detection
    start_d, end_d = analytics.get_database_date_range()
    assert start_d is not None
    assert end_d is not None
    assert start_d <= end_d

    # 2. Total catalog (must have 77 tables)
    catalog = engine.get_all_tables_catalog()
    assert len(catalog) == 77

    # 3. Daily activity summary
    acts = analytics.get_daily_activity_summary(DashboardFilterParams())
    assert len(acts) > 0

    # 4. Apps and devices
    apps = analytics.get_apps_list()
    assert len(apps) > 0

    devices = analytics.get_devices_list()
    assert len(devices) > 0

    # 5. Sleep & Vitals
    sleeps = analytics.get_sleep_sessions(DashboardFilterParams())
    assert len(sleeps) > 0

    hr_df = analytics.get_heart_rate_summary_df(DashboardFilterParams())
    assert not hr_df.empty

    # 6. Body measurements (including basal_metabolic_rate)
    body_df = analytics.get_body_measurements_df(DashboardFilterParams())
    assert not body_df.empty
    assert "bmr_kcal" in body_df.columns

    # 7. Exercise sessions
    exercise_sessions = analytics.get_exercise_sessions(DashboardFilterParams())
    assert len(exercise_sessions) > 0
