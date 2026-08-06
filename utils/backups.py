"""Managed ZIP backup and restore helpers for EnvsBot."""

from __future__ import annotations

import asyncio
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
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from utils.config import BASE_DIR, config, get_runtime_config_path
from utils.file_security import (
    PRIVATE_FILE_MODE,
    ensure_private_directory,
    ensure_private_file,
)
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


def backup_retention_days() -> int:
    """Return age-based backup retention in days, or 0 when disabled."""
    try:
        return max(0, int(config.get("backup_retention_days", 0) or 0))
    except Exception:
        return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_name(reason: str) -> str:
    timestamp = _now().strftime("%Y%m%d-%H%M%S-%f")
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


async def _create_database_snapshot(bot: Any, source_path: Path, target_path: Path) -> None:
    """Create a consistent database snapshot before archive compression."""
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    await _flush_database(bot)
    db = getattr(bot, "db", None)
    conn = getattr(db, "conn", None)
    backup_method = getattr(conn, "backup", None)

    if callable(backup_method):
        target = sqlite3.connect(target_path)
        try:
            await _maybe_await(backup_method(target))
        finally:
            target.close()
    else:
        await asyncio.to_thread(shutil.copy2, source_path, target_path)


def _write_file(
    path: Path,
    arcname: str,
    archive: zipfile.ZipFile,
    *,
    source_path: Path | None = None,
) -> dict[str, Any]:
    """Compress and hash one file inside the backup worker thread."""
    archive.write(path, arcname)
    return {
        "name": arcname,
        "source": str(source_path or path),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _build_backup_archive(
    tmp_path: Path,
    archive_path: Path,
    directory: Path,
    manifest: dict[str, Any],
    source_items: list[tuple[str, Path, Path]],
) -> None:
    """Build, verify and publish an archive outside the XMPP event loop."""
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for arcname, archive_source, original_source in source_items:
                try:
                    if not archive_source.exists():
                        raise FileNotFoundError(original_source)
                    item = _write_file(
                        archive_source,
                        arcname,
                        archive,
                        source_path=original_source,
                    )
                    manifest["files"].append(item)
                except FileNotFoundError:
                    manifest["missing"].append(
                        {"name": arcname, "source": str(original_source)}
                    )

            archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True))

        with zipfile.ZipFile(tmp_path) as archive:
            if archive.testzip() is not None:
                raise BackupError("new backup archive failed CRC verification")
            if MANIFEST_NAME not in archive.namelist():
                raise BackupError("new backup archive has no manifest")
        with tmp_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp_path, archive_path)
        ensure_private_file(archive_path)
        with suppress(OSError):
            dir_fd = os.open(directory, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


async def create_backup(bot: Any, *, reason: str = "manual", prune: bool = True) -> Path:
    """Create a managed ZIP backup and return its archive path."""
    directory = ensure_private_directory(backup_dir())

    db_path = _resolve_path(config.get("db", "bot.db"))
    archive_path = directory / _archive_name(reason)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{archive_path.name}.",
        suffix=".tmp",
        dir=directory,
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    os.chmod(tmp_path, PRIVATE_FILE_MODE)
    manifest: dict[str, Any] = {
        "app": "envsbot",
        "version": __version__,
        "created_at": _iso_now(),
        "reason": reason,
        "files": [],
        "missing": [],
    }

    try:
        with tempfile.TemporaryDirectory(prefix="envsbot-backup-") as tmpdir:
            db_snapshot = Path(tmpdir) / "bot.db"
            if db_path.exists():
                await _create_database_snapshot(bot, db_path, db_snapshot)

            archive_sources: list[tuple[str, Path, Path]] = []
            for arcname, original_source in _source_items(db_path):
                archive_source = db_snapshot if arcname == "bot.db" else original_source
                archive_sources.append((arcname, archive_source, original_source))

            await asyncio.to_thread(
                _build_backup_archive,
                tmp_path,
                archive_path,
                directory,
                manifest,
                archive_sources,
            )
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    if prune:
        try:
            await asyncio.to_thread(
                prune_old_backups,
                directory=directory,
                keep=backup_keep(),
            )
        except Exception:
            log.exception(
                "[BACKUP] archive=%s status=created prune_status=failed",
                archive_path.name,
            )
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


def _parse_archive_created_at(value: str | None) -> datetime | None:
    """Parse a manifest timestamp into an aware UTC datetime if possible."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def plan_backup_prune(
    *,
    directory: Path | None = None,
    keep: int | None = None,
    days: int | None = None,
) -> list[BackupArchive]:
    """Return managed archives that would be removed by retention policy."""
    directory = directory or backup_dir()
    keep = backup_keep() if keep is None else max(1, int(keep))
    days = backup_retention_days() if days is None else max(0, int(days))
    archives = list_backups(directory=directory)

    selected: dict[Path, BackupArchive] = {}
    for archive in archives[keep:]:
        selected[archive.path] = archive

    if days > 0:
        cutoff = _now() - timedelta(days=days)
        for archive in archives:
            created_at = _parse_archive_created_at(archive.created_at)
            if created_at is not None and created_at < cutoff:
                selected[archive.path] = archive

    # Preserve newest-first listing order from list_backups().
    return [archive for archive in archives if archive.path in selected]


def prune_old_backups(
    *,
    directory: Path | None = None,
    keep: int | None = None,
    days: int | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """Remove old managed backup archives and return affected paths."""
    planned = plan_backup_prune(directory=directory, keep=keep, days=days)
    if dry_run:
        return [archive.path for archive in planned]

    removed: list[Path] = []
    for archive in planned:
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
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            os.chmod(tmp_path, PRIVATE_FILE_MODE)
            with archive.open(entry) as source:
                shutil.copyfileobj(source, tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
        ensure_private_file(target)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


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


def _restore_archive_entries(archive_path: Path, targets: dict[str, Path]) -> list[str]:
    """Extract managed restore entries in a worker thread."""
    restored: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        members = _safe_members(archive)
        for entry in RESTORE_ENTRIES:
            if entry not in members:
                continue
            _restore_entry(archive, entry, targets[entry])
            restored.append(entry)
    return restored


async def restore_backup(bot: Any, archive_path: Path) -> dict[str, Any]:
    """Restore managed backup entries and reconnect the database when possible."""
    archive_path = archive_path.resolve()
    manifest = await asyncio.to_thread(_read_manifest, archive_path)
    # Do not prune while the selected archive is still needed for restore.
    safety_backup = await create_backup(bot, reason="restore-safety", prune=False)

    restored: list[str] = []
    closed_db = False
    try:
        closed_db = await _close_database(bot)
        targets = _target_paths()
        restored = await asyncio.to_thread(
            _restore_archive_entries,
            archive_path,
            targets,
        )
        if closed_db:
            await _connect_database(bot)
            closed_db = False
        await asyncio.to_thread(prune_old_backups)
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


def _archive_member_sha256(archive: zipfile.ZipFile, name: str) -> str:
    """Hash one archive member without loading a large database into memory."""
    digest = hashlib.sha256()
    with archive.open(name) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(path: Path) -> dict[str, Any]:
    """Verify a managed backup archive manifest and member checksums."""
    path = path.resolve()
    manifest = _read_manifest(path)
    errors: list[str] = []
    files = manifest.get("files", [])
    with zipfile.ZipFile(path) as archive:
        archive_test = archive.testzip()
        if archive_test is not None:
            errors.append(f"zip CRC failed for {archive_test}")
        members = _safe_members(archive)
        for item in files:
            name = str(item.get("name") or "")
            expected = str(item.get("sha256") or "")
            if not name:
                errors.append("manifest file without name")
                continue
            if name not in members:
                errors.append(f"missing archive member: {name}")
                continue
            if expected:
                digest = _archive_member_sha256(archive, name)
                if digest != expected:
                    errors.append(f"checksum mismatch: {name}")
    return {
        "name": path.name,
        "ok": not errors,
        "errors": errors,
        "manifest": manifest,
        "files": [str(item.get("name", "?")) for item in files],
    }


def smoke_test_backup(path: Path) -> dict[str, Any]:
    """Extract the archived database to a temporary location and verify it."""
    path = path.resolve()
    verify = verify_backup(path)
    errors = list(verify.get("errors", []))
    database_result: list[str] = []
    with tempfile.TemporaryDirectory(prefix="envsbot-backup-smoke-") as tmpdir:
        target = Path(tmpdir) / "bot.db"
        with zipfile.ZipFile(path) as archive:
            members = _safe_members(archive)
            if "bot.db" not in members:
                errors.append("backup has no bot.db")
            else:
                _restore_entry(archive, "bot.db", target)
        if target.exists():
            try:
                connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
                try:
                    database_result = [
                        str(row[0])
                        for row in connection.execute("PRAGMA integrity_check;").fetchall()
                    ]
                finally:
                    connection.close()
            except Exception as exc:
                errors.append(f"database open/integrity check failed: {exc}")
            if database_result != ["ok"]:
                errors.append(
                    "database integrity check failed: "
                    + ", ".join(database_result or ["no result"])
                )
    return {
        "name": path.name,
        "ok": not errors,
        "errors": errors,
        "database_integrity": database_result,
    }


def restore_plan(archive_path: Path) -> dict[str, Any]:
    """Return what restore_backup() would restore without writing files."""
    archive_path = archive_path.resolve()
    manifest = _read_manifest(archive_path)
    targets = _target_paths()
    with zipfile.ZipFile(archive_path) as archive:
        members = _safe_members(archive)
        entries = [entry for entry in RESTORE_ENTRIES if entry in members]
    return {
        "archive": archive_path.name,
        "manifest": manifest,
        "entries": entries,
        "targets": {entry: str(targets[entry]) for entry in entries},
    }
