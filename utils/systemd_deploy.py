"""Render and validate an envsbot systemd service for the current installation."""

from __future__ import annotations

import grp
import os
import pwd
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from utils.config import get_runtime_config_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_runtime_path(value: object, *, root: Path | None = None) -> Path:
    path = Path(str(value)).expanduser()
    base = PROJECT_ROOT if root is None else root
    return path if path.is_absolute() else (base / path).resolve()


def _idlerpg_export_path(config: Mapping[str, Any]) -> Path:
    group = config.get("idlerpg")
    if isinstance(group, Mapping):
        value = group.get("export_path", "data/idlerpg")
    else:
        value = "data/idlerpg"
    return _resolve_runtime_path(value)


def service_paths(config: Mapping[str, Any]) -> dict[str, Path]:
    """Return relevant runtime paths used by systemd hardening checks."""
    return {
        "working_directory": PROJECT_ROOT,
        "config": get_runtime_config_path().resolve(),
        "database": _resolve_runtime_path(config.get("db", "bot.db")),
        "log_directory": _resolve_runtime_path(config.get("log_dir", "logs")),
        "backup_directory": _resolve_runtime_path(config.get("backup_dir", "data/backups")),
        "idlerpg_export": _idlerpg_export_path(config),
        "restart_notification": _resolve_runtime_path(
            config.get("restart_notification_file", "data/envsbot_restart_notification.json")
        ),
    }


def _exec_start() -> str:
    candidate = Path(sys.executable).resolve().parent / "envsbot"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)
    discovered = shutil.which("envsbot")
    if discovered:
        return str(Path(discovered).resolve())
    return f"{Path(sys.executable).resolve()} {PROJECT_ROOT / 'envsbot.py'}"


def _unique_writable_paths(config: Mapping[str, Any]) -> list[Path]:
    paths = service_paths(config)
    candidates = [
        paths["config"].parent,
        paths["database"].parent,
        paths["log_directory"],
        paths["backup_directory"],
        paths["idlerpg_export"],
        paths["restart_notification"].parent,
    ]
    result: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if any(resolved == existing or existing in resolved.parents for existing in result):
            continue
        result = [existing for existing in result if resolved not in existing.parents]
        result.append(resolved)
    return result


def _writable_paths_cover_project(config: Mapping[str, Any]) -> bool:
    """Return whether writable paths make the application tree writable."""
    project = PROJECT_ROOT.resolve()
    return any(
        path == project or path in project.parents
        for path in _unique_writable_paths(config)
    )


def render_systemd_unit(
    config: Mapping[str, Any],
    *,
    user: str = "envsbot",
    group: str = "envsbot",
    environment_file: str = "/etc/default/envsbot",
) -> str:
    """Render a hardened unit using paths from the active installation."""
    workdir = PROJECT_ROOT.resolve()
    config_path = service_paths(config)["config"]
    writable = " ".join(str(path) for path in _unique_writable_paths(config))
    exec_start = _exec_start()
    return f"""[Unit]\nDescription=EnvsBot XMPP bot\nDocumentation=https://github.com/envs-net/envsbot\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=notify\nNotifyAccess=main\nUser={user}\nGroup={group}\nWorkingDirectory={workdir}\nEnvironmentFile=-{environment_file}\nEnvironment=PYTHONUNBUFFERED=1\nEnvironment=ENVSBOT_CONFIG={config_path}\nExecStart={exec_start}\nRestart=on-failure\nRestartSec=5\nWatchdogSec=60\nTimeoutStopSec=45\nUMask=0077\n\nNoNewPrivileges=true\nPrivateTmp=true\nPrivateDevices=true\nProtectSystem=strict\nProtectHome=true\nProtectKernelTunables=true\nProtectKernelModules=true\nProtectKernelLogs=true\nProtectControlGroups=true\nRestrictSUIDSGID=true\nLockPersonality=true\nCapabilityBoundingSet=\nAmbientCapabilities=\nReadWritePaths={writable}\n\n[Install]\nWantedBy=multi-user.target\n"""


def _account_access(path: Path, *, user: str, group: str, write: bool = False, execute: bool = False) -> bool:
    """Check POSIX mode bits for the configured systemd service account."""
    try:
        user_info = pwd.getpwnam(user)
        group_info = grp.getgrnam(group)
        details = path.stat()
    except (KeyError, OSError):
        return False

    gids = {user_info.pw_gid, group_info.gr_gid}
    for entry in grp.getgrall():
        if user in entry.gr_mem:
            gids.add(entry.gr_gid)

    mode = details.st_mode
    if details.st_uid == user_info.pw_uid:
        bits = (mode >> 6) & 0b111
    elif details.st_gid in gids:
        bits = (mode >> 3) & 0b111
    else:
        bits = mode & 0b111
    # Permission triples use r=4, w=2, x=1 independent of owner/group/other.
    required = 2 if write else 4
    if execute:
        required |= 1
    return bits & required == required


def check_systemd_installation(
    config: Mapping[str, Any],
    *,
    user: str = "envsbot",
    group: str = "envsbot",
    environment_file: str = "/etc/default/envsbot",
) -> tuple[int, str]:
    """Check paths and service-account permissions for the rendered unit."""
    paths = service_paths(config)
    checks: list[tuple[bool, str]] = []
    try:
        pwd.getpwnam(user)
        user_ok = True
    except KeyError:
        user_ok = False
    try:
        grp.getgrnam(group)
        group_ok = True
    except KeyError:
        group_ok = False
    checks.append((user_ok, f"User: {user}"))
    checks.append((group_ok, f"Group: {group}"))

    workdir = paths["working_directory"]
    checks.append((
        workdir.is_dir() and user_ok and group_ok and _account_access(
            workdir, user=user, group=group, execute=True
        ),
        f"WorkingDirectory: {workdir}",
    ))

    exec_text = _exec_start()
    executable = Path(exec_text.split()[0])
    checks.append((
        executable.is_file() and user_ok and group_ok and _account_access(
            executable, user=user, group=group, execute=True
        ),
        f"ExecStart: {exec_text}",
    ))

    config_path = paths["config"]
    checks.append((
        config_path.is_file() and user_ok and group_ok and _account_access(
            config_path, user=user, group=group
        ),
        f"Config: {config_path}",
    ))

    for label in ("database", "restart_notification"):
        parent = paths[label].parent
        checks.append((
            parent.is_dir() and user_ok and group_ok and _account_access(
                parent, user=user, group=group, write=True, execute=True
            ),
            f"{label} parent: {parent}",
        ))
    for label in ("backup_directory", "idlerpg_export", "log_directory"):
        path = paths[label]
        parent = path if path.is_dir() else path.parent
        checks.append((
            parent.is_dir() and user_ok and group_ok and _account_access(
                parent, user=user, group=group, write=True, execute=True
            ),
            f"{label}: {path}",
        ))

    writable = _unique_writable_paths(config)
    checks.append((bool(writable), "ReadWritePaths: " + " ".join(map(str, writable))))
    checks.append((
        not _writable_paths_cover_project(config),
        "Application tree read-only: move ENVSBOT_CONFIG and DB_FILE out of "
        f"{PROJECT_ROOT.resolve()} if this check fails",
    ))

    lines = [f"{'OK' if ok else 'FAIL'}  {text}" for ok, text in checks]
    lines.append(
        "\nRendered unit:\n"
        + render_systemd_unit(
            config, user=user, group=group, environment_file=environment_file
        )
    )
    return (0 if all(ok for ok, _ in checks) else 1), "\n".join(lines)

