from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from analytics_service import HealthConnectAnalyticsService
from db_engine import HealthConnectDbEngine
from domain_models import DashboardFilterParams


@pytest.fixture
def analytics_mock_db(tmp_path: Path) -> Path:
    """Create a temporary populated SQLite database for analytics service testing."""
    db_file = tmp_path / "analytics_test.db"
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    # Steps & distance
    cur.execute("""
        CREATE TABLE steps_record_table (
            row_id INTEGER PRIMARY KEY,
            count INTEGER,
            start_time INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE distance_record_table (
            row_id INTEGER PRIMARY KEY,
            distance REAL,
            start_time INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE active_calories_burned_record_table (
            row_id INTEGER PRIMARY KEY,
            energy REAL,
            start_time INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE total_calories_burned_record_table (
            row_id INTEGER PRIMARY KEY,
            energy REAL,
            start_time INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE exercise_session_record_table (
            row_id INTEGER PRIMARY KEY,
            title TEXT,
            exercise_type INTEGER,
            start_time INTEGER,
            end_time INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE exercise_route_table (
            parent_key INTEGER,
            timestamp_millis INTEGER,
            latitude REAL,
            longitude REAL,
            altitude REAL
        );
    """)
    cur.execute("""
        CREATE TABLE weight_record_table (
            row_id INTEGER PRIMARY KEY,
            weight REAL,
            time INTEGER,
            device_info_id INTEGER,
            app_info_id INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE body_fat_record_table (
            row_id INTEGER PRIMARY KEY,
            percentage REAL,
            time INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE basal_metabolic_rate_record_table (
            row_id INTEGER PRIMARY KEY,
            bmr REAL,
            time INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE sleep_session_record_table (
            row_id INTEGER PRIMARY KEY,
            start_time INTEGER,
            end_time INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE sleep_stages_table (
            parent_key INTEGER,
            stage_type INTEGER,
            stage_start_time INTEGER,
            stage_end_time INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE heart_rate_record_series_table (
            parent_key INTEGER,
            beats_per_minute INTEGER,
            epoch_millis INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE oxygen_saturation_record_table (
            row_id INTEGER PRIMARY KEY,
            percentage REAL,
            time INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE application_info_table (
            row_id INTEGER PRIMARY KEY,
            package_name TEXT,
            app_name TEXT,
            record_types_used TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE device_info_table (
            row_id INTEGER PRIMARY KEY,
            manufacturer TEXT,
            model TEXT,
            device_type INTEGER,
            display_name TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE read_access_logs_table (
            row_id INTEGER PRIMARY KEY,
            reader_app_id INTEGER,
            writer_app_id INTEGER,
            record_type TEXT,
            read_time INTEGER
        );
    """)

    # Populate sample data (epoch: 1750000000000 = ~2025-06-15)
    cur.execute("INSERT INTO steps_record_table VALUES (1, 8000, 1750000000000);")
    cur.execute("INSERT INTO distance_record_table VALUES (1, 6200.0, 1750000000000);")
    cur.execute(
        "INSERT INTO active_calories_burned_record_table VALUES (1, 250000.0, 1750000000000);"
    )  # 250 kcal
    cur.execute(
        "INSERT INTO total_calories_burned_record_table VALUES (1, 1800000.0, 1750000000000);"
    )  # 1800 kcal

    # Exercise & route
    cur.execute(
        "INSERT INTO exercise_session_record_table VALUES (10, 'Morning Walk', 53, 1750000000000, 1750001800000);"
    )  # 30 min
    cur.execute(
        "INSERT INTO exercise_route_table VALUES (10, 1750000000000, 35.6895, 139.6917, 40.0);"
    )

    # Body measurements
    cur.execute(
        "INSERT INTO weight_record_table VALUES (1, 65000.0, 1750000000000, 1, 1);"
    )  # 65.0 kg
    cur.execute("INSERT INTO body_fat_record_table VALUES (1, 18.5, 1750000000000);")
    cur.execute("INSERT INTO basal_metabolic_rate_record_table VALUES (1, 1550.0, 1750000000000);")

    # Sleep
    cur.execute(
        "INSERT INTO sleep_session_record_table VALUES (100, 1750000000000, 1750028800000);"
    )  # 8 hours
    cur.execute("INSERT INTO sleep_stages_table VALUES (100, 4, 1750000000000, 1750014400000);")
    cur.execute("INSERT INTO sleep_stages_table VALUES (100, 5, 1750014400000, 1750028800000);")

    # Vitals
    cur.execute("INSERT INTO heart_rate_record_series_table VALUES (1, 72, 1750000000000);")
    cur.execute("INSERT INTO heart_rate_record_series_table VALUES (1, 80, 1750000100000);")
    cur.execute("INSERT INTO oxygen_saturation_record_table VALUES (1, 98.0, 1750000000000);")
    cur.execute(
        "INSERT INTO oxygen_saturation_record_table VALUES (2, 94.0, 1750000200000);"
    )  # low event

    # Apps & devices & audit
    cur.execute(
        "INSERT INTO application_info_table VALUES (1, 'com.google.fit', 'Fit', 'steps,weight');"
    )
    cur.execute("INSERT INTO device_info_table VALUES (1, 'Xiaomi', 'Redmi 12 5G', 2, 'My Phone');")
    cur.execute("INSERT INTO read_access_logs_table VALUES (1, 1, 1, 'steps', 1750000000000);")

    conn.commit()
    conn.close()
    return db_file


def test_get_database_date_range(analytics_mock_db: Path) -> None:
    """Verify detection of database earliest and latest date range."""
    engine = HealthConnectDbEngine(analytics_mock_db)
    service = HealthConnectAnalyticsService(engine)
    start_d, end_d = service.get_database_date_range()
    assert start_d is not None
    assert end_d is not None
    assert start_d <= end_d


def test_get_daily_activity_summary(analytics_mock_db: Path) -> None:
    """Verify aggregation of daily steps, distance, active/total calories."""
    engine = HealthConnectDbEngine(analytics_mock_db)
    service = HealthConnectAnalyticsService(engine)
    summaries = service.get_daily_activity_summary(DashboardFilterParams())
    assert len(summaries) == 1
    s = summaries[0]
    assert s.step_count == 8000
    assert s.distance_km == 6.2
    assert s.active_calories_kcal == 250.0
    assert s.total_calories_kcal == 1800.0


def test_get_exercise_sessions_and_route(analytics_mock_db: Path) -> None:
    """Verify exercise session retrieval and GPS route coordinates."""
    engine = HealthConnectDbEngine(analytics_mock_db)
    service = HealthConnectAnalyticsService(engine)
    sessions = service.get_exercise_sessions(DashboardFilterParams())
    assert len(sessions) == 1
    sess = sessions[0]
    assert sess.title == "Morning Walk"
    assert sess.exercise_type_name == "WALKING"
    assert sess.duration_minutes == 30.0
    assert sess.has_route is True

    points = service.get_exercise_route_points(sess.row_id)
    assert len(points) == 1
    p = points[0]
    assert p.latitude == 35.6895
    assert p.longitude == 139.6917


def test_get_body_measurements_df(analytics_mock_db: Path) -> None:
    """Verify body measurements extraction and unit normalization."""
    engine = HealthConnectDbEngine(analytics_mock_db)
    service = HealthConnectAnalyticsService(engine)
    df = service.get_body_measurements_df(DashboardFilterParams())
    assert not df.empty
    assert df["weight_kg"].iloc[0] == 65.0
    assert df["body_fat_pct"].iloc[0] == 18.5
    assert df["bmr_kcal"].iloc[0] == 1550.0


def test_get_sleep_sessions(analytics_mock_db: Path) -> None:
    """Verify sleep session and stage intervals."""
    engine = HealthConnectDbEngine(analytics_mock_db)
    service = HealthConnectAnalyticsService(engine)
    sessions = service.get_sleep_sessions(DashboardFilterParams())
    assert len(sessions) == 1
    sess = sessions[0]
    assert len(sess.stages) == 2
    assert sess.stages[0].stage_name == "浅い睡眠 (LIGHT)"
    assert sess.stages[1].stage_name == "深い睡眠 (DEEP)"


def test_get_heart_rate_and_oxygen_saturation(analytics_mock_db: Path) -> None:
    """Verify heart rate stats and oxygen saturation low event detection."""
    engine = HealthConnectDbEngine(analytics_mock_db)
    service = HealthConnectAnalyticsService(engine)
    df_hr = service.get_heart_rate_summary_df(DashboardFilterParams())
    assert not df_hr.empty
    assert df_hr["avg_bpm"].iloc[0] == 76.0
    assert df_hr["min_bpm"].iloc[0] == 72
    assert df_hr["max_bpm"].iloc[0] == 80

    df_o2 = service.get_oxygen_saturation_df(DashboardFilterParams())
    assert len(df_o2) == 2
    assert any(df_o2["is_low_event"])


def test_get_apps_devices_and_audit_logs(analytics_mock_db: Path) -> None:
    """Verify listing of apps, devices and audit read access logs."""
    engine = HealthConnectDbEngine(analytics_mock_db)
    service = HealthConnectAnalyticsService(engine)
    apps = service.get_apps_list()
    assert len(apps) == 1
    assert apps[0].app_name == "Fit"

    devices = service.get_devices_list()
    assert len(devices) == 1
    assert devices[0].model == "Redmi 12 5G"

    logs = service.get_read_access_audit_logs()
    assert len(logs) == 1
    assert logs[0].reader_app_name == "Fit"
