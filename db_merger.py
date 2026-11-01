"""SQLite incremental differential merge engine for Google Health Connect exports."""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
from pathlib import Path
from typing import Final

import structlog

from backup_manager import run_backup
from domain_models import DriveSyncResult, TableMergeStat

_ROOT: Final[Path] = Path(__file__).resolve().parent
_DATA_DIR: Final[Path] = _ROOT / "data"
_DEFAULT_MASTER_DB: Final[Path] = _DATA_DIR / "health_connect_export.db"
_EXCLUDED_SYSTEM_TABLES: Final[frozenset[str]] = frozenset(
    {
        "sqlite_sequence",
        "sqlite_stat1",
        "android_metadata",
        "pre_migration_category_priority_table",
    }
)
_REFERENCE_TABLES: Final[tuple[str, ...]] = (
    "device_info_table",
    "device_data_provider_metadata_table",
    "application_info_table",
)
_CHILD_PARENT_MAP: Final[dict[str, tuple[str, str, str]]] = {
    "sleep_stages_table": ("sleep_session_record_table", "parent_key", "row_id"),
    "heart_rate_record_series_table": ("heart_rate_record_table", "parent_key", "row_id"),
    "exercise_route_table": ("exercise_session_record_table", "parent_key", "row_id"),
    "exercise_segments_table": ("exercise_session_record_table", "parent_key", "row_id"),
    "exercise_laps_table": ("exercise_session_record_table", "parent_key", "row_id"),
    "speed_record_table": ("SpeedRecordTable", "parent_key", "row_id"),
    "steps_cadence_record_table": ("StepsCadenceRecordTable", "parent_key", "row_id"),
    "power_record_table": ("PowerRecordTable", "parent_key", "row_id"),
    "cycling_pedaling_cadence_record_table": (
        "CyclingPedalingCadenceRecordTable",
        "parent_key",
        "row_id",
    ),
    "skin_temperature_delta_table": ("skin_temperature_record_table", "parent_key", "row_id"),
}
_LOG_TABLES: Final[frozenset[str]] = frozenset(
    {
        "read_access_logs_table",
        "access_logs_table",
        "change_logs_table",
        "change_log_request_table",
        "backup_change_token_table",
    }
)

logger = structlog.get_logger(__name__)


class DatabaseMergeError(Exception):
    """Raised when an unrecoverable error occurs during SQLite database merge."""


class SqliteDatabaseMerger:
    """Differential SQLite merger utilizing ATTACH DATABASE and schema-aware column filtering."""

    def __init__(self, master_db_path: Path = _DEFAULT_MASTER_DB) -> None:
        """Initialize merger with target master database path.

        Args:
            master_db_path: Path to local persistent master SQLite database.
        """
        self._master_db_path = master_db_path.resolve()

    @property
    def master_db_path(self) -> Path:
        """Return resolved path to master database."""
        return self._master_db_path

    @staticmethod
    def get_writable_columns(
        conn: sqlite3.Connection, table_name: str, schema: str = "main"
    ) -> list[str]:
        """Extract writable non-generated columns (hidden == 0) using PRAGMA table_xinfo.

        Args:
            conn: Open sqlite3.Connection.
            table_name: Table name string.
            schema: SQLite schema identifier ('main' or attached schema name).

        Returns:
            List of valid column names that can be targeted in INSERT statements.
        """
        cursor = conn.cursor()
        cursor.execute(f'PRAGMA {schema}.table_xinfo("{table_name}");')
        # table_xinfo row structure: cid, name, type, notnull, dflt_value, pk, hidden
        return [str(row[1]) for row in cursor.fetchall() if int(row[6]) == 0]

    @staticmethod
    def has_primary_or_unique_constraint(
        conn: sqlite3.Connection,
        table_name: str,
        schema: str = "main",
    ) -> bool:
        """Check if table has at least one PRIMARY KEY or UNIQUE constraint/index.

        Args:
            conn: Open sqlite3.Connection.
            table_name: Target table name.
            schema: SQLite schema identifier.

        Returns:
            True if table has PK or unique constraint, False otherwise.
        """
        cursor = conn.cursor()
        cursor.execute(f'PRAGMA {schema}.table_info("{table_name}");')
        if any(bool(row[5]) for row in cursor.fetchall()):
            return True

        cursor.execute(f'PRAGMA {schema}.index_list("{table_name}");')
        return any(bool(row[2]) for row in cursor.fetchall())

    @staticmethod
    def _build_select_expr(col_name: str, table_alias: str = "t") -> str:
        """Construct SQL expression for column with foreign key remapping where applicable."""
        if col_name == "app_info_id":
            return (
                f"coalesce((SELECT main_id FROM temp_app_map WHERE temp_id = {table_alias}.app_info_id), "
                f"{table_alias}.app_info_id)"
            )
        if col_name == "device_info_id":
            return (
                f"coalesce((SELECT main_id FROM temp_device_map WHERE temp_id = {table_alias}.device_info_id), "
                f"{table_alias}.device_info_id)"
            )
        if col_name == "device_data_provider_id":
            return (
                f"coalesce((SELECT main_id FROM temp_provider_map WHERE temp_id = {table_alias}.device_data_provider_id), "
                f"{table_alias}.device_data_provider_id)"
            )
        if col_name == "reader_app_id":
            return (
                f"coalesce((SELECT main_id FROM temp_app_map WHERE temp_id = {table_alias}.reader_app_id), "
                f"{table_alias}.reader_app_id)"
            )
        if col_name == "writer_app_id":
            return (
                f"coalesce((SELECT main_id FROM temp_app_map WHERE temp_id = {table_alias}.writer_app_id), "
                f"{table_alias}.writer_app_id)"
            )
        return f'{table_alias}."{col_name}"'

    def _prepare_reference_mappings(self, conn: sqlite3.Connection) -> list[TableMergeStat]:
        """Merge reference tables and populate temporary mapping tables for foreign key translation."""
        cursor = conn.cursor()
        ref_stats: list[TableMergeStat] = []

        # Create temporary mapping tables
        cursor.execute(
            "CREATE TEMP TABLE IF NOT EXISTS temp_device_map (temp_id INTEGER PRIMARY KEY, main_id INTEGER);"
        )
        cursor.execute(
            "CREATE TEMP TABLE IF NOT EXISTS temp_provider_map (temp_id INTEGER PRIMARY KEY, main_id INTEGER);"
        )
        cursor.execute(
            "CREATE TEMP TABLE IF NOT EXISTS temp_app_map (temp_id INTEGER PRIMARY KEY, main_id INTEGER);"
        )
        cursor.execute("DELETE FROM temp_device_map;")
        cursor.execute("DELETE FROM temp_provider_map;")
        cursor.execute("DELETE FROM temp_app_map;")

        cursor.execute("SELECT name FROM temp_db.sqlite_master WHERE type='table';")
        temp_tables = {str(r[0]) for r in cursor.fetchall()}
        cursor.execute("SELECT name FROM main.sqlite_master WHERE type='table';")
        main_tables = {str(r[0]) for r in cursor.fetchall()}

        # 1. Merge device_info_table
        if "device_info_table" in temp_tables and "device_info_table" in main_tables:
            cursor.execute('SELECT count(*) FROM main."device_info_table";')
            cnt_before = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO main.device_info_table (manufacturer, model, device_type, device_id, display_name, udi)
                SELECT t.manufacturer, t.model, t.device_type, t.device_id, t.display_name, t.udi
                FROM temp_db.device_info_table t
                WHERE NOT EXISTS (
                    SELECT 1 FROM main.device_info_table m
                    WHERE coalesce(m.manufacturer, '') = coalesce(t.manufacturer, '')
                      AND coalesce(m.model, '') = coalesce(t.model, '')
                      AND coalesce(m.device_type, 0) = coalesce(t.device_type, 0)
                      AND coalesce(m.device_id, '') = coalesce(t.device_id, '')
                      AND coalesce(m.display_name, '') = coalesce(t.display_name, '')
                      AND coalesce(m.udi, '') = coalesce(t.udi, '')
                );
                """
            )
            cursor.execute('SELECT count(*) FROM main."device_info_table";')
            diff = max(0, int(cursor.fetchone()[0]) - cnt_before)
            if diff > 0:
                ref_stats.append(TableMergeStat(table_name="device_info_table", rows_inserted=diff))

            cursor.execute(
                """
                INSERT OR REPLACE INTO temp_device_map (temp_id, main_id)
                SELECT t.row_id, m.row_id
                FROM temp_db.device_info_table t
                JOIN main.device_info_table m ON
                    coalesce(m.manufacturer, '') = coalesce(t.manufacturer, '')
                    AND coalesce(m.model, '') = coalesce(t.model, '')
                    AND coalesce(m.device_type, 0) = coalesce(t.device_type, 0)
                    AND coalesce(m.device_id, '') = coalesce(t.device_id, '')
                    AND coalesce(m.display_name, '') = coalesce(t.display_name, '')
                    AND coalesce(m.udi, '') = coalesce(t.udi, '');
                """
            )

        # 2. Merge device_data_provider_metadata_table
        if (
            "device_data_provider_metadata_table" in temp_tables
            and "device_data_provider_metadata_table" in main_tables
        ):
            cursor.execute('SELECT count(*) FROM main."device_data_provider_metadata_table";')
            cnt_before = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO main.device_data_provider_metadata_table (source_package_name)
                SELECT t.source_package_name
                FROM temp_db.device_data_provider_metadata_table t
                WHERE NOT EXISTS (
                    SELECT 1 FROM main.device_data_provider_metadata_table m
                    WHERE coalesce(m.source_package_name, '') = coalesce(t.source_package_name, '')
                );
                """
            )
            cursor.execute('SELECT count(*) FROM main."device_data_provider_metadata_table";')
            diff = max(0, int(cursor.fetchone()[0]) - cnt_before)
            if diff > 0:
                ref_stats.append(
                    TableMergeStat(
                        table_name="device_data_provider_metadata_table", rows_inserted=diff
                    )
                )

            cursor.execute(
                """
                INSERT OR REPLACE INTO temp_provider_map (temp_id, main_id)
                SELECT t.row_id, m.row_id
                FROM temp_db.device_data_provider_metadata_table t
                JOIN main.device_data_provider_metadata_table m ON
                    coalesce(m.source_package_name, '') = coalesce(t.source_package_name, '');
                """
            )

        # 3. Merge application_info_table
        if "application_info_table" in temp_tables and "application_info_table" in main_tables:
            cursor.execute('SELECT count(*) FROM main."application_info_table";')
            cnt_before = int(cursor.fetchone()[0])
            app_cols = self.get_writable_columns(conn, "application_info_table", schema="main")
            non_pk_app_cols = [c for c in app_cols if c != "row_id"]
            select_app_exprs = [self._build_select_expr(c, "t") for c in non_pk_app_cols]

            insert_cols_str = ", ".join(f'"{c}"' for c in non_pk_app_cols)
            select_exprs_str = ", ".join(select_app_exprs)
            cursor.execute(
                f"""
                INSERT OR IGNORE INTO main.application_info_table ({insert_cols_str})
                SELECT {select_exprs_str} FROM temp_db.application_info_table t;
                """
            )
            cursor.execute('SELECT count(*) FROM main."application_info_table";')
            diff = max(0, int(cursor.fetchone()[0]) - cnt_before)
            if diff > 0:
                ref_stats.append(
                    TableMergeStat(table_name="application_info_table", rows_inserted=diff)
                )

            cursor.execute(
                """
                INSERT OR REPLACE INTO temp_app_map (temp_id, main_id)
                SELECT t.row_id, m.row_id
                FROM temp_db.application_info_table t
                JOIN main.application_info_table m ON m.package_name = t.package_name;
                """
            )

        return ref_stats

    def merge_from_temp_db(
        self,
        temp_db_path: Path,
        source_file_name: str = "downloaded_export.db",
        skip_pre_backup: bool = False,
        replace_master: bool = False,
    ) -> DriveSyncResult:
        """Merge records from temporary SQLite database into master database with backup protection.

        Args:
            temp_db_path: Path to downloaded temporary SQLite database.
            source_file_name: Human-readable name of the source export file for logging.
            skip_pre_backup: If True, bypass pre-merge backup (useful for unit tests).
            replace_master: If True, fully overwrite master database with downloaded database.

        Returns:
            DriveSyncResult containing operation status and merged statistics.

        Raises:
            DatabaseMergeError: If merge fails critically.
        """
        temp_db = temp_db_path.resolve()
        if not temp_db.is_file():
            raise DatabaseMergeError(f"テンポラリデータベースファイルが存在しません: {temp_db}")

        # Case 1: Master database does not exist yet -> Initial bootstrap
        if not self._master_db_path.exists():
            self._master_db_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(str(temp_db), str(self._master_db_path))
            except OSError as e:
                raise DatabaseMergeError(f"マスターDBの初期作成に失敗しました: {e!s}") from e

            # Inspect initial table counts
            initial_stats = self._inspect_total_rows(self._master_db_path)
            total_rows = sum(s.rows_inserted for s in initial_stats)
            return DriveSyncResult(
                success=True,
                message=f"マスターDBを新規作成しました (全{len(initial_stats)}テーブル, {total_rows}件初期同期)",
                downloaded_file_name=source_file_name,
                total_rows_merged=total_rows,
                table_stats=initial_stats,
                backup_zip_path=None,
            )

        # Case 2: Full replacement requested
        if replace_master:
            backup_zip_path: str | None = None
            if not skip_pre_backup:
                backup_res = run_backup(
                    app_name="health_viewer_pre_merge",
                    source_dir=str(self._master_db_path.parent),
                )
                if not backup_res.get("success", False):
                    raise DatabaseMergeError(
                        f"全置換前のバックアップに失敗したため、処理を中断しました: {backup_res.get('message')}"
                    )
                backup_zip_path = str(backup_res.get("destination", ""))

            self._master_db_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(str(temp_db), str(self._master_db_path))
            except OSError as e:
                raise DatabaseMergeError(f"マスターDBの全置換コピーに失敗しました: {e!s}") from e

            all_stats = self._inspect_total_rows(self._master_db_path)
            total_rows = sum(s.rows_inserted for s in all_stats)
            return DriveSyncResult(
                success=True,
                message=f"マスターDBを全置換しました (全{len(all_stats)}テーブル, {total_rows}件)",
                downloaded_file_name=source_file_name,
                total_rows_merged=total_rows,
                table_stats=all_stats,
                backup_zip_path=backup_zip_path,
            )

        # Case 3: Master database exists -> Pre-merge verified backup
        backup_zip_path = None
        if not skip_pre_backup:
            backup_res = run_backup(
                app_name="health_viewer_pre_merge",
                source_dir=str(self._master_db_path.parent),
            )
            if not backup_res.get("success", False):
                raise DatabaseMergeError(
                    f"安全マージ前のバックアップに失敗したため、処理を中断しました: {backup_res.get('message')}"
                )
            backup_zip_path = str(backup_res.get("destination", ""))

        # Connect with WAL and write lock capability
        conn = sqlite3.connect(str(self._master_db_path), timeout=60.0)
        conn.isolation_level = None  # Autocommit mode for ATTACH/DETACH control
        try:
            # Enforce foreign keys temporarily disabled during bulk schema merge
            conn.execute("PRAGMA foreign_keys = OFF;")

            # Attach temporary database
            temp_db_escaped = str(temp_db).replace("'", "''")
            conn.execute(f"ATTACH DATABASE '{temp_db_escaped}' AS temp_db;")

            # Discover all common user tables
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM temp_db.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
            temp_tables = {str(row[0]) for row in cursor.fetchall()} - _EXCLUDED_SYSTEM_TABLES

            cursor.execute(
                "SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
            main_tables = {str(row[0]) for row in cursor.fetchall()} - _EXCLUDED_SYSTEM_TABLES

            common_tables = set(temp_tables & main_tables)
            table_stats: list[TableMergeStat] = []
            total_merged = 0

            # Atomic Transaction Block
            conn.execute("BEGIN IMMEDIATE;")
            try:
                # 1. Merge reference tables and populate mapping tables
                ref_stats = self._prepare_reference_mappings(conn)
                table_stats.extend(ref_stats)
                total_merged += sum(s.rows_inserted for s in ref_stats)

                # Partition tables into groups
                regular_tables = sorted(
                    common_tables
                    - set(_REFERENCE_TABLES)
                    - set(_CHILD_PARENT_MAP.keys())
                    - _LOG_TABLES
                )
                child_tables = [t for t in _CHILD_PARENT_MAP if t in common_tables]
                log_tables = sorted(common_tables & _LOG_TABLES)

                # 2. Merge regular / parent record tables
                for table_name in regular_tables:
                    main_cols = self.get_writable_columns(conn, table_name, schema="main")
                    temp_cols = self.get_writable_columns(conn, table_name, schema="temp_db")
                    common_cols = [c for c in temp_cols if c in main_cols]

                    if not common_cols:
                        continue

                    cursor.execute(f'SELECT count(*) FROM main."{table_name}";')
                    cnt_before = int(cursor.fetchone()[0])

                    cursor.execute(f'PRAGMA main.table_info("{table_name}");')
                    pk_cols = [str(r[1]) for r in cursor.fetchall() if int(r[5]) > 0]

                    cursor.execute(f'PRAGMA main.index_list("{table_name}");')
                    has_unique_idx = any(bool(r[2]) for r in cursor.fetchall())

                    exclude_pk = (
                        len(pk_cols) == 1 and pk_cols[0].endswith("row_id") and has_unique_idx
                    )

                    target_cols = [c for c in common_cols if not (exclude_pk and c == pk_cols[0])]
                    cols_clause = ", ".join(f'"{c}"' for c in target_cols)
                    select_exprs = [self._build_select_expr(c, "t") for c in target_cols]
                    select_clause = ", ".join(select_exprs)

                    has_pk = self.has_primary_or_unique_constraint(conn, table_name, schema="main")
                    if has_pk:
                        merge_sql = (
                            f'INSERT OR IGNORE INTO main."{table_name}" ({cols_clause}) '
                            f'SELECT {select_clause} FROM temp_db."{table_name}" t;'
                        )
                    else:
                        merge_sql = (
                            f'INSERT INTO main."{table_name}" ({cols_clause}) '
                            f'SELECT {select_clause} FROM temp_db."{table_name}" t '
                            f"EXCEPT "
                            f'SELECT {cols_clause} FROM main."{table_name}";'
                        )

                    cursor.execute(merge_sql)

                    cursor.execute(f'SELECT count(*) FROM main."{table_name}";')
                    cnt_after = int(cursor.fetchone()[0])
                    diff = max(0, cnt_after - cnt_before)

                    if diff > 0:
                        table_stats.append(
                            TableMergeStat(table_name=table_name, rows_inserted=diff)
                        )
                        total_merged += diff

                # 3. Merge child tables with parent_key remapped via uuid
                for table_name in child_tables:
                    parent_table, fk_col, parent_pk = _CHILD_PARENT_MAP[table_name]
                    main_cols = self.get_writable_columns(conn, table_name, schema="main")
                    temp_cols = self.get_writable_columns(conn, table_name, schema="temp_db")
                    common_cols = [c for c in temp_cols if c in main_cols]

                    if not common_cols or parent_table not in common_tables:
                        continue

                    cursor.execute(f'SELECT count(*) FROM main."{table_name}";')
                    cnt_before = int(cursor.fetchone()[0])

                    cols_clause = ", ".join(f'"{c}"' for c in common_cols)
                    select_exprs = [
                        f'm."{parent_pk}" AS "{fk_col}"' if c == fk_col else f'c."{c}"'
                        for c in common_cols
                    ]
                    select_clause = ", ".join(select_exprs)

                    merge_sql = (
                        f'INSERT INTO main."{table_name}" ({cols_clause}) '
                        f"SELECT {select_clause} "
                        f'FROM temp_db."{table_name}" c '
                        f'JOIN temp_db."{parent_table}" p ON c."{fk_col}" = p."{parent_pk}" '
                        f'JOIN main."{parent_table}" m ON p.uuid = m.uuid '
                        f"EXCEPT "
                        f'SELECT {cols_clause} FROM main."{table_name}";'
                    )

                    cursor.execute(merge_sql)

                    cursor.execute(f'SELECT count(*) FROM main."{table_name}";')
                    cnt_after = int(cursor.fetchone()[0])
                    diff = max(0, cnt_after - cnt_before)

                    if diff > 0:
                        table_stats.append(
                            TableMergeStat(table_name=table_name, rows_inserted=diff)
                        )
                        total_merged += diff

                # 4. Merge log tables
                for table_name in log_tables:
                    main_cols = self.get_writable_columns(conn, table_name, schema="main")
                    temp_cols = self.get_writable_columns(conn, table_name, schema="temp_db")
                    common_cols = [c for c in temp_cols if c in main_cols]

                    if not common_cols:
                        continue

                    cursor.execute(f'SELECT count(*) FROM main."{table_name}";')
                    cnt_before = int(cursor.fetchone()[0])

                    target_cols = [c for c in common_cols if c != "row_id"]
                    cols_clause = ", ".join(f'"{c}"' for c in target_cols)
                    select_exprs = [self._build_select_expr(c, "t") for c in target_cols]
                    select_clause = ", ".join(select_exprs)

                    merge_sql = (
                        f'INSERT INTO main."{table_name}" ({cols_clause}) '
                        f'SELECT {select_clause} FROM temp_db."{table_name}" t '
                        f"EXCEPT "
                        f'SELECT {cols_clause} FROM main."{table_name}";'
                    )

                    cursor.execute(merge_sql)

                    cursor.execute(f'SELECT count(*) FROM main."{table_name}";')
                    cnt_after = int(cursor.fetchone()[0])
                    diff = max(0, cnt_after - cnt_before)

                    if diff > 0:
                        table_stats.append(
                            TableMergeStat(table_name=table_name, rows_inserted=diff)
                        )
                        total_merged += diff

                conn.execute("COMMIT;")
            except Exception as exc:
                conn.execute("ROLLBACK;")
                raise DatabaseMergeError(
                    f"差分マージ実行中にエラーが発生しロールバックしました: {exc!s}"
                ) from exc

            return DriveSyncResult(
                success=True,
                message=f"差分マージが完了しました: 新規 {total_merged} 件のレコードを追加 ({len(table_stats)} テーブル更新)",
                downloaded_file_name=source_file_name,
                total_rows_merged=total_merged,
                table_stats=table_stats,
                backup_zip_path=backup_zip_path,
            )

        finally:
            with contextlib.suppress(Exception):
                conn.execute("DETACH DATABASE temp_db;")
            conn.close()

    @staticmethod
    def _inspect_total_rows(db_path: Path) -> list[TableMergeStat]:
        """Inspect and return row counts for all tables in specified database."""
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
            tables = [
                str(r[0]) for r in cursor.fetchall() if str(r[0]) not in _EXCLUDED_SYSTEM_TABLES
            ]
            stats: list[TableMergeStat] = []
            for t in sorted(tables):
                cursor.execute(f'SELECT count(*) FROM "{t}";')
                cnt = int(cursor.fetchone()[0])
                stats.append(TableMergeStat(table_name=t, rows_inserted=cnt))
            return stats
        finally:
            conn.close()
