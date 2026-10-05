from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

import pytest

from db_engine import DatabaseConnectionError, HealthConnectDbEngine, TableNotFoundError
from domain_models import DashboardFilterParams, HealthDomainCategory


@pytest.fixture
def mock_db_path(tmp_path: Path) -> Path:
    """Create a temporary valid SQLite database for testing."""
    db_file = tmp_path / "test_health.db"
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE steps_record_table (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            count INTEGER NOT NULL,
            start_time INTEGER,
            app_info_id INTEGER,
            device_info_id INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE application_info_table (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_name TEXT NOT NULL,
            app_name TEXT,
            app_icon BLOB
        );
    """)
    cur.execute(
        "INSERT INTO steps_record_table (count, start_time, app_info_id, device_info_id) VALUES (5000, 1750000000000, 1, 1);"
    )
    cur.execute(
        "INSERT INTO steps_record_table (count, start_time, app_info_id, device_info_id) VALUES (3000, 1750086400000, 1, 1);"
    )
    cur.execute(
        "INSERT INTO application_info_table (package_name, app_name, app_icon) VALUES ('com.google.fit', 'Google Fit', X'89504E47');"
    )
    conn.commit()
    conn.close()
    return db_file


def test_db_engine_init_missing_file(tmp_path: Path) -> None:
    """Verify DatabaseConnectionError is raised if file is missing."""
    with pytest.raises(DatabaseConnectionError, match="データベースファイルが存在しません"):
        HealthConnectDbEngine(tmp_path / "non_existent.db")


def test_get_all_table_names(mock_db_path: Path) -> None:
    """Verify table names retrieval filters sqlite_ internal tables."""
    engine = HealthConnectDbEngine(mock_db_path)
    tables = engine.get_all_table_names()
    assert "application_info_table" in tables
    assert "steps_record_table" in tables
    assert all(not t.startswith("sqlite_") for t in tables)


def test_get_table_columns(mock_db_path: Path) -> None:
    """Verify column metadata extraction."""
    engine = HealthConnectDbEngine(mock_db_path)
    cols = engine.get_table_columns("steps_record_table")
    col_names = [c.name for c in cols]
    assert "row_id" in col_names
    assert "count" in col_names
    assert "start_time" in col_names


def test_get_table_row_count(mock_db_path: Path) -> None:
    """Verify row count computation."""
    engine = HealthConnectDbEngine(mock_db_path)
    assert engine.get_table_row_count("steps_record_table") == 2
    assert engine.get_table_row_count("application_info_table") == 1


def test_get_table_unknown_raises_error(mock_db_path: Path) -> None:
    """Verify TableNotFoundError when requesting nonexistent table."""
    engine = HealthConnectDbEngine(mock_db_path)
    with pytest.raises(
        TableNotFoundError, match="テーブル「unknown_table」はデータベースに存在しません"
    ):
        engine.get_table_row_count("unknown_table")


def test_get_all_tables_catalog(mock_db_path: Path) -> None:
    """Verify complete catalog metadata assembly."""
    engine = HealthConnectDbEngine(mock_db_path)
    catalog = engine.get_all_tables_catalog()
    assert len(catalog) == 2
    steps_meta = next(c for c in catalog if c.table_name == "steps_record_table")
    assert steps_meta.category == HealthDomainCategory.ACTIVITY
    assert steps_meta.row_count == 2
    assert steps_meta.has_data is True


def test_fetch_table_rows_and_blob_formatting(mock_db_path: Path) -> None:
    """Verify paginated fetch and BLOB conversion."""
    engine = HealthConnectDbEngine(mock_db_path)
    df = engine.fetch_table_rows("application_info_table", limit=10)
    assert len(df) == 1
    assert "Google Fit" in df["app_name"].values
    # BLOB column should be converted to string representation
    assert "<BLOB: 4 bytes>" in str(df["app_icon"].iloc[0])


def test_execute_query_forbidden_statements(mock_db_path: Path) -> None:
    """Verify non-SELECT/PRAGMA statements are blocked."""
    engine = HealthConnectDbEngine(mock_db_path)
    with pytest.raises(ValueError, match="読み取り専用エンジンでは"):
        engine.execute_query("DELETE FROM steps_record_table")


def test_epoch_millis_to_dt() -> None:
    """Verify epoch millis conversion to datetime."""
    dt = HealthConnectDbEngine.epoch_millis_to_dt(1750000000000)
    assert dt is not None
    assert dt.year == 2025
    assert HealthConnectDbEngine.epoch_millis_to_dt(None) is None


def test_build_time_filter_clause() -> None:
    """Verify time filter SQL WHERE fragment construction."""
    filters = DashboardFilterParams(
        start_date=datetime.date(2025, 6, 1),
        end_date=datetime.date(2025, 6, 30),
    )
    clause, params = HealthConnectDbEngine.build_time_filter_clause("start_time", filters)
    assert 'AND "start_time" >=' in clause
    assert 'AND "start_time" <=' in clause
    assert len(params) == 2

    # Empty filters
    empty_clause, empty_params = HealthConnectDbEngine.build_time_filter_clause(
        "start_time", DashboardFilterParams()
    )
    assert empty_clause == ""
    assert empty_params == []
