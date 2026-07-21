"""Security helpers for sensitive runtime files and directories."""

from __future__ import annotations

import os
import stat
from pathlib import Path

PRIVATE_FILE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700


def ensure_private_directory(path: str | os.PathLike[str]) -> Path:
    """Create *path* and restrict it to the owning user."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    os.chmod(directory, PRIVATE_DIRECTORY_MODE)
    return directory


def ensure_private_file(
    path: str | os.PathLike[str],
    *,
    mode: int = PRIVATE_FILE_MODE,
) -> Path:
    """Restrict an existing regular file to the owning user."""
    target = Path(path)
    if target.exists() and target.is_file():
        os.chmod(target, mode)
    return target


def permission_bits(path: str | os.PathLike[str]) -> int | None:
    """Return POSIX permission bits, or ``None`` when unavailable."""
    try:
        return stat.S_IMODE(Path(path).stat().st_mode)
    except (FileNotFoundError, OSError):
        return None


def has_group_or_other_access(path: str | os.PathLike[str]) -> bool:
    """Return whether a path grants any permission to group or others."""
    mode = permission_bits(path)
    return bool(mode is not None and mode & 0o077)


def format_mode(path: str | os.PathLike[str]) -> str:
    """Return a compact octal mode for diagnostics."""
    mode = permission_bits(path)
    return "missing" if mode is None else f"{mode:04o}"


def sensitive_permission_targets(
    *,
    config_path: str | os.PathLike[str],
    database_path: str | os.PathLike[str],
    backup_directory: str | os.PathLike[str],
) -> tuple[tuple[str, Path], ...]:
    """Return sensitive runtime files/directories that should be owner-only."""
    targets: list[tuple[str, Path]] = [("config", Path(config_path))]

    raw_database = str(database_path or "")
    if raw_database and raw_database != ":memory:" and not raw_database.startswith("file:"):
        database = Path(database_path)
        targets.extend(
            [
                ("database", database),
                ("database WAL", Path(f"{database}-wal")),
                ("database SHM", Path(f"{database}-shm")),
            ]
        )

    backups = Path(backup_directory)
    targets.append(("backup dir", backups))
    if backups.is_dir():
        targets.extend(
            (f"backup {path.name}", path)
            for path in sorted(backups.glob("*.zip"))
            if path.is_file()
        )
    return tuple(targets)
