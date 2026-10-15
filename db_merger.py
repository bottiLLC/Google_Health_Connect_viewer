"""SQLite incremental differential merge engine for Google Health Connect exports."""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
from pathlib import Path
from typing import Final

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

    def merge_from_temp_db(
        self,
        temp_db_path: Path,
        source_file_name: str = "downloaded_export.db",
        skip_pre_backup: bool = False,
    ) -> DriveSyncResult:
        """Merge records from temporary SQLite database into master database with backup protection.

        Args:
            temp_db_path: Path to downloaded temporary SQLite database.
            source_file_name: Human-readable name of the source export file for logging.
            skip_pre_backup: If True, bypass pre-merge backup (useful for unit tests).

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

        # Case 2: Master database exists -> Pre-merge verified backup
        backup_zip_path: str | None = None
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
            # Escape single quotes in path
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

            common_tables = sorted(temp_tables & main_tables)
            table_stats: list[TableMergeStat] = []
            total_merged = 0

            # Atomic Transaction Block
            conn.execute("BEGIN IMMEDIATE;")
            try:
                for table_name in common_tables:
                    # Resolve common writable columns (excluding generated columns)
                    main_cols = self.get_writable_columns(conn, table_name, schema="main")
                    temp_cols = self.get_writable_columns(conn, table_name, schema="temp_db")
                    common_cols = [c for c in temp_cols if c in main_cols]

                    if not common_cols:
                        continue

                    # Record row count before merge
                    cursor.execute(f'SELECT count(*) FROM main."{table_name}";')
                    cnt_before = int(cursor.fetchone()[0])

                    has_pk = self.has_primary_or_unique_constraint(conn, table_name, schema="main")
                    cols_clause = ", ".join(f'"{c}"' for c in common_cols)

                    if has_pk:
                        # Tables with PK/UNIQUE: standard INSERT OR IGNORE
                        merge_sql = (
                            f'INSERT OR IGNORE INTO main."{table_name}" ({cols_clause}) '
                            f'SELECT {cols_clause} FROM temp_db."{table_name}";'
                        )
                    else:
                        # Tables without PK: EXCEPT set difference to prevent duplication
                        merge_sql = (
                            f'INSERT INTO main."{table_name}" ({cols_clause}) '
                            f'SELECT {cols_clause} FROM temp_db."{table_name}" '
                            f"EXCEPT "
                            f'SELECT {cols_clause} FROM main."{table_name}";'
                        )

                    cursor.execute(merge_sql)

                    # Record row count after merge
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
