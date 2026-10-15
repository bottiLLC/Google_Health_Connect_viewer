"""Unit tests for Google Drive API synchronization client (drive_sync.py)."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from drive_sync import (
    _SQLITE_HEADER,
    DriveAuthError,
    DriveFileNotFoundError,
    DriveSyncError,
    GoogleDriveSyncClient,
    extract_sqlite_from_zip,
    is_sqlite_database_file,
)


def test_client_properties_and_file_checks() -> None:
    """Verify credentials_path, token_path and file presence predicates."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmp_dir:
        creds_file = Path(tmp_dir) / "credentials.json"
        token_file = Path(tmp_dir) / "token.json"
        client = GoogleDriveSyncClient(credentials_path=creds_file, token_path=token_file)

        # Act & Assert
        assert client.credentials_path == creds_file
        assert client.token_path == token_file
        assert client.has_credentials() is False
        assert client.has_token() is False

        creds_file.write_text("{}", encoding="utf-8")
        token_file.write_text("{}", encoding="utf-8")
        assert client.has_credentials() is True
        assert client.has_token() is True


def test_authenticate_cached_valid_token() -> None:
    """Verify that authenticate returns cached credentials if valid."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmp_dir:
        creds_file = Path(tmp_dir) / "credentials.json"
        token_file = Path(tmp_dir) / "token.json"
        token_file.write_text('{"token": "valid"}', encoding="utf-8")

        mock_creds = MagicMock()
        mock_creds.valid = True

        client = GoogleDriveSyncClient(credentials_path=creds_file, token_path=token_file)

        with patch("drive_sync.Credentials.from_authorized_user_file", return_value=mock_creds):
            # Act
            creds = client.authenticate()

            # Assert
            assert creds == mock_creds


def test_authenticate_token_refresh() -> None:
    """Verify that expired credentials with refresh token trigger refresh and save."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmp_dir:
        creds_file = Path(tmp_dir) / "credentials.json"
        token_file = Path(tmp_dir) / "token.json"
        token_file.write_text('{"token": "expired"}', encoding="utf-8")

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "some_refresh_token"
        mock_creds.to_json.return_value = '{"token": "refreshed"}'

        client = GoogleDriveSyncClient(credentials_path=creds_file, token_path=token_file)

        with patch("drive_sync.Credentials.from_authorized_user_file", return_value=mock_creds):
            # Act
            creds = client.authenticate()

            # Assert
            mock_creds.refresh.assert_called_once()
            assert creds == mock_creds
            assert "refreshed" in token_file.read_text(encoding="utf-8")


def test_authenticate_missing_credentials_raises_auth_error() -> None:
    """Verify that absent credentials.json raises DriveAuthError."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmp_dir:
        creds_file = Path(tmp_dir) / "credentials.json"
        token_file = Path(tmp_dir) / "token.json"
        client = GoogleDriveSyncClient(credentials_path=creds_file, token_path=token_file)

        # Act & Assert
        with pytest.raises(DriveAuthError, match="OAuth認証情報ファイルが見つかりません"):
            client.authenticate()


def test_authenticate_run_local_server_success() -> None:
    """Verify that missing token triggers InstalledAppFlow and persists token."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmp_dir:
        creds_file = Path(tmp_dir) / "credentials.json"
        token_file = Path(tmp_dir) / "token.json"
        creds_file.write_text('{"installed": {}}', encoding="utf-8")

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = '{"token": "newly_authorized"}'

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        client = GoogleDriveSyncClient(credentials_path=creds_file, token_path=token_file)

        with (
            patch("drive_sync.InstalledAppFlow.from_client_secrets_file", return_value=mock_flow),
        ):
            # Act
            creds = client.authenticate(local_server_timeout=30)

            # Assert
            mock_flow.run_local_server.assert_called_once_with(port=0, timeout_seconds=30)
            assert creds == mock_creds
            assert "newly_authorized" in token_file.read_text(encoding="utf-8")


def test_find_latest_sqlite_file_empty_folder_id_raises_value_error() -> None:
    """Verify that empty or whitespace folder_id raises ValueError."""
    # Arrange
    client = GoogleDriveSyncClient()

    # Act & Assert
    with pytest.raises(ValueError, match="Google Drive フォルダ ID が指定されていません"):
        client.find_latest_sqlite_file("   ")


def test_find_latest_sqlite_file_empty_results_raises_not_found() -> None:
    """Verify that empty file list raises DriveFileNotFoundError."""
    # Arrange
    client = GoogleDriveSyncClient()
    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_files.list.return_value.execute.return_value = {"files": []}
    mock_service.files.return_value = mock_files

    with (
        patch.object(client, "get_drive_service", return_value=mock_service),
        pytest.raises(DriveFileNotFoundError, match="ファイルが見つかりません"),
    ):
        client.find_latest_sqlite_file("folder_123")


def test_find_latest_sqlite_file_prefers_db_extension() -> None:
    """Verify that list candidates with .db or sqlite mimeType are prioritized."""
    # Arrange
    client = GoogleDriveSyncClient()
    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_files.list.return_value.execute.return_value = {
        "files": [
            {
                "id": "file_txt",
                "name": "backup.txt",
                "modifiedTime": "2026-10-15T12:00:00Z",
                "size": "500",
                "mimeType": "text/plain",
            },
            {
                "id": "file_db",
                "name": "health_connect_20261015.db",
                "modifiedTime": "2026-10-15T10:00:00Z",
                "size": "1048576",
                "mimeType": "application/x-sqlite3",
            },
        ]
    }
    mock_service.files.return_value = mock_files

    with patch.object(client, "get_drive_service", return_value=mock_service):
        # Act
        meta = client.find_latest_sqlite_file("folder_123")

        # Assert
        assert meta.file_id == "file_db"
        assert meta.name == "health_connect_20261015.db"
        assert meta.size_bytes == 1048576
        assert meta.modified_time.year == 2026


def test_download_file_to_temp() -> None:
    """Verify file download streaming to temporary file and cleanup."""
    # Arrange
    client = GoogleDriveSyncClient()
    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_request = MagicMock()
    mock_files.get_media.return_value = mock_request
    mock_service.files.return_value = mock_files

    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (None, True)

    with (
        patch.object(client, "get_drive_service", return_value=mock_service),
        patch("drive_sync.MediaIoBaseDownload", return_value=mock_downloader),
    ):
        # Act
        temp_file_path: Path | None = None
        with client.download_file_to_temp("file_123") as p:
            temp_file_path = p
            assert temp_file_path.exists()

        # Assert post-context cleanup
        assert not temp_file_path.exists()


def test_is_sqlite_database_file_variants() -> None:
    """Verify is_sqlite_database_file header validation across valid and invalid files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        valid_db = tmp / "valid.db"
        valid_db.write_bytes(_SQLITE_HEADER + b"some database payload data")

        text_file = tmp / "text.txt"
        text_file.write_text("Hello, this is plain text.", encoding="utf-8")

        empty_file = tmp / "empty.db"
        empty_file.write_bytes(b"")

        short_file = tmp / "short.db"
        short_file.write_bytes(b"SQLite")

        assert is_sqlite_database_file(valid_db) is True
        assert is_sqlite_database_file(text_file) is False
        assert is_sqlite_database_file(empty_file) is False
        assert is_sqlite_database_file(short_file) is False
        assert is_sqlite_database_file(tmp / "non_existent.db") is False


def test_extract_sqlite_from_zip_with_db_extension() -> None:
    """Verify extracting SQLite file from ZIP archive by .db extension."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        zip_path = tmp / "backup.zip"
        extract_dir = tmp / "extracted"

        # Create valid zip containing health.db
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.json", '{"version": 1}')
            zf.writestr("health.db", _SQLITE_HEADER + b"payload")

        extracted_file = extract_sqlite_from_zip(zip_path, extract_dir)
        assert extracted_file.exists()
        assert extracted_file.name == "health.db"
        assert extracted_file.read_bytes() == _SQLITE_HEADER + b"payload"


def test_extract_sqlite_from_zip_with_magic_number() -> None:
    """Verify extracting SQLite file without .db extension using magic number detection."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        zip_path = tmp / "backup_no_ext.zip"
        extract_dir = tmp / "extracted"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "Plain instructions")
            zf.writestr("raw_storage_payload", _SQLITE_HEADER + b"sqlite content")

        extracted_file = extract_sqlite_from_zip(zip_path, extract_dir)
        assert extracted_file.exists()
        assert extracted_file.name == "raw_storage_payload"
        assert extracted_file.read_bytes().startswith(_SQLITE_HEADER)


def test_extract_sqlite_from_zip_corrupted_archive() -> None:
    """Verify that a corrupted ZIP raises DriveSyncError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        zip_path = tmp / "corrupted.zip"
        extract_dir = tmp / "extracted"

        # Write truncated/corrupted zip data
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("test.db", _SQLITE_HEADER + b"data")

        # Corrupt the file on disk
        data = bytearray(zip_path.read_bytes())
        data[20:40] = b"\x00" * 20
        zip_path.write_bytes(data)

        with pytest.raises(
            DriveSyncError,
            match="破損を検知しました|指定ファイルは有効な ZIP アーカイブではありません",
        ):
            extract_sqlite_from_zip(zip_path, extract_dir)


def test_extract_sqlite_from_zip_no_sqlite_file() -> None:
    """Verify that a ZIP without SQLite raises DriveFileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        zip_path = tmp / "no_sqlite.zip"
        extract_dir = tmp / "extracted"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "No database inside")
            zf.writestr("data.csv", "a,b,c\n1,2,3")

        with pytest.raises(DriveFileNotFoundError, match="有効な SQLite ファイルが見つかりません"):
            extract_sqlite_from_zip(zip_path, extract_dir)


def test_extract_sqlite_from_zip_not_a_zip() -> None:
    """Verify that passing a non-zip file raises DriveSyncError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        plain_file = tmp / "not_a_zip.txt"
        plain_file.write_text("not a zip", encoding="utf-8")

        with pytest.raises(DriveSyncError, match="有効な ZIP アーカイブではありません"):
            extract_sqlite_from_zip(plain_file, tmp / "extracted")


def test_find_latest_backup_file_prioritizes_zip() -> None:
    """Verify that find_latest_backup_file correctly identifies zip archives as latest backup."""
    client = GoogleDriveSyncClient()
    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_files.list.return_value.execute.return_value = {
        "files": [
            {
                "id": "zip_id_123",
                "name": "HealthConnect_20261016.zip",
                "modifiedTime": "2026-10-16T02:00:00Z",
                "size": "2097152",
                "mimeType": "application/zip",
            },
            {
                "id": "old_db_id",
                "name": "HealthConnect_20261010.db",
                "modifiedTime": "2026-10-10T02:00:00Z",
                "size": "1048576",
                "mimeType": "application/x-sqlite3",
            },
        ]
    }
    mock_service.files.return_value = mock_files

    with patch.object(client, "get_drive_service", return_value=mock_service):
        meta = client.find_latest_backup_file("folder_zip")
        assert meta.file_id == "zip_id_123"
        assert meta.name == "HealthConnect_20261016.zip"
        assert meta.size_bytes == 2097152


def test_download_and_extract_db_with_zip_payload() -> None:
    """Verify download_and_extract_db streams ZIP and returns extracted SQLite path."""
    client = GoogleDriveSyncClient()
    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_request = MagicMock()
    mock_files.get_media.return_value = mock_request
    mock_service.files.return_value = mock_files

    mock_downloader = MagicMock()
    mock_downloader.next_chunk.side_effect = lambda: (None, True)

    with (
        patch.object(client, "get_drive_service", return_value=mock_service),
        patch("drive_sync.MediaIoBaseDownload") as mock_downloader_cls,
    ):

        def fake_downloader_init(fh: Any, req: Any) -> MagicMock:
            with zipfile.ZipFile(fh, "w") as zf:
                zf.writestr("inner_export.db", _SQLITE_HEADER + b"decompressed content")
            return mock_downloader

        mock_downloader_cls.side_effect = fake_downloader_init

        extracted_path: Path | None = None
        with client.download_and_extract_db("file_zip", file_name="export.zip") as p:
            extracted_path = p
            assert extracted_path.exists()
            assert extracted_path.name == "inner_export.db"
            assert extracted_path.read_bytes() == _SQLITE_HEADER + b"decompressed content"

        # Ensure extracted files are wiped after context exit
        assert not extracted_path.exists()


def test_download_and_extract_db_with_raw_db_payload() -> None:
    """Verify download_and_extract_db returns raw file directly if payload is not a ZIP."""
    client = GoogleDriveSyncClient()
    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_request = MagicMock()
    mock_files.get_media.return_value = mock_request
    mock_service.files.return_value = mock_files

    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (None, True)

    with (
        patch.object(client, "get_drive_service", return_value=mock_service),
        patch("drive_sync.MediaIoBaseDownload") as mock_downloader_cls,
    ):

        def fake_raw_downloader_init(fh: Any, req: Any) -> MagicMock:
            fh.write(_SQLITE_HEADER + b"raw database content")
            return mock_downloader

        mock_downloader_cls.side_effect = fake_raw_downloader_init

        raw_path: Path | None = None
        with client.download_and_extract_db("file_raw", file_name="export.db") as p:
            raw_path = p
            assert raw_path.exists()
            assert raw_path.read_bytes() == _SQLITE_HEADER + b"raw database content"

        assert not raw_path.exists()
