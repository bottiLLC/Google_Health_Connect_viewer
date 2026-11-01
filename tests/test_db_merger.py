"""Unit tests for SQLite incremental differential merger engine (db_merger.py)."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from db_merger import DatabaseMergeError, SqliteDatabaseMerger


def test_merge_non_existent_temp_db_raises_error() -> None:
    """Verify that merging a non-existent temp DB raises DatabaseMergeError."""
    # Arrange
    merger = SqliteDatabaseMerger(Path("/tmp/non_existent_master.db"))
    non_existent_temp = Path("/tmp/non_existent_temp.db")

    # Act & Assert
    with pytest.raises(DatabaseMergeError, match="テンポラリデータベースファイルが存在しません"):
        merger.merge_from_temp_db(non_existent_temp)


def test_merge_initial_bootstrap_creates_master_db() -> None:
    """Verify that if master DB is absent, merger performs initial bootstrap copy."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmp_dir:
        dir_path = Path(tmp_dir)
        master_path = dir_path / "master.db"
        temp_path = dir_path / "temp.db"

        # Create temp db with sample table and rows
        conn = sqlite3.connect(str(temp_path))
        conn.execute("CREATE TABLE sample_table (id INTEGER PRIMARY KEY, val TEXT);")
        conn.execute("INSERT INTO sample_table VALUES (1, 'alpha'), (2, 'beta');")
        conn.commit()
        conn.close()

        merger = SqliteDatabaseMerger(master_path)

        # Act
        result = merger.merge_from_temp_db(temp_path, source_file_name="initial.db")

        # Assert
        assert result.success is True
        assert master_path.exists()
        assert result.total_rows_merged == 2
        assert "新規作成" in result.message

        # Verify rows in master
        master_conn = sqlite3.connect(str(master_path))
        rows = master_conn.execute("SELECT * FROM sample_table ORDER BY id;").fetchall()
        master_conn.close()
        assert rows == [(1, "alpha"), (2, "beta")]


def test_merge_with_generated_columns_and_pk() -> None:
    """Verify that generated columns are bypassed and primary key duplicates are ignored."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmp_dir:
        dir_path = Path(tmp_dir)
        master_path = dir_path / "master.db"
        temp_path = dir_path / "temp.db"

        # Master setup with generated column
        master_conn = sqlite3.connect(str(master_path))
        master_conn.execute(
            "CREATE TABLE steps (id INTEGER PRIMARY KEY, count INTEGER, double_count INT AS (count * 2));"
        )
        master_conn.execute("INSERT INTO steps (id, count) VALUES (1, 100);")
        master_conn.commit()
        master_conn.close()

        # Temp setup with overlapping row (id=1) and new row (id=2)
        temp_conn = sqlite3.connect(str(temp_path))
        temp_conn.execute(
            "CREATE TABLE steps (id INTEGER PRIMARY KEY, count INTEGER, double_count INT AS (count * 2));"
        )
        temp_conn.execute("INSERT INTO steps (id, count) VALUES (1, 100), (2, 200);")
        temp_conn.commit()
        temp_conn.close()

        merger = SqliteDatabaseMerger(master_path)

        # Act
        result = merger.merge_from_temp_db(temp_path, skip_pre_backup=True)

        # Assert
        assert result.success is True
        assert result.total_rows_merged == 1
        assert len(result.table_stats) == 1
        assert result.table_stats[0].table_name == "steps"
        assert result.table_stats[0].rows_inserted == 1

        # Check final content in master
        m_conn = sqlite3.connect(str(master_path))
        rows = m_conn.execute("SELECT id, count, double_count FROM steps ORDER BY id;").fetchall()
        m_conn.close()
        assert rows == [(1, 100, 200), (2, 200, 400)]


def test_merge_without_pk_uses_except_no_duplicates() -> None:
    """Verify that tables without PK use EXCEPT to avoid duplicate row insertion."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmp_dir:
        dir_path = Path(tmp_dir)
        master_path = dir_path / "master.db"
        temp_path = dir_path / "temp.db"

        # Table without PK
        m_conn = sqlite3.connect(str(master_path))
        m_conn.execute("CREATE TABLE series (parent_id INT, bpm INT, ts INT);")
        m_conn.execute("INSERT INTO series VALUES (10, 72, 1000), (10, 75, 2000);")
        m_conn.commit()
        m_conn.close()

        # Temp contains existing (10, 75, 2000) and new (10, 80, 3000)
        t_conn = sqlite3.connect(str(temp_path))
        t_conn.execute("CREATE TABLE series (parent_id INT, bpm INT, ts INT);")
        t_conn.execute("INSERT INTO series VALUES (10, 75, 2000), (10, 80, 3000);")
        t_conn.commit()
        t_conn.close()

        merger = SqliteDatabaseMerger(master_path)

        # Act
        result = merger.merge_from_temp_db(temp_path, skip_pre_backup=True)

        # Assert
        assert result.success is True
        assert result.total_rows_merged == 1
        assert result.table_stats[0].rows_inserted == 1

        # Verify no duplicate rows
        check_conn = sqlite3.connect(str(master_path))
        rows = check_conn.execute("SELECT * FROM series ORDER BY ts;").fetchall()
        check_conn.close()
        assert rows == [(10, 72, 1000), (10, 75, 2000), (10, 80, 3000)]


def test_merge_pre_backup_failure_aborts_merge() -> None:
    """Verify that merge aborts immediately if pre-merge backup fails."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmp_dir:
        dir_path = Path(tmp_dir)
        master_path = dir_path / "master.db"
        temp_path = dir_path / "temp.db"

        sqlite3.connect(str(master_path)).close()
        sqlite3.connect(str(temp_path)).close()

        merger = SqliteDatabaseMerger(master_path)

        # Mock backup failure
        with (
            patch("db_merger.run_backup", return_value={"success": False, "message": "Disk full"}),
            pytest.raises(DatabaseMergeError, match="安全マージ前のバックアップに失敗したため"),
        ):
            merger.merge_from_temp_db(temp_path, skip_pre_backup=False)


def test_merge_transaction_rollback_on_error() -> None:
    """Verify that any exception during table merge rolls back transaction and detaches temp_db."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmp_dir:
        dir_path = Path(tmp_dir)
        master_path = dir_path / "master.db"
        temp_path = dir_path / "temp.db"

        m_conn = sqlite3.connect(str(master_path))
        m_conn.execute("CREATE TABLE t1 (id INT PRIMARY KEY);")
        m_conn.execute("INSERT INTO t1 VALUES (1);")
        m_conn.commit()
        m_conn.close()

        t_conn = sqlite3.connect(str(temp_path))
        t_conn.execute("CREATE TABLE t1 (id INT PRIMARY KEY);")
        t_conn.execute("INSERT INTO t1 VALUES (2);")
        t_conn.commit()
        t_conn.close()

        merger = SqliteDatabaseMerger(master_path)

        # Inject error into cursor execute during merge
        with (
            patch.object(
                merger, "get_writable_columns", side_effect=RuntimeError("Simulated query failure")
            ),
            pytest.raises(
                DatabaseMergeError, match="差分マージ実行中にエラーが発生しロールバックしました"
            ),
        ):
            merger.merge_from_temp_db(temp_path, skip_pre_backup=True)

        # Confirm rollback: t1 in master must still have only 1 row
        check_conn = sqlite3.connect(str(master_path))
        count = check_conn.execute("SELECT count(*) FROM t1;").fetchone()[0]
        check_conn.close()
        assert count == 1


def test_get_writable_columns_and_has_pk() -> None:
    """Verify column metadata extraction and constraint detection methods."""
    # Arrange
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE test_table (id INTEGER PRIMARY KEY, val TEXT NOT NULL, gen INT AS (1 + 1));"
    )
    conn.execute("CREATE TABLE no_pk_table (x INT, y TEXT);")
    conn.execute("CREATE TABLE unique_table (code TEXT UNIQUE);")

    # Act
    cols = SqliteDatabaseMerger.get_writable_columns(conn, "test_table")
    has_pk_1 = SqliteDatabaseMerger.has_primary_or_unique_constraint(conn, "test_table")
    has_pk_2 = SqliteDatabaseMerger.has_primary_or_unique_constraint(conn, "no_pk_table")
    has_pk_3 = SqliteDatabaseMerger.has_primary_or_unique_constraint(conn, "unique_table")
    conn.close()

    # Assert
    assert cols == ["id", "val"]  # gen is excluded
    assert has_pk_1 is True
    assert has_pk_2 is False
    assert has_pk_3 is True


def test_merge_resolves_row_id_collision_for_records_with_unique_uuid() -> None:
    """Verify that records with row_id=1 in temp DB get auto-incremented in master if uuid is new."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        dir_path = Path(tmp_dir)
        master_path = dir_path / "master.db"
        temp_path = dir_path / "temp.db"

        # Create master with row_id=1, uuid='uuid_old'
        m_conn = sqlite3.connect(str(master_path))
        m_conn.execute(
            "CREATE TABLE steps_record_table (row_id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, count INT);"
        )
        m_conn.execute("INSERT INTO steps_record_table VALUES (1, 'uuid_old', 100);")
        m_conn.commit()
        m_conn.close()

        # Temp DB export restarts row_id at 1, but has new record with uuid='uuid_new'
        t_conn = sqlite3.connect(str(temp_path))
        t_conn.execute(
            "CREATE TABLE steps_record_table (row_id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, count INT);"
        )
        t_conn.execute(
            "INSERT INTO steps_record_table VALUES (1, 'uuid_old', 100), (2, 'uuid_new', 200);"
        )
        t_conn.commit()
        t_conn.close()

        merger = SqliteDatabaseMerger(master_path)
        result = merger.merge_from_temp_db(temp_path, skip_pre_backup=True)

        assert result.success is True
        assert result.total_rows_merged == 1

        check_conn = sqlite3.connect(str(master_path))
        rows = check_conn.execute(
            "SELECT row_id, uuid, count FROM steps_record_table ORDER BY row_id;"
        ).fetchall()
        check_conn.close()

        assert len(rows) == 2
        assert rows[0] == (1, "uuid_old", 100)
        assert rows[1] == (2, "uuid_new", 200)


def test_merge_remaps_child_table_parent_key_via_uuid() -> None:
    """Verify child tables (sleep_stages_table) have parent_key remapped to master parent row_id."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        dir_path = Path(tmp_dir)
        master_path = dir_path / "master.db"
        temp_path = dir_path / "temp.db"

        # Master has parent at row_id=10
        m_conn = sqlite3.connect(str(master_path))
        m_conn.execute(
            "CREATE TABLE sleep_session_record_table (row_id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, notes TEXT);"
        )
        m_conn.execute("CREATE TABLE sleep_stages_table (parent_key INTEGER, stage_type INTEGER);")
        m_conn.execute("INSERT INTO sleep_session_record_table VALUES (10, 'sess_1', 'old');")
        m_conn.execute("INSERT INTO sleep_stages_table VALUES (10, 1);")
        m_conn.commit()
        m_conn.close()

        # Temp has parent at row_id=1 (same sess_1) and row_id=2 (new sess_2)
        t_conn = sqlite3.connect(str(temp_path))
        t_conn.execute(
            "CREATE TABLE sleep_session_record_table (row_id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, notes TEXT);"
        )
        t_conn.execute("CREATE TABLE sleep_stages_table (parent_key INTEGER, stage_type INTEGER);")
        t_conn.execute(
            "INSERT INTO sleep_session_record_table VALUES (1, 'sess_1', 'old'), (2, 'sess_2', 'new');"
        )
        # Stages: (1, 1) is already in master; (1, 2) is new stage for sess_1; (2, 3) is stage for sess_2
        t_conn.execute("INSERT INTO sleep_stages_table VALUES (1, 1), (1, 2), (2, 3);")
        t_conn.commit()
        t_conn.close()

        merger = SqliteDatabaseMerger(master_path)
        result = merger.merge_from_temp_db(temp_path, skip_pre_backup=True)

        assert result.success is True

        check_conn = sqlite3.connect(str(master_path))
        parents = check_conn.execute(
            "SELECT row_id, uuid FROM sleep_session_record_table ORDER BY row_id;"
        ).fetchall()
        stages = check_conn.execute(
            "SELECT parent_key, stage_type FROM sleep_stages_table ORDER BY parent_key, stage_type;"
        ).fetchall()
        check_conn.close()

        assert parents == [(10, "sess_1"), (11, "sess_2")]
        # Stage (1, 1) deduplicated; (1, 2) mapped to 10; (2, 3) mapped to 11
        assert stages == [(10, 1), (10, 2), (11, 3)]


def test_merge_with_replace_master_true() -> None:
    """Verify replace_master=True completely overwrites master DB with temp DB."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        dir_path = Path(tmp_dir)
        master_path = dir_path / "master.db"
        temp_path = dir_path / "temp.db"

        m_conn = sqlite3.connect(str(master_path))
        m_conn.execute("CREATE TABLE sample (id INT PRIMARY KEY, val TEXT);")
        m_conn.execute("INSERT INTO sample VALUES (1, 'old');")
        m_conn.commit()
        m_conn.close()

        t_conn = sqlite3.connect(str(temp_path))
        t_conn.execute("CREATE TABLE sample (id INT PRIMARY KEY, val TEXT);")
        t_conn.execute("INSERT INTO sample VALUES (1, 'replaced'), (2, 'added');")
        t_conn.commit()
        t_conn.close()

        merger = SqliteDatabaseMerger(master_path)
        result = merger.merge_from_temp_db(temp_path, skip_pre_backup=True, replace_master=True)

        assert result.success is True
        assert "全置換" in result.message

        check_conn = sqlite3.connect(str(master_path))
        rows = check_conn.execute("SELECT id, val FROM sample ORDER BY id;").fetchall()
        check_conn.close()

        assert rows == [(1, "replaced"), (2, "added")]
