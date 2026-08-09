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

from utils.config import config
from utils.config.defaults import BASE_DIR
from utils.config.loader import get_runtime_config_path
from utils.file_security import (
    PRIVATE_FILE_MODE,
    ensure_private_directory,
    ensure_private_file,
)
from utils.version import __version__
from utils.runtime_paths import (
    chat_slang_additions_file,
    chat_slang_file,
    chat_slang_removals_file,
    vcard_file,
)

log = logging.getLogger(__name__)

BACKUP_PREFIX = "envsbot-backup"
MIGRATION_BACKUP_PREFIX = "envsbot-db-pre-migration"
MANIFEST_NAME = "manifest.json"
SUPPORT_FILE_ENTRIES = (
    "vcard.py",
    "chat_slang.csv",
    "slang_additions.csv",
    "slang_removals.csv",
)


class BackupError(Exception):
    """Raised when a managed backup or restore operation fails."""


class RestoreRuntimeQuiescedError(BackupError):
    """Restore failed after runtime shutdown; the process must restart."""


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


def migration_backup_keep() -> int:
    """Return how many pre-migration SQLite snapshots to retain."""
    try:
        return max(1, int(config.get("database_migration_backup_keep", 5) or 5))
    except Exception:
        return 5


def migration_backup_retention_days() -> int:
    """Return age retention for pre-migration snapshots, or 0 when disabled."""
    try:
        return max(
            0,
            int(config.get("database_migration_backup_retention_days", 90) or 0),
        )
    except Exception:
        return 90


def backup_smoke_test_on_create() -> bool:
    """Return whether every newly-created managed archive must restore cleanly."""
    return bool(config.get("backup_smoke_test_on_create", True))


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
        ("vcard.py", vcard_file(config)),
        ("chat_slang.csv", chat_slang_file(config)),
        ("slang_additions.csv", chat_slang_additions_file(config)),
        ("slang_removals.csv", chat_slang_removals_file(config)),
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


async def create_backup(
    bot: Any,
    *,
    reason: str = "manual",
    prune: bool = True,
    verify: bool | None = None,
) -> Path:
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

    should_verify = backup_smoke_test_on_create() if verify is None else bool(verify)
    if should_verify:
        smoke = await asyncio.to_thread(smoke_test_backup, archive_path)
        if not bool(smoke.get("ok")):
            archive_path.unlink(missing_ok=True)
            errors = ", ".join(str(item) for item in smoke.get("errors", []))
            raise BackupError(
                f"new backup failed restore smoke test: {errors or 'unknown error'}"
            )

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


def list_migration_snapshots(*, directory: Path | None = None) -> list[Path]:
    """List pre-migration SQLite snapshots newest first."""
    directory = directory or backup_dir()
    if not directory.exists():
        return []
    paths = [
        path
        for path in directory.glob(f"{MIGRATION_BACKUP_PREFIX}-*.sqlite3")
        if path.is_file()
    ]
    return sorted(paths, key=lambda path: (path.stat().st_mtime, path.name), reverse=True)


def plan_migration_snapshot_prune(
    *,
    directory: Path | None = None,
    keep: int | None = None,
    days: int | None = None,
) -> list[Path]:
    """Return pre-migration snapshots selected by count/age retention."""
    snapshots = list_migration_snapshots(directory=directory)
    keep = migration_backup_keep() if keep is None else max(1, int(keep))
    days = (
        migration_backup_retention_days()
        if days is None
        else max(0, int(days))
    )
    selected = set(snapshots[keep:])
    if days > 0:
        cutoff = _now().timestamp() - days * 86400
        selected.update(
            path for path in snapshots if path.stat().st_mtime < cutoff
        )
    return [path for path in snapshots if path in selected]


def prune_migration_snapshots(
    *,
    directory: Path | None = None,
    keep: int | None = None,
    days: int | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """Prune verified pre-migration SQLite snapshots."""
    planned = plan_migration_snapshot_prune(
        directory=directory,
        keep=keep,
        days=days,
    )
    if dry_run:
        return planned
    removed: list[Path] = []
    for path in planned:
        try:
            path.unlink()
            removed.append(path)
        except FileNotFoundError:
            continue
    return removed


def verify_sqlite_snapshot(path: Path) -> dict[str, Any]:
    """Open a standalone SQLite snapshot read-only and run integrity checks."""
    path = path.resolve()
    errors: list[str] = []
    integrity: list[str] = []
    foreign_keys: list[tuple[Any, ...]] = []
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = [
                str(row[0])
                for row in connection.execute("PRAGMA integrity_check;").fetchall()
            ]
            foreign_keys = [
                tuple(row)
                for row in connection.execute("PRAGMA foreign_key_check;").fetchall()
            ]
        finally:
            connection.close()
    except Exception as exc:
        errors.append(f"database open/integrity check failed: {exc}")
    if integrity != ["ok"]:
        errors.append(
            "database integrity check failed: "
            + ", ".join(integrity or ["no result"])
        )
    if foreign_keys:
        errors.append(f"foreign key check failed: {len(foreign_keys)} violation(s)")
    return {
        "name": path.name,
        "ok": not errors,
        "errors": errors,
        "database_integrity": integrity,
        "foreign_key_violations": len(foreign_keys),
    }


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
        "vcard.py": vcard_file(config),
        "chat_slang.csv": chat_slang_file(config),
        "slang_additions.csv": chat_slang_additions_file(config),
        "slang_removals.csv": chat_slang_removals_file(config),
    }


def _config_restore_member(members: set[str]) -> str | None:
    """Return the config archive member matching the active config format."""
    config_path = get_runtime_config_path()
    suffix = config_path.suffix.lower()
    candidates: tuple[str, ...]
    if suffix == ".py":
        candidates = ("config.py",)
    elif suffix == ".json":
        candidates = (config_path.name, "config.json")
    else:
        candidates = (config_path.name,)
    return next((name for name in dict.fromkeys(candidates) if name in members), None)


def _restore_specs(members: set[str]) -> tuple[list[tuple[str, Path]], list[str]]:
    """Return live restore targets and entries kept for offline restore."""
    targets = _target_paths()
    online: list[tuple[str, Path]] = []
    if "bot.db" in members:
        online.append(("bot.db", targets["bot.db"]))

    config_member = _config_restore_member(members)
    if config_member is not None:
        online.append((config_member, targets["config.py"]))

    project_root = BASE_DIR.resolve()
    manual: list[str] = []
    for entry in SUPPORT_FILE_ENTRIES:
        if entry not in members:
            continue
        target = targets[entry].resolve()
        if target == project_root or project_root in target.parents:
            manual.append(entry)
        else:
            online.append((entry, target))

    for config_entry in ("config.py", "config.json"):
        if config_entry in members and config_entry != config_member:
            manual.append(config_entry)
    return online, manual


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


def _stage_archive_entries(
    archive_path: Path,
    specs: list[tuple[str, Path]],
    stage_dir: Path,
) -> dict[str, Path]:
    """Extract all live restore inputs before any target is changed."""
    staged: dict[str, Path] = {}
    with zipfile.ZipFile(archive_path) as archive:
        members = _safe_members(archive)
        for index, (entry, _target) in enumerate(specs):
            if entry not in members:
                raise BackupError(f"Backup archive is missing restore entry: {entry}")
            target = stage_dir / f"{index:02d}-{Path(entry).name}"
            with archive.open(entry) as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(target, PRIVATE_FILE_MODE)
            staged[entry] = target
    return staged


def _replace_from_stage(source: Path, target: Path) -> None:
    """Atomically replace one live target from a staged restore file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            os.chmod(tmp_path, PRIVATE_FILE_MODE)
            with source.open("rb") as handle:
                shutil.copyfileobj(handle, tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
        ensure_private_file(target)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def _apply_staged_entries(
    staged: dict[str, Path],
    specs: list[tuple[str, Path]],
) -> list[str]:
    """Publish all staged live restore entries in target order."""
    restored: list[str] = []
    for entry, target in specs:
        _replace_from_stage(staged[entry], target)
        restored.append(entry)
    return restored


def _rollback_staged_entries(
    staged_by_target: dict[Path, Path],
    specs: list[tuple[str, Path]],
    original_exists: dict[Path, bool],
) -> None:
    """Restore exact pre-restore target contents after a failed live restore."""
    for _entry, target in specs:
        if original_exists.get(target, False):
            source = staged_by_target.get(target)
            if source is None:
                raise BackupError(f"Rollback stage is missing target: {target}")
            _replace_from_stage(source, target)
        else:
            target.unlink(missing_ok=True)


def _stage_live_targets(
    specs: list[tuple[str, Path]],
    stage_root: Path,
) -> tuple[dict[Path, Path], dict[Path, bool]]:
    """Snapshot closed live targets for exact rollback immediately before restore."""
    staged_by_target: dict[Path, Path] = {}
    original_exists: dict[Path, bool] = {}
    for index, (_entry, target) in enumerate(specs):
        exists = target.exists()
        original_exists[target] = exists
        if not exists:
            continue
        if not target.is_file():
            raise BackupError(f"Restore target is not a regular file: {target}")
        staged = stage_root / f"{index:03d}-{target.name}"
        with target.open("rb") as source, staged.open("wb") as handle:
            shutil.copyfileobj(source, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(staged, PRIVATE_FILE_MODE)
        staged_by_target[target] = staged
    return staged_by_target, original_exists


async def _close_database(bot: Any) -> bool:
    db = getattr(bot, "db", None)
    close = getattr(db, "close", None)
    if not callable(close):
        return False
    await _maybe_await(close())
    return True


async def _quiesce_runtime_for_restore(bot: Any) -> None:
    """Stop all mutable runtime activity before replacing live state files."""
    if hasattr(bot, "accepting_commands"):
        bot.accepting_commands = False
    session_ready = getattr(bot, "session_ready", None)
    clear = getattr(session_ready, "clear", None)
    if callable(clear):
        clear()

    shutdown_runtime = getattr(bot, "shutdown_runtime", None)
    if callable(shutdown_runtime):
        clean = await _maybe_await(shutdown_runtime())
        if clean is False:
            raise BackupError("runtime shutdown was incomplete")
        return

    # Lightweight embedders/tests may not expose the full lifecycle mixin.
    if not await _close_database(bot):
        raise BackupError("runtime exposes neither shutdown_runtime nor a closable database")


async def restore_backup(bot: Any, archive_path: Path) -> dict[str, Any]:
    """Restore verified runtime files after fully quiescing the bot.

    Verification, staging and the safety backup happen while the current
    runtime is still healthy. Immediately before publishing restored files,
    all mutable bot activity is stopped through ``shutdown_runtime()``. The
    database is intentionally *not* reconnected afterwards: callers must exit
    and start a fresh process so no pre-restore in-memory state can overwrite
    restored data.

    Mutable support files are restored when they live outside the application
    checkout. Legacy source-tree copies remain in the archive for offline/manual
    recovery so hardened deployments never require write access to the read-only
    application tree.
    """
    archive_path = archive_path.resolve()
    smoke = await asyncio.to_thread(smoke_test_backup, archive_path)
    if not bool(smoke.get("ok")):
        errors = ", ".join(str(item) for item in smoke.get("errors", []))
        raise BackupError(
            f"Backup is not safe to restore: {errors or 'verification failed'}"
        )

    manifest = await asyncio.to_thread(_read_manifest, archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        members = _safe_members(archive)
    restore_specs, manual_entries = _restore_specs(members)
    if not restore_specs:
        raise BackupError("Backup contains no runtime files supported by managed restore.")

    with tempfile.TemporaryDirectory(prefix="envsbot-restore-stage-") as stage_name:
        stage_root = Path(stage_name)
        restore_stage = stage_root / "restore"
        rollback_stage = stage_root / "rollback"
        restore_stage.mkdir()
        rollback_stage.mkdir()
        staged_restore = await asyncio.to_thread(
            _stage_archive_entries,
            archive_path,
            restore_specs,
            restore_stage,
        )
        # Do not prune while the selected archive or safety archive is needed.
        safety_backup = await create_backup(
            bot,
            reason="restore-safety",
            prune=False,
            verify=False,
        )
        safety_verify = await asyncio.to_thread(verify_backup, safety_backup)
        if not bool(safety_verify.get("ok")):
            errors = ", ".join(str(item) for item in safety_verify.get("errors", []))
            raise BackupError(
                "Safety backup verification failed before restore: "
                f"{errors or 'unknown error'}"
            )

        try:
            await _quiesce_runtime_for_restore(bot)
        except Exception as quiesce_error:
            raise RestoreRuntimeQuiescedError(
                "Could not safely quiesce the bot before restore; a process "
                f"restart is required: {quiesce_error}"
            ) from quiesce_error

        # shutdown_runtime() flushes and closes mutable state. Snapshot the exact
        # closed files now, rather than relying only on the earlier safety backup,
        # so rollback cannot lose writes made between that backup and shutdown.
        try:
            rollback_by_target, original_exists = await asyncio.to_thread(
                _stage_live_targets,
                restore_specs,
                rollback_stage,
            )
        except Exception as rollback_stage_error:
            raise RestoreRuntimeQuiescedError(
                "Could not stage the quiesced runtime for rollback; no restore "
                "files were published and a process restart is required: "
                f"{rollback_stage_error}"
            ) from rollback_stage_error

        restored: list[str] = []
        try:
            restored = await asyncio.to_thread(
                _apply_staged_entries,
                staged_restore,
                restore_specs,
            )
        except Exception as restore_error:
            rollback_error: Exception | None = None
            try:
                await asyncio.to_thread(
                    _rollback_staged_entries,
                    rollback_by_target,
                    restore_specs,
                    original_exists,
                )
            except Exception as exc:
                rollback_error = exc

            if rollback_error is not None:
                raise RestoreRuntimeQuiescedError(
                    "Restore failed and automatic rollback also failed; "
                    f"safety backup {safety_backup.name} was preserved. "
                    "The bot must restart before any further operation. "
                    f"Restore error: {restore_error}; rollback error: {rollback_error}"
                ) from restore_error
            raise RestoreRuntimeQuiescedError(
                "Restore failed; exact pre-restore runtime files were rolled back. "
                f"Safety backup {safety_backup.name} was preserved. The bot must "
                f"restart before any further operation: {restore_error}"
            ) from restore_error

    try:
        await asyncio.to_thread(prune_old_backups)
    except Exception:
        log.exception(
            "[BACKUP] restore status=ok prune_status=failed archive=%s",
            archive_path.name,
        )

    return {
        "archive": archive_path.name,
        "manifest": manifest,
        "restored": restored,
        "manual_restore": manual_entries,
        "safety_backup": safety_backup.name,
        "restart_required": True,
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
    foreign_key_violations: list[tuple[Any, ...]] = []
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
                    foreign_key_violations = [
                        tuple(row)
                        for row in connection.execute("PRAGMA foreign_key_check;").fetchall()
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
            if foreign_key_violations:
                errors.append(
                    "database foreign key check failed: "
                    f"{len(foreign_key_violations)} violation(s)"
                )
    return {
        "name": path.name,
        "ok": not errors,
        "errors": errors,
        "database_integrity": database_result,
        "foreign_key_violations": len(foreign_key_violations),
    }


def restore_plan(archive_path: Path) -> dict[str, Any]:
    """Return what restore_backup() would restore without writing files."""
    archive_path = archive_path.resolve()
    manifest = _read_manifest(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        members = _safe_members(archive)
    specs, manual_entries = _restore_specs(members)
    entries = [entry for entry, _target in specs]
    return {
        "archive": archive_path.name,
        "manifest": manifest,
        "entries": entries,
        "targets": {entry: str(target) for entry, target in specs},
        "manual_restore": manual_entries,
    }
