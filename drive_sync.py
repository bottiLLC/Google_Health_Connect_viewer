"""Google Drive API client for Google Health Connect SQLite export synchronization."""

from __future__ import annotations

import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.http import MediaIoBaseDownload

from domain_models import DriveFileMeta

_SQLITE_HEADER: Final[bytes] = b"SQLite format 3\x00"
_SCOPES: Final[list[str]] = ["https://www.googleapis.com/auth/drive.readonly"]
_ROOT: Final[Path] = Path(__file__).resolve().parent
_DATA_DIR: Final[Path] = _ROOT / "data"
_CREDENTIALS_FILE: Final[Path] = _DATA_DIR / "credentials.json"
_TOKEN_FILE: Final[Path] = _DATA_DIR / "token.json"


class DriveSyncError(Exception):
    """Base exception for Google Drive synchronization errors."""


class DriveAuthError(DriveSyncError):
    """Raised when OAuth credentials cannot be loaded or authenticated."""


class DriveFileNotFoundError(DriveSyncError):
    """Raised when no valid SQLite export file is found in target Google Drive folder."""


def is_sqlite_database_file(file_path: Path) -> bool:
    """ファイルの先頭 16 バイトのマジックナンバーを検証して SQLite DB かを判定する。"""
    if not file_path.is_file() or file_path.stat().st_size < 16:
        return False
    try:
        with open(file_path, "rb") as f:
            return f.read(16) == _SQLITE_HEADER
    except OSError:
        return False


def extract_sqlite_from_zip(zip_path: Path, extract_dir: Path) -> Path:
    """ZIP アーカイブを完全性検証し、内部の SQLite データベースファイルを特定・展開する。

    Args:
        zip_path: ダウンロードされた ZIP ファイルのパス。
        extract_dir: 展開先の一時作業ディレクトリ。

    Returns:
        展開された SQLite ファイルの絶対パス。

    Raises:
        DriveSyncError: ZIP が破損している場合。
        DriveFileNotFoundError: ZIP 内に有効な SQLite ファイルが存在しない場合。
    """
    if not zipfile.is_zipfile(zip_path):
        raise DriveSyncError(f"指定ファイルは有効な ZIP アーカイブではありません: {zip_path.name}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        corrupted = zf.testzip()
        if corrupted is not None:
            raise DriveSyncError(f"ZIP アーカイブの破損を検知しました (破損エントリ: {corrupted})")

        # 1. 拡張子 .db / .sqlite による優先探索
        candidate_entry: str | None = None
        for name in zf.namelist():
            lower_name = name.lower()
            if not lower_name.endswith("/") and (
                lower_name.endswith(".db") or lower_name.endswith(".sqlite")
            ):
                candidate_entry = name
                break

        # 2. 拡張子で見つからない場合は先頭マジックナンバーによる全件検証
        if candidate_entry is None:
            for name in zf.namelist():
                info = zf.getinfo(name)
                if not info.is_dir() and info.file_size >= 16:
                    with zf.open(name) as member_file:
                        if member_file.read(16) == _SQLITE_HEADER:
                            candidate_entry = name
                            break

        if candidate_entry is None:
            raise DriveFileNotFoundError(
                f"ZIP アーカイブ ({zip_path.name}) 内に有効な SQLite ファイルが見つかりません。"
            )

        extracted_path = Path(zf.extract(candidate_entry, path=str(extract_dir))).resolve()
        return extracted_path


class GoogleDriveSyncClient:
    """Client for authenticating, discovering, and downloading SQLite exports from Google Drive."""

    def __init__(
        self,
        credentials_path: Path = _CREDENTIALS_FILE,
        token_path: Path = _TOKEN_FILE,
    ) -> None:
        """Initialize Drive sync client with deterministic credential paths.

        Args:
            credentials_path: Path to OAuth2 client secrets JSON file.
            token_path: Path to cached token JSON file.
        """
        self._credentials_path = credentials_path
        self._token_path = token_path

    @property
    def credentials_path(self) -> Path:
        """Return resolved path to OAuth credentials file."""
        return self._credentials_path

    @property
    def token_path(self) -> Path:
        """Return resolved path to OAuth token file."""
        return self._token_path

    def has_credentials(self) -> bool:
        """Check if OAuth client secrets file exists on disk."""
        return self._credentials_path.is_file()

    def has_token(self) -> bool:
        """Check if cached OAuth token file exists on disk."""
        return self._token_path.is_file()

    def authenticate(self, local_server_timeout: int = 120) -> Credentials:
        """Authenticate user with Google Drive API, refreshing or running local OAuth flow.

        Args:
            local_server_timeout: Timeout in seconds for waiting on browser authentication callback.

        Returns:
            Authorized google.oauth2.credentials.Credentials instance.

        Raises:
            DriveAuthError: If credentials.json is missing or authentication fails.
        """
        creds: Credentials | None = None

        if self._token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                    str(self._token_path), _SCOPES
                )
            except Exception:
                # Corrupted or incompatible token file
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())  # type: ignore[no-untyped-call]
                except Exception:
                    creds = None

            if not creds:
                if not self._credentials_path.exists():
                    raise DriveAuthError(
                        f"OAuth認証情報ファイルが見つかりません: {self._credentials_path}\n"
                        "Google Cloud Console からダウンロードした credentials.json を ./data/ 配下に配置してください。"
                    )
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self._credentials_path), _SCOPES
                    )
                    creds = flow.run_local_server(
                        port=0,
                        timeout_seconds=local_server_timeout,
                    )
                except Exception as e:
                    raise DriveAuthError(f"Google Drive OAuth認証に失敗しました: {e!s}") from e

            # Persist fresh token
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._token_path, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())

        return creds

    def get_drive_service(self) -> Resource:
        """Build and return authorized Google Drive v3 Resource service.

        Returns:
            Google Drive API v3 service resource.
        """
        creds = self.authenticate()
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def find_latest_backup_file(self, folder_id: str) -> DriveFileMeta:
        """Find the most recently modified backup file (ZIP or SQLite) in specified Google Drive folder.

        Args:
            folder_id: Google Drive target folder identifier string.

        Returns:
            DriveFileMeta for the latest backup file.

        Raises:
            ValueError: If folder_id is empty.
            DriveFileNotFoundError: If no candidate file is found.
            DriveSyncError: If Drive API call fails.
        """
        clean_folder_id = folder_id.strip()
        if not clean_folder_id:
            raise ValueError("Google Drive フォルダ ID が指定されていません。")

        service = self.get_drive_service()
        # Query for non-trashed files inside specified parent folder
        query = f"'{clean_folder_id}' in parents and trashed = false"

        try:
            results: dict[str, Any] = (
                service.files()
                .list(
                    q=query,
                    orderBy="modifiedTime desc",
                    pageSize=20,
                    fields="files(id, name, modifiedTime, size, mimeType)",
                )
                .execute()
            )
        except Exception as e:
            raise DriveSyncError(f"Google Drive フォルダ走査に失敗しました: {e!s}") from e

        files: list[dict[str, Any]] = results.get("files", [])
        if not files:
            raise DriveFileNotFoundError(
                f"指定フォルダ (ID: {clean_folder_id}) 内にファイルが見つかりません。"
            )

        # Filter candidate backup files: prefer .zip, .db, .sqlite or matching mimeTypes
        candidate: dict[str, Any] | None = None
        for file_item in files:
            name = str(file_item.get("name", "")).lower()
            mime = str(file_item.get("mimeType", "")).lower()
            if (
                name.endswith(".zip")
                or "zip" in mime
                or name.endswith(".db")
                or name.endswith(".sqlite")
                or "sqlite" in mime
            ):
                candidate = file_item
                break

        if candidate is None:
            # Fallback to the latest file in folder
            candidate = files[0]

        file_id = str(candidate["id"])
        name = str(candidate["name"])
        raw_mtime = str(candidate.get("modifiedTime", ""))
        size_bytes = int(candidate.get("size", 0))

        # Parse RFC 3339 datetime
        try:
            mtime_dt = datetime.fromisoformat(raw_mtime.replace("Z", "+00:00"))
        except ValueError:
            mtime_dt = datetime.now(UTC)

        return DriveFileMeta(
            file_id=file_id,
            name=name,
            modified_time=mtime_dt,
            size_bytes=size_bytes,
        )

    def find_latest_sqlite_file(self, folder_id: str) -> DriveFileMeta:
        """Find the latest backup file (backward-compatible delegate to find_latest_backup_file)."""
        return self.find_latest_backup_file(folder_id)

    @contextmanager
    def download_and_extract_db(self, file_id: str, file_name: str = "") -> Iterator[Path]:
        """Download remote Google Drive file and extract inner SQLite DB if compressed as ZIP.

        Args:
            file_id: Remote Google Drive file identifier.
            file_name: Optional file name for logging / extension hint.

        Yields:
            Path to downloaded (or extracted) valid SQLite database file.
        """
        service = self.get_drive_service()
        request = service.files().get_media(fileId=file_id)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            # Retain extension hint if available
            raw_suffix = ".zip" if file_name.lower().endswith(".zip") else ".download"
            raw_path = tmp_root / f"raw_export{raw_suffix}"

            with open(raw_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            # Inspect if downloaded payload is a ZIP archive
            if zipfile.is_zipfile(raw_path):
                extract_target_dir = tmp_root / "extracted"
                extract_target_dir.mkdir(parents=True, exist_ok=True)
                extracted_db_path = extract_sqlite_from_zip(raw_path, extract_target_dir)
                yield extracted_db_path
            else:
                # Direct SQLite file or non-compressed file
                yield raw_path

    @contextmanager
    def download_file_to_temp(self, file_id: str) -> Iterator[Path]:
        """Download remote Google Drive file (backward-compatible delegate)."""
        with self.download_and_extract_db(file_id) as p:
            yield p
