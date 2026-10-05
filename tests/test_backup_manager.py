from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from backup_manager import get_backup_dir, run_backup, set_backup_dir


def test_get_backup_dir_default_when_no_config(tmp_path: Path) -> None:
    """Ensure fallback to default ./backups when config and env are absent."""
    with (
        patch("backup_manager._CONFIG_FILE", tmp_path / "non_existent.json"),
        patch.dict("os.environ", {}, clear=True),
    ):
        res = get_backup_dir()
        assert res == Path("./backups").resolve()


def test_get_backup_dir_from_config(tmp_path: Path) -> None:
    """Ensure get_backup_dir resolves path defined in backup_config.json."""
    config_file = tmp_path / "backup_config.json"
    target_dir = tmp_path / "custom_backups"
    config_file.write_text(json.dumps({"backup_dir": str(target_dir)}), encoding="utf-8")

    with patch("backup_manager._CONFIG_FILE", config_file):
        res = get_backup_dir()
        assert res == target_dir.resolve()


def test_get_backup_dir_from_env_var(tmp_path: Path) -> None:
    """Ensure get_backup_dir falls back to BACKUP_DIR environment variable."""
    target_dir = tmp_path / "env_backups"
    with (
        patch("backup_manager._CONFIG_FILE", tmp_path / "non_existent.json"),
        patch.dict("os.environ", {"BACKUP_DIR": str(target_dir)}),
    ):
        res = get_backup_dir()
        assert res == target_dir.resolve()


def test_set_backup_dir_success(tmp_path: Path) -> None:
    """Verify set_backup_dir successfully updates config file and creates directory."""
    config_file = tmp_path / "data" / "backup_config.json"
    target_dir = tmp_path / "new_dest"

    with patch("backup_manager._CONFIG_FILE", config_file):
        res = set_backup_dir(str(target_dir))
        assert res["success"] is True
        assert "バックアップ先を設定しました" in str(res["message"])
        assert target_dir.exists()
        assert config_file.exists()


def test_set_backup_dir_os_error(tmp_path: Path) -> None:
    """Verify set_backup_dir handles filesystem permission errors gracefully."""
    config_file = tmp_path / "data" / "backup_config.json"
    with (
        patch("backup_manager._CONFIG_FILE", config_file),
        patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")),
    ):
        res = set_backup_dir(str(tmp_path / "forbidden"))
        assert res["success"] is False
        assert "保存先パスが無効、または書き込み権限がありません" in str(res["message"])


def test_run_backup_source_empty(tmp_path: Path) -> None:
    """Verify run_backup aborts safely when source directory is empty or nonexistent."""
    empty_src = tmp_path / "empty_dir"
    empty_src.mkdir()

    res = run_backup(source_dir=str(empty_src))
    assert res["success"] is False
    assert "バックアップ対象が存在しないか空欄です" in str(res["message"])


def test_run_backup_success(tmp_path: Path) -> None:
    """Verify run_backup creates valid atomic zip archive and passes testzip."""
    src_dir = tmp_path / "data"
    src_dir.mkdir()
    (src_dir / "sample.db").write_bytes(b"SQLite format 3\x00dummy data")
    (src_dir / "subfolder").mkdir()
    (src_dir / "subfolder" / "nested.txt").write_text("hello", encoding="utf-8")
    config_file = src_dir / "backup_config.json"
    config_file.write_text("{}", encoding="utf-8")

    dest_dir = tmp_path / "backups"

    with (
        patch("backup_manager._CONFIG_FILE", config_file),
        patch("backup_manager.get_backup_dir", return_value=dest_dir),
    ):
        res = run_backup(app_name="health_viewer", source_dir=str(src_dir))

        assert res["success"] is True
        assert "バックアップ完了" in str(res["message"])
        dest_file = Path(str(res["destination"]))
        assert dest_file.exists()

        # Verify integrity and exclusion of backup_config.json
        with zipfile.ZipFile(dest_file, "r") as zf:
            assert zf.testzip() is None
            names = zf.namelist()
            assert "sample.db" in names
            assert "subfolder/nested.txt" in names
            assert "backup_config.json" not in names


def test_run_backup_integrity_failure(tmp_path: Path) -> None:
    """Verify run_backup detects corrupted zip archive during testzip check."""
    src_dir = tmp_path / "data"
    src_dir.mkdir()
    (src_dir / "sample.db").write_bytes(b"dummy")

    dest_dir = tmp_path / "backups"

    with (
        patch("backup_manager.get_backup_dir", return_value=dest_dir),
        patch("zipfile.ZipFile.testzip", return_value="sample.db"),
    ):
        res = run_backup(app_name="health_viewer", source_dir=str(src_dir))
        assert res["success"] is False
        assert "整合性チェック失敗（破損検知）" in str(res["message"])
