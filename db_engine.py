"""Database access engine for Google Health Connect SQLite Export (Read-Only)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from domain_models import (
    ColumnMeta,
    DashboardFilterParams,
    TableCatalogMeta,
    resolve_category_for_table,
)


class DatabaseConnectionError(Exception):
    """Raised when SQLite database cannot be accessed or is invalid."""


class TableNotFoundError(Exception):
    """Raised when requesting a table that does not exist in the database."""


class HealthConnectDbEngine:
    """Read-only SQLite engine for Google Health Connect export database."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialize engine with path to SQLite database.

        Args:
            db_path: Path to SQLite database file.

        Raises:
            DatabaseConnectionError: If database file does not exist.
        """
        self._db_path = Path(db_path).resolve()
        if not self._db_path.exists():
            raise DatabaseConnectionError(f"データベースファイルが存在しません: {self._db_path}")

    @property
    def db_path(self) -> Path:
        """Return resolved database file path."""
        return self._db_path

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Provide a read-only SQLite connection context.

        Yields:
            sqlite3.Connection configured with URI mode=ro.
        """
        # Convert path to URI format for read-only access
        uri_path = f"file:{self._db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri_path, uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def get_all_table_names(self) -> list[str]:
        """Fetch all user-defined table names sorted alphabetically.

        Returns:
            List of table names excluding internal sqlite_ tables.
        """
        query = (
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name;"
        )
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            return [str(row[0]) for row in cursor.fetchall()]

    def get_table_columns(self, table_name: str) -> list[ColumnMeta]:
        """Extract column metadata using PRAGMA table_info.

        Args:
            table_name: Validated table name.

        Returns:
            List of ColumnMeta objects.

        Raises:
            TableNotFoundError: If table does not exist.
        """
        self._validate_table_name(table_name)
        query = f'PRAGMA table_info("{table_name}");'
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            cols: list[ColumnMeta] = []
            for row in cursor.fetchall():
                cols.append(
                    ColumnMeta(
                        cid=int(row["cid"]),
                        name=str(row["name"]),
                        type_name=str(row["type"]),
                        not_null=bool(row["notnull"]),
                        default_value=str(row["dflt_value"])
                        if row["dflt_value"] is not None
                        else None,
                        is_pk=bool(row["pk"]),
                    )
                )
            return cols

    def get_table_row_count(self, table_name: str) -> int:
        """Get exact count of rows in table.

        Args:
            table_name: Validated table name.

        Returns:
            Integer row count.
        """
        self._validate_table_name(table_name)
        query = f'SELECT count(*) FROM "{table_name}";'
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def get_all_tables_catalog(self) -> list[TableCatalogMeta]:
        """Scan and assemble complete catalog for all 77 tables.

        Returns:
            List of TableCatalogMeta containing schema, category and row count.
        """
        table_names = self.get_all_table_names()
        catalog: list[TableCatalogMeta] = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for name in table_names:
                cursor.execute(f'SELECT count(*) FROM "{name}";')
                count_row = cursor.fetchone()
                cnt = int(count_row[0]) if count_row else 0

                cursor.execute(f'PRAGMA table_info("{name}");')
                cols: list[ColumnMeta] = [
                    ColumnMeta(
                        cid=int(r["cid"]),
                        name=str(r["name"]),
                        type_name=str(r["type"]),
                        not_null=bool(r["notnull"]),
                        default_value=str(r["dflt_value"]) if r["dflt_value"] is not None else None,
                        is_pk=bool(r["pk"]),
                    )
                    for r in cursor.fetchall()
                ]

                category = resolve_category_for_table(name)
                catalog.append(
                    TableCatalogMeta(
                        table_name=name,
                        category=category,
                        row_count=cnt,
                        columns=cols,
                        has_data=(cnt > 0),
                        description=f"{category.label_ja} に分類されるレコードテーブル",
                    )
                )
        return catalog

    def fetch_table_rows(
        self,
        table_name: str,
        limit: int = 100,
        offset: int = 0,
        order_by: str | None = None,
        ascending: bool = True,
    ) -> pd.DataFrame:
        """Fetch paginated rows from specified table as DataFrame.

        Args:
            table_name: Validated table name.
            limit: Maximum rows to return (capped at 5000).
            offset: Offset row index.
            order_by: Optional column name to sort by.
            ascending: Sort direction.

        Returns:
            pandas DataFrame containing requested slice of records.
        """
        self._validate_table_name(table_name)
        safe_limit = max(1, min(limit, 5000))
        safe_offset = max(0, offset)

        cols = [c.name for c in self.get_table_columns(table_name)]

        order_clause = ""
        if order_by and order_by in cols:
            direction = "ASC" if ascending else "DESC"
            order_clause = f'ORDER BY "{order_by}" {direction}'

        query = f'SELECT * FROM "{table_name}" {order_clause} LIMIT ? OFFSET ?;'
        with self._get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=(safe_limit, safe_offset))
            # Format any bytes/blob columns to readable representation
            for col in df.columns:
                if df[col].dtype == object and len(df) > 0:
                    sample = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
                    if isinstance(sample, bytes):
                        df[col] = df[col].apply(
                            lambda b: f"<BLOB: {len(b)} bytes>" if isinstance(b, bytes) else b
                        )
            return df

    def execute_query(
        self,
        query: str,
        params: Sequence[Any] = (),
    ) -> pd.DataFrame:
        """Execute read-only SQL query with parameter binding.

        Args:
            query: SQL SELECT query statement.
            params: Sequence of parameter arguments.

        Returns:
            pandas DataFrame result.

        Raises:
            ValueError: If query is not a read-only query.
        """
        normalized = query.strip().upper()
        if not (
            normalized.startswith("SELECT")
            or normalized.startswith("PRAGMA")
            or normalized.startswith("WITH")
        ):
            raise ValueError(
                "読み取り専用エンジンでは SELECT/PRAGMA/WITH 以外のステートメントは実行できません。"
            )

        with self._get_connection() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def _validate_table_name(self, table_name: str) -> None:
        """Verify table exists in database to prevent SQL injection.

        Args:
            table_name: Table name string to check.

        Raises:
            TableNotFoundError: If table name is not in database.
        """
        all_tables = self.get_all_table_names()
        if table_name not in all_tables:
            raise TableNotFoundError(f"テーブル「{table_name}」はデータベースに存在しません。")

    @staticmethod
    def epoch_millis_to_dt(millis: int | float | None) -> datetime | None:
        """Convert epoch milliseconds timestamp to UTC datetime."""
        if millis is None or pd.isna(millis):
            return None
        try:
            return datetime.fromtimestamp(float(millis) / 1000.0, tz=UTC)
        except ValueError, OSError, OverflowError:
            return None

    @staticmethod
    def build_time_filter_clause(
        column_name: str,
        filters: DashboardFilterParams,
    ) -> tuple[str, list[Any]]:
        """Construct WHERE clause fragment for timestamp filtering in epoch milliseconds.

        Args:
            column_name: SQL column storing epoch millis.
            filters: Active dashboard filter parameters.

        Returns:
            Tuple of (SQL clause string, parameters list).
        """
        clauses: list[str] = []
        params: list[Any] = []

        if filters.start_date is not None:
            # Start of day in UTC epoch millis
            start_dt = datetime.combine(filters.start_date, datetime.min.time(), tzinfo=UTC)
            start_ms = int(start_dt.timestamp() * 1000)
            clauses.append(f'"{column_name}" >= ?')
            params.append(start_ms)

        if filters.end_date is not None:
            # End of day in UTC epoch millis
            end_dt = datetime.combine(filters.end_date, datetime.max.time(), tzinfo=UTC)
            end_ms = int(end_dt.timestamp() * 1000)
            clauses.append(f'"{column_name}" <= ?')
            params.append(end_ms)

        if not clauses:
            return "", []

        return " AND " + " AND ".join(clauses), params
