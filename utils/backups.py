"""Managed ZIP backup and restore helpers for EnvsBot."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.config import BASE_DIR, config, get_runtime_config_path
from utils.version import __version__

log = logging.getLogger(__name__)

BACKUP_PREFIX = "envsbot-backup"
MANIFEST_NAME = "manifest.json"
RESTORE_ENTRIES = ("bot.db", "config.py", "vcard.py", "chat_slang.csv")


class BackupError(Exception):
    """Raised when a managed backup or restore operation fails."""


@dataclass(frozen=True)
class BackupArchive:
    """Small listing entry for one backup archive."""

    path: Path
    name: str
    size: int
    created_at: str
    reason: str
    files: list[str]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().isoformat(timespec="seconds")


def _safe_reason(reason: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(reason or "manual").strip().lower())
    cleaned = cleaned.strip("-") or "manual"
    return cleaned[:40]


def _resolve_path(path_value: str | os.PathLike[str]) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def backup_dir() -> Path:
    """Return the configured managed backup directory."""
    return _resolve_path(config.get("backup_dir", "data/backups"))


def backup_keep() -> int:
    """Return the configured backup retention count."""
    try:
        return max(1, int(config.get("backup_keep", 15)))
    except Exception:
        return 15


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_name(reason: str) -> str:
    timestamp = _now().strftime("%Y%m%d-%H%M%S")
    return f"{BACKUP_PREFIX}-{timestamp}-{_safe_reason(reason)}.zip"


def _source_items(db_path: Path) -> list[tuple[str, Path]]:
    config_path = get_runtime_config_path()
    config_arcname = "config.py" if config_path.suffix.lower() == ".py" else config_path.name
    return [
        ("bot.db", db_path),
        (config_arcname, config_path),
        ("vcard.py", BASE_DIR / "vcard.py"),
        ("chat_slang.csv", BASE_DIR / "chat_slang.csv"),
    ]


async def _maybe_await(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


async def _flush_database(bot: Any) -> None:
    db = getattr(bot, "db", None)
    flush = getattr(db, "flush", None)
    if callable(flush):
        await _maybe_await(flush())


async def _write_database_snapshot(bot: Any, source_path: Path, archive: zipfile.ZipFile) -> dict[str, Any]:
    """Write a consistent database snapshot to ``archive`` as ``bot.db``."""
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    await _flush_database(bot)
    db = getattr(bot, "db", None)
    conn = getattr(db, "conn", None)
    backup_method = getattr(conn, "backup", None)

    with tempfile.TemporaryDirectory(prefix="envsbot-backup-") as tmpdir:
        tmp_db = Path(tmpdir) / "bot.db"
        if callable(backup_method):
            target = sqlite3.connect(tmp_db)
            try:
                await _maybe_await(backup_method(target))
            finally:
                target.close()
        else:
            shutil.copy2(source_path, tmp_db)

        archive.write(tmp_db, "bot.db")
        return {
            "name": "bot.db",
            "source": str(source_path),
            "size": tmp_db.stat().st_size,
            "sha256": _sha256(tmp_db),
        }


def _write_file(path: Path, arcname: str, archive: zipfile.ZipFile) -> dict[str, Any]:
    archive.write(path, arcname)
    return {
        "name": arcname,
        "source": str(path),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


async def create_backup(bot: Any, *, reason: str = "manual", prune: bool = True) -> Path:
    """Create a managed ZIP backup and return its archive path."""
    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)

    db_path = _resolve_path(config.get("db", "bot.db"))
    archive_path = directory / _archive_name(reason)
    manifest: dict[str, Any] = {
        "app": "envsbot",
        "version": __version__,
        "created_at": _iso_now(),
        "reason": reason,
        "files": [],
        "missing": [],
    }

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arcname, source_path in _source_items(db_path):
            try:
                if arcname == "bot.db":
                    item = await _write_database_snapshot(bot, source_path, archive)
                else:
                    if not source_path.exists():
                        raise FileNotFoundError(source_path)
                    item = _write_file(source_path, arcname, archive)
                manifest["files"].append(item)
            except FileNotFoundError:
                manifest["missing"].append({"name": arcname, "source": str(source_path)})

        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True))

    if prune:
        prune_old_backups(directory=directory, keep=backup_keep())
    return archive_path


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            with archive.open(MANIFEST_NAME) as handle:
                data = json.load(handle)
    except KeyError as exc:
        raise BackupError(f"Backup archive has no {MANIFEST_NAME}: {path.name}") from exc
    except Exception as exc:
        raise BackupError(f"Could not read backup manifest {path.name}: {exc}") from exc

    if not isinstance(data, dict) or data.get("app") != "envsbot":
        raise BackupError(f"Backup archive is not an EnvsBot backup: {path.name}")
    return data


def list_backups(*, directory: Path | None = None) -> list[BackupArchive]:
    """List managed backup archives newest first."""
    directory = directory or backup_dir()
    if not directory.exists():
        return []

    items: list[BackupArchive] = []
    for path in sorted(directory.glob(f"{BACKUP_PREFIX}-*.zip"), reverse=True):
        try:
            manifest = _read_manifest(path)
            files = [item.get("name", "?") for item in manifest.get("files", [])]
            created_at = str(manifest.get("created_at") or "unknown")
            reason = str(manifest.get("reason") or "unknown")
        except BackupError:
            files = []
            created_at = "unknown"
            reason = "unreadable"
        items.append(
            BackupArchive(
                path=path,
                name=path.name,
                size=path.stat().st_size,
                created_at=created_at,
                reason=reason,
                files=files,
            )
        )
    return items


def prune_old_backups(*, directory: Path | None = None, keep: int | None = None) -> list[Path]:
    """Remove old managed backup archives and return deleted paths."""
    directory = directory or backup_dir()
    keep = backup_keep() if keep is None else max(1, int(keep))
    archives = list_backups(directory=directory)
    removed: list[Path] = []
    for archive in archives[keep:]:
        try:
            archive.path.unlink()
            removed.append(archive.path)
        except FileNotFoundError:
            continue
    return removed


def resolve_backup(name: str) -> Path:
    """Resolve a user-provided backup name to a managed archive path."""
    value = (name or "").strip()
    if not value:
        raise BackupError("Missing backup archive name.")

    archives = list_backups()
    if value == "last":
        if not archives:
            raise BackupError("No backups found.")
        return archives[0].path

    if "/" in value or "\\" in value or value in {".", ".."}:
        raise BackupError("Backup name must not contain path separators.")

    candidates = {archive.name: archive.path for archive in archives}
    if not value.endswith(".zip"):
        value = f"{value}.zip"
    try:
        return candidates[value]
    except KeyError as exc:
        raise BackupError(f"Backup not found: {value}") from exc


def backup_details(path: Path) -> dict[str, Any]:
    """Return manifest and archive metadata for one backup."""
    manifest = _read_manifest(path)
    return {
        "name": path.name,
        "path": str(path),
        "size": path.stat().st_size,
        "manifest": manifest,
    }


def _target_paths() -> dict[str, Path]:
    config_path = get_runtime_config_path()
    if config_path.suffix.lower() != ".py" and not os.environ.get("ENVSBOT_CONFIG"):
        config_path = BASE_DIR / "config.py"
    return {
        "bot.db": _resolve_path(config.get("db", "bot.db")),
        "config.py": config_path,
        "config.json": config_path,
        "vcard.py": BASE_DIR / "vcard.py",
        "chat_slang.csv": BASE_DIR / "chat_slang.csv",
    }


def _safe_members(archive: zipfile.ZipFile) -> set[str]:
    names = set()
    for info in archive.infolist():
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts:
            raise BackupError(f"Unsafe archive entry: {name}")
        names.add(name)
    return names


def _restore_entry(archive: zipfile.ZipFile, entry: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        with archive.open(entry) as source:
            shutil.copyfileobj(source, tmp)
    os.replace(tmp_path, target)


async def _close_database(bot: Any) -> bool:
    db = getattr(bot, "db", None)
    close = getattr(db, "close", None)
    if not callable(close):
        return False
    await _maybe_await(close())
    return True


async def _connect_database(bot: Any) -> None:
    db = getattr(bot, "db", None)
    connect = getattr(db, "connect", None)
    if callable(connect):
        await _maybe_await(connect())


async def restore_backup(bot: Any, archive_path: Path) -> dict[str, Any]:
    """Restore managed backup entries and reconnect the database when possible."""
    archive_path = archive_path.resolve()
    manifest = _read_manifest(archive_path)
    # Do not prune while the selected archive is still needed for restore.
    safety_backup = await create_backup(bot, reason="restore-safety", prune=False)

    restored: list[str] = []
    closed_db = False
    try:
        closed_db = await _close_database(bot)
        targets = _target_paths()
        with zipfile.ZipFile(archive_path) as archive:
            members = _safe_members(archive)
            for entry in RESTORE_ENTRIES:
                if entry not in members:
                    continue
                _restore_entry(archive, entry, targets[entry])
                restored.append(entry)
        if closed_db:
            await _connect_database(bot)
        prune_old_backups()
    except Exception:
        if closed_db:
            try:
                await _connect_database(bot)
            except Exception:
                log.debug("[BACKUP] Failed to reconnect database after restore error", exc_info=True)
        raise

    return {
        "archive": archive_path.name,
        "manifest": manifest,
        "restored": restored,
        "safety_backup": safety_backup.name,
    }
