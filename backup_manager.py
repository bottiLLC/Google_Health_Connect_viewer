from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import structlog

_ROOT: Final[Path] = Path(__file__).resolve().parent
_CONFIG_FILE: Final[Path] = _ROOT / "data" / "backup_config.json"
_DEFAULT_BACKUP_DIR: Final[Path] = _ROOT / "backups"

logger = structlog.get_logger(__name__)


def get_backup_dir() -> Path:
    """Resolve active backup directory from config, env, or default."""
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
                custom_path = data.get("backup_dir")
                if isinstance(custom_path, str) and custom_path:
                    return Path(custom_path).resolve()
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "failed_to_read_backup_config", config_file=str(_CONFIG_FILE), error=str(e)
            )

    env_dir = os.getenv("BACKUP_DIR")
    if env_dir:
        return Path(env_dir).resolve()

    return _DEFAULT_BACKUP_DIR.resolve()


def set_backup_dir(target_dir: str) -> dict[str, str | bool]:
    """Validate and persist target backup directory path."""
    path = Path(target_dir).resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"backup_dir": str(path)}, f, indent=2)
        logger.info("backup_dir_updated", new_dir=str(path))
        return {"success": True, "message": f"バックアップ先を設定しました: {path!s}"}
    except OSError as e:
        logger.error("failed_to_set_backup_dir", target_dir=target_dir, error=str(e))
        return {
            "success": False,
            "message": f"保存先パスが無効、または書き込み権限がありません: {e!s}",
        }


def run_backup(
    app_name: str = "app", source_dir: Path | str | None = None
) -> dict[str, str | bool]:
    """Create atomic, integrity-verified ZIP archive of ./data directory."""
    source_path = Path(source_dir).resolve() if source_dir else (_ROOT / "data").resolve()
    now = datetime.now(UTC).astimezone()
    ts_display = now.strftime("%Y-%m-%d %H:%M:%S")

    # 1. Source presence verification
    if not source_path.exists() or not any(source_path.iterdir()):
        logger.warning("backup_aborted_source_empty", source_path=str(source_path))
        return {
            "success": False,
            "message": f"バックアップ対象が存在しないか空欄です: {source_path!s}",
            "timestamp": ts_display,
        }

    # 2. Destination directory resolution and creation
    backup_dir = get_backup_dir()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("backup_dir_creation_failed", backup_dir=str(backup_dir), error=str(e))
        return {
            "success": False,
            "message": f"保存先フォルダの作成に失敗しました: {e!s}",
            "timestamp": ts_display,
        }

    zip_filename = f"{app_name}_backup_{now.strftime('%Y%m%d_%H%M%S')}.zip"
    final_destination = backup_dir / zip_filename

    # 3. Atomic processing in temporary directory
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_zip = Path(tmp_dir) / zip_filename
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in source_path.rglob("*"):
                # Exclude backup configuration file itself from archive
                if file_path.is_file() and file_path.resolve() != _CONFIG_FILE.resolve():
                    zipf.write(file_path, file_path.relative_to(source_path))

        # 4. Integrity check (testzip)
        with zipfile.ZipFile(tmp_zip, "r") as zipf:
            corrupt = zipf.testzip()
            if corrupt is not None:
                logger.error("backup_integrity_check_failed", corrupt_member=corrupt)
                return {
                    "success": False,
                    "message": f"整合性チェック失敗（破損検知）: {corrupt}",
                    "timestamp": ts_display,
                }

        # 5. Atomic move to target destination
        file_size = tmp_zip.stat().st_size
        try:
            shutil.move(str(tmp_zip), str(final_destination))
        except OSError as e:
            logger.error(
                "backup_destination_move_failed", destination=str(final_destination), error=str(e)
            )
            return {
                "success": False,
                "message": f"バックアップファイルの確定移動に失敗しました: {e!s}",
                "timestamp": ts_display,
            }

    size_str = (
        f"{file_size / (1024 * 1024):.2f} MB"
        if file_size >= 1024 * 1024
        else f"{file_size / 1024:.2f} KB"
    )

    logger.info(
        "backup_completed", filename=zip_filename, size=size_str, destination=str(final_destination)
    )
    return {
        "success": True,
        "filename": zip_filename,
        "size": size_str,
        "destination": str(final_destination),
        "timestamp": ts_display,
        "message": f"バックアップ完了: {zip_filename} ({size_str})",
    }
