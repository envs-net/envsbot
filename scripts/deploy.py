#!/usr/bin/env python3
"""Interactive, preservation-first deployment helper for envsbot.

The helper intentionally orchestrates existing envsbot deployment primitives
instead of replacing them.  A bare invocation prints help and changes nothing.
"""

from __future__ import annotations

import argparse
import filecmp
import grp
import json
import os
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


_STABLE_RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")


class DeployError(RuntimeError):
    """Expected deployment failure with an operator-readable message."""


class UserCancelled(DeployError):
    """Raised when an interactive action is declined."""


@dataclass(frozen=True)
class Deployment:
    root: Path
    venv: Path
    config: Path
    service: str
    service_user: str
    service_group: str
    unit: Path
    python: str
    dry_run: bool = False

    @property
    def envsbot(self) -> Path:
        return self.venv / "bin" / "envsbot"

    @property
    def pip(self) -> Path:
        return self.venv / "bin" / "pip"

    @property
    def venv_python(self) -> Path:
        return self.venv / "bin" / "python"

    @property
    def environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["ENVSBOT_CONFIG"] = str(self.config)
        return env


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_config(root: Path, service: str) -> Path:
    configured = os.environ.get("ENVSBOT_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()
    systemd_config = _systemd_config_path(service)
    if systemd_config is not None:
        return systemd_config
    hardened = Path("/etc/envsbot/config.py")
    if hardened.exists():
        return hardened
    legacy_json = root / "config.json"
    if not (root / "config.py").exists() and legacy_json.exists():
        return legacy_json.resolve()
    return (root / "config.py").resolve()


def _systemd_property(service: str, prop: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "show", service, f"--property={prop}", "--value"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _systemd_config_path(service: str) -> Path | None:
    environment = _systemd_property(service, "Environment")
    if not environment:
        return None
    try:
        values = shlex.split(environment)
    except ValueError:
        values = environment.split()
    for value in values:
        if value.startswith("ENVSBOT_CONFIG="):
            configured = value.split("=", 1)[1].strip()
            if configured:
                path = Path(configured).expanduser()
                if not path.is_absolute():
                    workdir = _systemd_property(service, "WorkingDirectory")
                    base = Path(workdir).expanduser() if workdir else _project_root()
                    path = base / path
                return path.resolve()
    return None


def _systemd_venv(service: str) -> Path | None:
    exec_start = _systemd_property(service, "ExecStart")
    marker = "path="
    if marker not in exec_start:
        return None
    executable = exec_start.split(marker, 1)[1].split(";", 1)[0].strip()
    path = Path(executable).expanduser()
    if path.name == "envsbot" and path.parent.name == "bin":
        return path.parent.parent.resolve()
    return None


def _default_service_account(service: str, prop: str, fallback: str) -> str:
    env_name = f"ENVSBOT_SERVICE_{prop.upper()}"
    configured = os.environ.get(env_name)
    if configured:
        return configured
    discovered = _systemd_property(service, prop)
    return discovered or fallback


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="./scripts/deploy.sh",
        description=(
            "Interactive, preservation-first envsbot deployment helper. "
            "Running it without a command only shows this help."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  ./scripts/deploy.sh status
  ./scripts/deploy.sh check
  ./scripts/deploy.sh install --dry-run
  sudo ./scripts/deploy.sh install --config /etc/envsbot/config.py
  sudo ./scripts/deploy.sh update --to v1.8.0
  sudo ./scripts/deploy.sh update --to v1.7.3 --allow-downgrade

Paths are discovered from the current checkout and active configuration where
possible.  Override non-standard installations with --root, --venv, --config,
--service, --user, --group and --unit, or the documented ENVSBOT_* variables.

Safety rules:
  * install/update require an explicit confirmation;
  * stopping and starting systemd are confirmed separately;
  * existing config, database, vCard, operator avatar and systemd unit files are kept;
  * an existing systemd unit is never replaced by this helper;
  * update refuses a dirty tracked Git worktree;
  * automatic updates select stable vX.Y.Z release tags only and never downgrade to an older tag;
  * explicit downgrades require --allow-downgrade plus an additional confirmation;
  * a failed update after stopping the service leaves it stopped.
""",
    )
    parser.add_argument("command", nargs="?", choices=("status", "check", "install", "update"))
    parser.add_argument("--root", type=Path, help="application checkout (default: current checkout)")
    parser.add_argument("--venv", type=Path, help="virtualenv path (default: ROOT/.venv)")
    parser.add_argument("--config", type=Path, help="runtime config path")
    parser.add_argument(
        "--service",
        default=os.environ.get("ENVSBOT_SERVICE", "envsbot.service"),
        help="systemd service name (default: envsbot.service)",
    )
    parser.add_argument("--user", help="systemd service user")
    parser.add_argument("--group", help="systemd service group")
    parser.add_argument("--unit", type=Path, help="systemd unit path")
    parser.add_argument(
        "--python",
        default=os.environ.get("ENVSBOT_DEPLOY_BASE_PYTHON", "python3"),
        help="base interpreter used to create a missing virtualenv",
    )
    parser.add_argument("--dry-run", action="store_true", help="show the plan without changing anything")
    parser.add_argument(
        "--to",
        metavar="TAG",
        help="explicit tag to install with update (default: newest stable vX.Y.Z release)",
    )
    parser.add_argument(
        "--allow-downgrade",
        action="store_true",
        help="allow an explicit --to TAG older than HEAD (never used for automatic updates)",
    )
    return parser


def _deployment(options: argparse.Namespace) -> Deployment:
    root = (options.root or _project_root()).expanduser().resolve()
    service = options.service
    venv_value = options.venv or os.environ.get("ENVSBOT_VENV") or _systemd_venv(service) or root / ".venv"
    venv = Path(venv_value).expanduser().resolve()
    config = (options.config or _default_config(root, service)).expanduser().resolve()
    user = options.user or _default_service_account(service, "User", "envsbot")
    group = options.group or _default_service_account(service, "Group", user)
    unit_value = options.unit or os.environ.get("ENVSBOT_SYSTEMD_UNIT")
    if unit_value is None:
        fragment = _systemd_property(service, "FragmentPath")
        unit_name = service if service.endswith(".service") else f"{service}.service"
        unit_value = fragment or f"/etc/systemd/system/{unit_name}"
    unit = Path(unit_value).expanduser().resolve()
    return Deployment(
        root=root,
        venv=venv,
        config=config,
        service=service,
        service_user=user,
        service_group=group,
        unit=unit,
        python=options.python,
        dry_run=bool(options.dry_run),
    )


def _quote(args: Sequence[object]) -> str:
    return " ".join(shlex.quote(str(item)) for item in args)


def _run(
    args: Sequence[object],
    *,
    deployment: Deployment | None = None,
    as_service_user: bool = False,
    capture: bool = False,
    check: bool = True,
    cwd: Path | None = None,
    announce: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [str(item) for item in args]
    if as_service_user and deployment is not None:
        current = pwd.getpwuid(os.geteuid()).pw_name
        if deployment.service_user != current:
            if os.geteuid() != 0:
                raise DeployError(
                    f"run this command as {deployment.service_user!r} or as root; "
                    f"current user is {current!r}"
                )
            if shutil.which("runuser"):
                command = ["runuser", "-u", deployment.service_user, "--", *command]
            elif shutil.which("sudo"):
                command = ["sudo", "-u", deployment.service_user, "--", *command]
            else:
                raise DeployError("runuser/sudo is required to execute commands as the service user")
    if announce:
        print(f"+ {_quote(command)}")
    try:
        result = subprocess.run(
            command,
            check=False,
            cwd=str(cwd) if cwd else None,
            env=deployment.environment if deployment else None,
            capture_output=capture,
            text=True,
        )
    except OSError as exc:
        raise DeployError(f"could not execute {command[0]}: {exc}") from exc
    if check and result.returncode != 0:
        if capture:
            if result.stdout.strip():
                print(result.stdout.rstrip())
            if result.stderr.strip():
                print(result.stderr.rstrip(), file=sys.stderr)
        raise DeployError(f"command failed with exit code {result.returncode}: {_quote(command)}")
    return result


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N] ").strip().casefold()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _require_confirmation(prompt: str) -> None:
    if not _confirm(prompt):
        raise UserCancelled("cancelled by operator")


def _require_source_tree(deployment: Deployment) -> None:
    required = ("pyproject.toml", "config_sample.py", "vcard_sample.py", "scripts/deploy.sh")
    missing = [name for name in required if not (deployment.root / name).is_file()]
    if missing:
        raise DeployError(
            f"not an envsbot source checkout: {deployment.root} (missing: {', '.join(missing)})"
        )


def _account_exists(user: str) -> bool:
    try:
        pwd.getpwnam(user)
    except KeyError:
        return False
    return True


def _ensure_parent(path: Path, deployment: Deployment, *, mode: int = 0o750) -> None:
    if path.parent.exists():
        return
    path.parent.mkdir(parents=True, mode=mode)
    if os.geteuid() == 0 and _account_exists(deployment.service_user):
        details = pwd.getpwnam(deployment.service_user)
        try:
            gid = grp.getgrnam(deployment.service_group).gr_gid
        except KeyError:
            gid = details.pw_gid
        os.chown(path.parent, details.pw_uid, gid)


def _copy_if_missing(source: Path, destination: Path, deployment: Deployment, *, mode: int) -> bool:
    if destination.exists():
        print(f"KEEP existing {destination}")
        return False
    _ensure_parent(destination, deployment)
    try:
        with source.open("rb") as source_file, destination.open("xb") as destination_file:
            shutil.copyfileobj(source_file, destination_file)
    except FileExistsError:
        print(f"KEEP existing {destination}")
        return False
    destination.chmod(mode)
    if os.geteuid() == 0 and _account_exists(deployment.service_user):
        details = pwd.getpwnam(deployment.service_user)
        try:
            gid = grp.getgrnam(deployment.service_group).gr_gid
        except KeyError:
            gid = details.pw_gid
        os.chown(destination, details.pw_uid, gid)
    print(f"CREATE {destination}")
    return True


def _venv_version(deployment: Deployment) -> tuple[int, int]:
    if not deployment.venv_python.is_file():
        raise DeployError(f"virtualenv Python not found: {deployment.venv_python}")
    result = _run(
        [deployment.venv_python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        deployment=deployment,
        capture=True,
        announce=False,
    )
    try:
        major, minor = result.stdout.strip().split(".", 1)
        return int(major), int(minor)
    except (TypeError, ValueError) as exc:
        raise DeployError("could not determine virtualenv Python version") from exc


def _constraint_file(deployment: Deployment) -> Path:
    major, minor = _venv_version(deployment)
    if major != 3 or minor not in {12, 13}:
        raise DeployError(f"unsupported Python version {major}.{minor}; envsbot supports Python 3.12/3.13")
    path = deployment.root / f"constraints/python3{minor}.txt"
    if not path.is_file():
        raise DeployError(f"constraint snapshot missing: {path}")
    return path


def _install_dependencies(deployment: Deployment) -> None:
    constraints = _constraint_file(deployment)
    _run(
        [deployment.pip, "install", "-c", constraints, "-e", deployment.root],
        deployment=deployment,
        as_service_user=True,
    )


def _create_venv_if_missing(deployment: Deployment) -> None:
    if deployment.venv_python.is_file():
        print(f"KEEP existing virtualenv {deployment.venv}")
        return
    print(f"CREATE virtualenv {deployment.venv}")
    _run(
        [deployment.python, "-m", "venv", deployment.venv],
        deployment=deployment,
        as_service_user=True,
    )


def _runtime_paths(deployment: Deployment) -> dict[str, Path | None]:
    code = r'''
import json
from pathlib import Path
from utils.bundled_assets import resolve_bundled_asset
from utils.config import config, get_runtime_config_path
from utils.runtime_paths import vcard_file
from utils.systemd_deploy import service_paths

paths = service_paths(config)
avatar_value = config.get("avatar")
avatar = resolve_bundled_asset(str(avatar_value)) if avatar_value else None
print(json.dumps({
    "config": str(get_runtime_config_path().resolve()),
    "database": str(paths["database"].resolve()),
    "runtime_data": str(paths["runtime_data_directory"].resolve()),
    "vcard": str(vcard_file(config).resolve()),
    "avatar": str(avatar.resolve()) if avatar else None,
}))
'''
    result = _run(
        [deployment.venv_python, "-c", code],
        deployment=deployment,
        capture=True,
        cwd=deployment.root,
        announce=False,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DeployError("could not resolve runtime paths from the active configuration") from exc
    return {name: (Path(value).resolve() if value else None) for name, value in data.items()}


def _envsbot(
    deployment: Deployment,
    *args: str,
    capture: bool = False,
    announce: bool = True,
) -> subprocess.CompletedProcess[str]:
    if not deployment.envsbot.is_file():
        raise DeployError(f"envsbot executable not found: {deployment.envsbot}")
    return _run(
        [deployment.envsbot, *args],
        deployment=deployment,
        as_service_user=True,
        capture=capture,
        cwd=deployment.root,
        announce=announce,
    )


def _systemctl_exists(deployment: Deployment) -> bool:
    if not shutil.which("systemctl"):
        return False
    result = _run(
        ["systemctl", "cat", deployment.service], check=False, capture=True, announce=False
    )
    return result.returncode == 0


def _service_active(deployment: Deployment) -> bool:
    if not shutil.which("systemctl"):
        return False
    result = _run(
        ["systemctl", "is-active", "--quiet", deployment.service], check=False, announce=False
    )
    return result.returncode == 0


def _unit_service_values(rendered: str) -> dict[str, list[str]]:
    """Return assignments from the rendered [Service] section."""
    values: dict[str, list[str]] = {}
    section = ""
    for raw_line in rendered.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "Service" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key, []).append(value)
    return values


def _environment_assignment(value: str, name: str) -> str | None:
    try:
        fields = shlex.split(value)
    except ValueError:
        fields = value.split()
    prefix = f"{name}="
    for field in fields:
        if field.startswith(prefix):
            return field[len(prefix):]
    return None


def _exec_start_executable(value: str) -> str:
    if "path=" in value:
        return value.split("path=", 1)[1].split(";", 1)[0].strip()
    try:
        fields = shlex.split(value)
    except ValueError:
        fields = value.split()
    return fields[0] if fields else ""


def _bool_value(value: str) -> bool | None:
    normalized = value.strip().casefold()
    if normalized in {"1", "yes", "true", "on"}:
        return True
    if normalized in {"0", "no", "false", "off"}:
        return False
    return None


def _duration_seconds(value: str) -> float | None:
    """Parse the compact duration forms used by systemctl show."""
    normalized = value.strip().casefold().replace(" ", "")
    if not normalized or normalized in {"infinity", "infinite"}:
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(usec|us|ms|msec|s|sec|min|h|hr)?", normalized)
    if match is None:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or "s"
    factor = {
        "usec": 0.000001,
        "us": 0.000001,
        "ms": 0.001,
        "msec": 0.001,
        "s": 1.0,
        "sec": 1.0,
        "min": 60.0,
        "h": 3600.0,
        "hr": 3600.0,
    }[unit]
    return amount * factor


def _path_set(value: str) -> set[str]:
    try:
        fields = shlex.split(value)
    except ValueError:
        fields = value.split()
    result: set[str] = set()
    for field in fields:
        item = field.strip()
        if not item:
            continue
        prefix = ""
        while item.startswith(("-", "+", "!")):
            prefix += item[0]
            item = item[1:]
        if item:
            result.add(prefix + str(Path(item).expanduser().resolve()))
    return result


def _umask_value(value: str) -> int | None:
    text = value.strip()
    try:
        return int(text, 8) if text else None
    except ValueError:
        return None


def _desired_systemd_values(deployment: Deployment) -> dict[str, object]:
    rendered = _envsbot(
        deployment,
        "systemd",
        "render",
        "--user",
        deployment.service_user,
        "--group",
        deployment.service_group,
        capture=True,
        announce=False,
    ).stdout
    service = _unit_service_values(rendered)

    def one(name: str) -> str:
        values = service.get(name, [])
        if not values:
            raise DeployError(f"rendered systemd unit is missing {name}")
        return values[-1]

    config_value = None
    for environment in service.get("Environment", []):
        configured = _environment_assignment(environment, "ENVSBOT_CONFIG")
        if configured is not None:
            config_value = configured
            break
    if config_value is None:
        raise DeployError("rendered systemd unit is missing ENVSBOT_CONFIG")

    watchdog = _duration_seconds(one("WatchdogSec"))
    if watchdog is None:
        raise DeployError("rendered systemd WatchdogSec could not be parsed")

    restart_delay = _duration_seconds(one("RestartSec"))
    stop_timeout = _duration_seconds(one("TimeoutStopSec"))
    if restart_delay is None or stop_timeout is None:
        raise DeployError("rendered systemd service timeout could not be parsed")

    return {
        "Unit file": str(deployment.unit),
        "Type": one("Type"),
        "NotifyAccess": one("NotifyAccess"),
        "User": one("User"),
        "Group": one("Group"),
        "WorkingDirectory": str(Path(one("WorkingDirectory")).resolve()),
        "ExecStart": str(Path(_exec_start_executable(one("ExecStart"))).resolve()),
        "ENVSBOT_CONFIG": str(Path(config_value).resolve()),
        "Restart": one("Restart"),
        "Restart delay": restart_delay,
        "Watchdog": watchdog,
        "Stop timeout": stop_timeout,
        "UMask": _umask_value(one("UMask")),
        "NoNewPrivileges": _bool_value(one("NoNewPrivileges")),
        "PrivateTmp": _bool_value(one("PrivateTmp")),
        "PrivateDevices": _bool_value(one("PrivateDevices")),
        "ProtectSystem": one("ProtectSystem"),
        "ProtectHome": _bool_value(one("ProtectHome")),
        "ProtectKernelTunables": _bool_value(one("ProtectKernelTunables")),
        "ProtectKernelModules": _bool_value(one("ProtectKernelModules")),
        "ProtectKernelLogs": _bool_value(one("ProtectKernelLogs")),
        "ProtectControlGroups": _bool_value(one("ProtectControlGroups")),
        "RestrictSUIDSGID": _bool_value(one("RestrictSUIDSGID")),
        "LockPersonality": _bool_value(one("LockPersonality")),
        "ReadWritePaths": _path_set(one("ReadWritePaths")),
    }


def _resolved_path_text(value: str) -> str:
    text = value.strip()
    return str(Path(text).expanduser().resolve()) if text else ""


def _actual_systemd_values(deployment: Deployment) -> dict[str, object]:
    environment = _systemd_property(deployment.service, "Environment")
    config_value = _environment_assignment(environment, "ENVSBOT_CONFIG")
    fragment = _systemd_property(deployment.service, "FragmentPath")
    working_directory = _systemd_property(deployment.service, "WorkingDirectory")
    exec_start = _exec_start_executable(
        _systemd_property(deployment.service, "ExecStart")
    )
    watchdog = _duration_seconds(_systemd_property(deployment.service, "WatchdogUSec"))
    restart_delay = _duration_seconds(
        _systemd_property(deployment.service, "RestartUSec")
    )
    stop_timeout = _duration_seconds(
        _systemd_property(deployment.service, "TimeoutStopUSec")
    )
    return {
        "Unit file": _resolved_path_text(fragment),
        "Type": _systemd_property(deployment.service, "Type"),
        "NotifyAccess": _systemd_property(deployment.service, "NotifyAccess"),
        "User": _systemd_property(deployment.service, "User"),
        "Group": _systemd_property(deployment.service, "Group"),
        "WorkingDirectory": _resolved_path_text(working_directory),
        "ExecStart": _resolved_path_text(exec_start),
        "ENVSBOT_CONFIG": _resolved_path_text(config_value or ""),
        "Restart": _systemd_property(deployment.service, "Restart"),
        "Restart delay": restart_delay,
        "Watchdog": watchdog,
        "Stop timeout": stop_timeout,
        "UMask": _umask_value(_systemd_property(deployment.service, "UMask")),
        "NoNewPrivileges": _bool_value(
            _systemd_property(deployment.service, "NoNewPrivileges")
        ),
        "PrivateTmp": _bool_value(_systemd_property(deployment.service, "PrivateTmp")),
        "PrivateDevices": _bool_value(
            _systemd_property(deployment.service, "PrivateDevices")
        ),
        "ProtectSystem": _systemd_property(deployment.service, "ProtectSystem"),
        "ProtectHome": _bool_value(_systemd_property(deployment.service, "ProtectHome")),
        "ProtectKernelTunables": _bool_value(
            _systemd_property(deployment.service, "ProtectKernelTunables")
        ),
        "ProtectKernelModules": _bool_value(
            _systemd_property(deployment.service, "ProtectKernelModules")
        ),
        "ProtectKernelLogs": _bool_value(
            _systemd_property(deployment.service, "ProtectKernelLogs")
        ),
        "ProtectControlGroups": _bool_value(
            _systemd_property(deployment.service, "ProtectControlGroups")
        ),
        "RestrictSUIDSGID": _bool_value(
            _systemd_property(deployment.service, "RestrictSUIDSGID")
        ),
        "LockPersonality": _bool_value(
            _systemd_property(deployment.service, "LockPersonality")
        ),
        "ReadWritePaths": _path_set(
            _systemd_property(deployment.service, "ReadWritePaths")
        ),
    }


def _display_systemd_value(name: str, value: object) -> str:
    if name in {"Restart delay", "Watchdog", "Stop timeout"}:
        return f"{value:g}s" if isinstance(value, (int, float)) else str(value)
    if name == "UMask" and isinstance(value, int):
        return f"{value:04o}"
    if name == "ReadWritePaths" and isinstance(value, set):
        return " ".join(sorted(value)) or "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "-"
    return str(value)


def _check_installed_systemd(deployment: Deployment) -> bool:
    """Compare the desired unit with systemd's effective loaded properties."""
    if not shutil.which("systemctl"):
        raise DeployError("systemctl is required for installed service checks")
    if not _systemctl_exists(deployment):
        raise DeployError(f"installed systemd service not found: {deployment.service}")

    desired = _desired_systemd_values(deployment)
    actual = _actual_systemd_values(deployment)
    print("Installed systemd service:")
    all_ok = True
    for name, expected in desired.items():
        current = actual.get(name)
        ok = current == expected
        all_ok = all_ok and ok
        current_text = _display_systemd_value(name, current)
        if ok:
            print(f"  OK    {name}: {current_text}")
        else:
            expected_text = _display_systemd_value(name, expected)
            print(f"  FAIL  {name}: {current_text}")
            print(f"        expected: {expected_text}")
    return all_ok



def _stop_active_service(deployment: Deployment, *, reason: str) -> bool:
    if not _service_active(deployment):
        print(f"Service {deployment.service} is not active; no stop required.")
        return False
    _require_confirmation(f"Stop {deployment.service} {reason}?")
    _run(["systemctl", "stop", deployment.service])
    return True


def _ask_start(deployment: Deployment) -> None:
    if not _systemctl_exists(deployment):
        print(f"No installed systemd service {deployment.service}; not starting anything.")
        return
    if _service_active(deployment):
        print(f"Service {deployment.service} is already active.")
        return
    if _confirm(f"Start {deployment.service} now?"):
        _run(["systemctl", "start", deployment.service])
        _run(["systemctl", "is-active", deployment.service])
    else:
        print(f"LEAVE {deployment.service} stopped (operator choice)")


def _git(
    deployment: Deployment,
    *args: str,
    capture: bool = False,
    check: bool = True,
    announce: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(
        ["git", *args],
        deployment=deployment,
        as_service_user=True,
        capture=capture,
        check=check,
        cwd=deployment.root,
        announce=announce,
    )


def _require_clean_tracked_tree(deployment: Deployment) -> None:
    result = _git(
        deployment, "status", "--porcelain", "--untracked-files=no", capture=True, announce=False
    )
    if result.stdout.strip():
        raise DeployError(
            "tracked Git worktree is not clean; commit/stash local code changes before updating\n"
            + result.stdout.rstrip()
        )


def _current_revision(deployment: Deployment) -> str:
    result = _git(
        deployment, "describe", "--tags", "--always", "--dirty", capture=True, announce=False
    )
    return result.stdout.strip() or "unknown"


def _is_stable_release_tag(tag: str) -> bool:
    return _STABLE_RELEASE_TAG.fullmatch(tag) is not None


def _latest_tag(deployment: Deployment) -> str:
    result = _git(deployment, "tag", "--sort=-v:refname", capture=True, announce=False)
    tags = [
        line.strip()
        for line in result.stdout.splitlines()
        if _is_stable_release_tag(line.strip())
    ]
    if not tags:
        raise DeployError("no stable Git release tags (vX.Y.Z) found")
    return tags[0]


def _git_remote(deployment: Deployment) -> str:
    """Return the remote used for release discovery without guessing silently."""
    configured = os.environ.get("ENVSBOT_DEPLOY_REMOTE")
    remotes_result = _git(deployment, "remote", capture=True, announce=False)
    remotes = [line.strip() for line in remotes_result.stdout.splitlines() if line.strip()]

    if configured:
        if configured not in remotes:
            raise DeployError(f"configured Git remote does not exist: {configured}")
        return configured

    branch_result = _git(
        deployment,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        capture=True,
        check=False,
        announce=False,
    )
    if branch_result.returncode == 0:
        branch = branch_result.stdout.strip()
        remote_result = _git(
            deployment,
            "config",
            "--get",
            f"branch.{branch}.remote",
            capture=True,
            check=False,
            announce=False,
        )
        branch_remote = remote_result.stdout.strip() if remote_result.returncode == 0 else ""
        if branch_remote and branch_remote != "." and branch_remote in remotes:
            return branch_remote

    if "origin" in remotes:
        return "origin"
    if len(remotes) == 1:
        return remotes[0]
    if not remotes:
        raise DeployError("no Git remote is configured for release discovery")
    raise DeployError(
        "multiple Git remotes are configured and no release remote could be selected; "
        "set ENVSBOT_DEPLOY_REMOTE explicitly"
    )


def _remote_tags(deployment: Deployment, remote: str) -> list[str]:
    result = _git(
        deployment,
        "ls-remote",
        "--tags",
        "--refs",
        "--sort=-version:refname",
        remote,
        capture=True,
        announce=False,
    )
    prefix = "refs/tags/"
    tags: list[str] = []
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or not fields[1].startswith(prefix):
            continue
        tag = fields[1][len(prefix) :].strip()
        if tag:
            tags.append(tag)
    return tags


def _latest_remote_tag(deployment: Deployment, remote: str) -> str:
    tags = [tag for tag in _remote_tags(deployment, remote) if _is_stable_release_tag(tag)]
    if not tags:
        raise DeployError(
            f"no stable Git release tags (vX.Y.Z) found on remote {remote!r}"
        )
    return tags[0]


def _remote_tag_object(deployment: Deployment, remote: str, tag: str) -> str:
    result = _git(
        deployment,
        "ls-remote",
        "--tags",
        remote,
        f"refs/tags/{tag}",
        capture=True,
        check=False,
        announce=False,
    )
    if result.returncode != 0:
        raise DeployError(f"could not query release tag {tag!r} from remote {remote!r}")
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) == 2 and fields[1] == f"refs/tags/{tag}":
            return fields[0]
    raise DeployError(f"release tag does not exist on remote {remote!r}: {tag}")


def _local_tag_object(deployment: Deployment, tag: str) -> str | None:
    result = _git(
        deployment,
        "rev-parse",
        "--verify",
        "--quiet",
        f"refs/tags/{tag}",
        capture=True,
        check=False,
        announce=False,
    )
    if result.returncode == 0:
        return result.stdout.strip() or None
    if result.returncode == 1:
        return None
    raise DeployError(f"could not inspect local release tag: {tag}")


def _sync_release_tag(deployment: Deployment, remote: str, tag: str) -> None:
    """Fetch only the selected release tag and never overwrite a conflicting tag."""
    remote_object = _remote_tag_object(deployment, remote, tag)
    local_object = _local_tag_object(deployment, tag)
    if local_object is not None:
        if local_object != remote_object:
            raise DeployError(
                f"local release tag {tag!r} conflicts with remote {remote!r}; refusing to overwrite it. "
                "Verify the tag manually, then rename/delete the incorrect local tag before retrying."
            )
        return

    _git(
        deployment,
        "fetch",
        "--no-tags",
        remote,
        f"refs/tags/{tag}:refs/tags/{tag}",
    )


def _prepare_release_target(deployment: Deployment, requested_tag: str | None) -> tuple[str, str]:
    """Refresh branches without importing every tag, then sync only the chosen release."""
    remote = _git_remote(deployment)
    _git(deployment, "fetch", "--prune", "--no-tags", remote)
    target = requested_tag or _latest_remote_tag(deployment, remote)
    _sync_release_tag(deployment, remote, target)
    _validate_tag(deployment, target)
    return remote, target


def _validate_tag(deployment: Deployment, tag: str) -> None:
    result = _git(
        deployment,
        "rev-parse",
        "--verify",
        "--quiet",
        f"refs/tags/{tag}^{{commit}}",
        capture=True,
        check=False,
        announce=False,
    )
    if result.returncode != 0:
        raise DeployError(f"release tag does not exist: {tag}")


def _git_is_ancestor(deployment: Deployment, older: str, newer: str) -> bool:
    result = _git(
        deployment,
        "merge-base",
        "--is-ancestor",
        older,
        newer,
        capture=True,
        check=False,
        announce=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise DeployError(f"could not compare Git revisions {older!r} and {newer!r}")


def _target_relation(deployment: Deployment, target: str) -> str:
    """Classify a release target relative to the currently checked-out HEAD."""
    head_before_target = _git_is_ancestor(deployment, "HEAD", target)
    target_before_head = _git_is_ancestor(deployment, target, "HEAD")
    if head_before_target and target_before_head:
        return "same"
    if head_before_target:
        return "upgrade"
    if target_before_head:
        return "downgrade"
    return "diverged"


def _head_is_detached(deployment: Deployment) -> bool:
    result = _git(
        deployment,
        "symbolic-ref",
        "--quiet",
        "HEAD",
        capture=True,
        check=False,
        announce=False,
    )
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    raise DeployError("could not determine whether the Git checkout is attached to a branch")


def _approve_update_target(
    deployment: Deployment,
    target: str,
    *,
    requested_tag: str | None,
    allow_downgrade: bool,
) -> bool:
    """Return whether the selected release should be checked out."""
    current = _current_revision(deployment)
    relation = _target_relation(deployment, target)

    if relation == "upgrade":
        _require_confirmation(f"Update {current} to {target}?")
        return True

    if relation == "same":
        if _head_is_detached(deployment):
            print(f"Already at release {target}; nothing to update.")
            return False
        _require_confirmation(
            f"Current HEAD already matches {target}. Pin this checkout to the release tag?"
        )
        return True

    if relation == "downgrade":
        if requested_tag is None:
            print(f"No newer release is available (latest release: {target}).")
            print(f"The current checkout {current} contains commits newer than {target}.")
            print("Nothing to update; the development branch is never deployed automatically.")
            return False
        if not allow_downgrade:
            raise DeployError(
                f"requested release {target} is older than the current checkout {current}; "
                "refusing downgrade (use --allow-downgrade only for an intentional rollback)"
            )
        print(
            "WARNING: this is an explicit code downgrade. The helper does not downgrade the "
            "database schema; an incompatible database will leave the service stopped."
        )
        _require_confirmation(
            f"Downgrade {current} to {target}? A matching database backup may be required."
        )
        return True

    raise DeployError(
        f"release {target} is not on the current HEAD history; refusing a non-fast-forward "
        "deployment. Resolve the Git history manually before updating."
    )


def _relative_to_root(path: Path | None, root: Path) -> bool:
    if path is None:
        return False
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _protected_paths(deployment: Deployment) -> dict[str, Path]:
    resolved = _runtime_paths(deployment)
    protected: dict[str, Path] = {"config": deployment.config, "systemd unit": deployment.unit}
    for name in ("database", "vcard", "avatar"):
        path = resolved.get(name)
        if path is None:
            continue
        if name == "avatar":
            bundled_dir = (deployment.root / "utils" / "bundled").resolve()
            try:
                path.resolve().relative_to(bundled_dir)
            except ValueError:
                pass
            else:
                continue
        protected[name] = path
    return protected


def _backup_project_protected_paths(
    deployment: Deployment,
    protected: dict[str, Path],
    backup_dir: Path,
) -> dict[str, tuple[Path, Path]]:
    backups: dict[str, tuple[Path, Path]] = {}
    for label, path in protected.items():
        if not path.exists() or not path.is_file() or not _relative_to_root(path, deployment.root):
            continue
        target = backup_dir / f"{len(backups):02d}-{path.name}"
        shutil.copy2(path, target)
        backups[label] = (path, target)
        print(f"PROTECT {label}: {path}")
    return backups


def _restore_project_protected_paths(backups: dict[str, tuple[Path, Path]]) -> None:
    for label, (path, backup) in backups.items():
        unchanged = path.is_file() and filecmp.cmp(path, backup, shallow=False)
        if unchanged:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, path)
        print(f"RESTORE protected {label}: {path}")


def _print_paths(
    deployment: Deployment,
    *,
    runtime: dict[str, Path | None] | None = None,
) -> None:
    rows: list[tuple[str, object]] = [
        ("application", deployment.root),
        ("virtualenv", deployment.venv),
        ("config", deployment.config),
        ("service", deployment.service),
        ("service user", deployment.service_user),
        ("service group", deployment.service_group),
        ("unit", deployment.unit),
    ]
    if runtime:
        rows.extend(
            (name.replace("_", " "), runtime.get(name) or "-")
            for name in ("database", "runtime_data", "vcard", "avatar")
        )

    width = max(len(label) for label, _value in rows)
    print("Deployment paths:")
    for label, value in rows:
        print(f"  {label + ':':<{width + 1}}  {value}")

def _install_plan(deployment: Deployment) -> None:
    _print_paths(deployment)
    print("\nInstall plan:")
    print("  - keep every existing config/database/vCard/operator-avatar/systemd unit file")
    print("  - create/reuse the configured virtualenv and install constrained dependencies")
    print("  - create config.py from config_sample.py only when the config is missing")
    print("  - create vcard.py from vcard_sample.py only when the configured vCard is missing")
    print("  - install a newly rendered systemd unit only when no unit exists and you confirm it")
    print("  - ask separately before starting the service")


def _finish_install(deployment: Deployment, *, stopped: bool) -> int:
    _create_venv_if_missing(deployment)
    _install_dependencies(deployment)
    created_config = _copy_if_missing(
        deployment.root / "config_sample.py", deployment.config, deployment, mode=0o600
    )
    if created_config:
        print(
            "\nConfiguration was created but not guessed or edited. "
            f"Edit {deployment.config} and rerun './scripts/deploy.sh install'."
        )
        print("No database, vCard or systemd unit was changed after creating the config.")
        if stopped:
            print(f"LEAVE {deployment.service} stopped until the new configuration has been reviewed.")
        return 0

    _envsbot(deployment, "--check")
    runtime = _runtime_paths(deployment)
    vcard = runtime.get("vcard")
    if vcard is not None:
        _copy_if_missing(deployment.root / "vcard_sample.py", vcard, deployment, mode=0o600)
    for label in ("database", "avatar"):
        path = runtime.get(label)
        if path is not None and path.exists():
            print(f"KEEP existing {label}: {path}")

    _envsbot(
        deployment,
        "systemd",
        "check",
        "--user",
        deployment.service_user,
        "--group",
        deployment.service_group,
    )

    if deployment.unit.exists() or _systemctl_exists(deployment):
        print(f"KEEP existing systemd service file for {deployment.service}; it will not be replaced.")
    elif _confirm(f"Install a new systemd unit at {deployment.unit}?"):
        rendered = _envsbot(
            deployment,
            "systemd",
            "render",
            "--user",
            deployment.service_user,
            "--group",
            deployment.service_group,
            capture=True,
        ).stdout
        deployment.unit.parent.mkdir(parents=True, exist_ok=True)
        try:
            with deployment.unit.open("x", encoding="utf-8") as unit_file:
                unit_file.write(rendered)
        except FileExistsError:
            print(f"KEEP existing {deployment.unit}; it appeared before installation completed.")
        else:
            deployment.unit.chmod(0o644)
            print(f"CREATE {deployment.unit}")
            if shutil.which("systemd-analyze"):
                try:
                    _run(["systemd-analyze", "verify", deployment.unit])
                except DeployError:
                    deployment.unit.unlink(missing_ok=True)
                    print(f"REMOVE invalid newly created unit {deployment.unit}", file=sys.stderr)
                    raise
            _run(["systemctl", "daemon-reload"])
    else:
        print("SKIP systemd unit installation (operator choice)")

    _ask_start(deployment)
    return 0


def install(deployment: Deployment) -> int:
    _require_source_tree(deployment)
    _install_plan(deployment)
    if deployment.dry_run:
        print("\nDRY RUN: no files, packages or services were changed.")
        return 0
    _require_confirmation("Proceed with the envsbot installation shown above?")
    if not _account_exists(deployment.service_user):
        raise DeployError(
            f"service user {deployment.service_user!r} does not exist; create it manually or use --user"
        )
    stopped = _stop_active_service(
        deployment, reason="before installing dependencies and deployment files"
    )
    try:
        return _finish_install(deployment, stopped=stopped)
    except Exception:
        if stopped:
            print(
                f"\nINSTALL FAILED: {deployment.service} was stopped and will remain stopped.",
                file=sys.stderr,
            )
        raise

def _update_plan(deployment: Deployment, requested_tag: str | None) -> None:
    runtime = _runtime_paths(deployment) if deployment.venv_python.is_file() and deployment.config.exists() else None
    _print_paths(deployment, runtime=runtime)
    print("\nUpdate plan:")
    print(f"  current: {_current_revision(deployment)}")
    print(f"  target:  {requested_tag or 'newest stable vX.Y.Z release (resolved after Git query)'}")
    print("  - require a clean tracked Git worktree")
    print("  - preserve config/database/vCard/operator-avatar/systemd unit files")
    print("  - ask before stopping an active service")
    print(
        "  - query stable vX.Y.Z release tags from the configured Git remote "
        "without overwriting unrelated local tags"
    )
    print("  - fetch and checkout only the selected release tag (never deploy main automatically)")
    print("  - refuse automatic downgrades; explicit older --to tags require --allow-downgrade")
    print("  - install dependencies using the matching Python constraint snapshot")
    print("  - run db status, migration dry-run, verified db backup, migrate and db check")
    print("  - run envsbot --check and envsbot systemd check")
    print("  - ask separately before starting the service")


def update(
    deployment: Deployment,
    requested_tag: str | None,
    *,
    allow_downgrade: bool = False,
) -> int:
    _require_source_tree(deployment)
    if not (deployment.root / ".git").exists():
        raise DeployError(f"update requires a Git checkout: {deployment.root}")
    if not deployment.envsbot.is_file() or not deployment.config.is_file():
        raise DeployError("existing virtualenv/envsbot executable and runtime config are required for update")
    _require_clean_tracked_tree(deployment)
    _update_plan(deployment, requested_tag)
    if deployment.dry_run:
        print("\nDRY RUN: no Git refs, files, packages, database or services were changed.")
        return 0
    _require_confirmation("Proceed with the envsbot update plan shown above?")

    remote, target = _prepare_release_target(deployment, requested_tag)
    print(f"Selected release: {target} (remote: {remote})")
    if not _approve_update_target(
        deployment,
        target,
        requested_tag=requested_tag,
        allow_downgrade=allow_downgrade,
    ):
        return 0

    protected = _protected_paths(deployment)
    print("\nProtected operator files:")
    for label, path in protected.items():
        state = "exists" if path.exists() else "missing"
        print(f"  {label}: {path} ({state})")

    stopped = _stop_active_service(
        deployment, reason="before changing code, dependencies and database schema"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="envsbot-deploy-protect.") as temporary:
            backups = _backup_project_protected_paths(
                deployment, protected, Path(temporary)
            )
            _git(deployment, "checkout", target)
            _restore_project_protected_paths(backups)

        _install_dependencies(deployment)
        _envsbot(deployment, "db", "status")
        _envsbot(deployment, "db", "migrate", "--dry-run")
        _envsbot(deployment, "db", "backup")
        _envsbot(deployment, "db", "migrate")
        _envsbot(deployment, "db", "check")
        _envsbot(deployment, "--check")
        _envsbot(
            deployment,
            "systemd",
            "check",
            "--user",
            deployment.service_user,
            "--group",
            deployment.service_group,
        )
    except Exception:
        if stopped:
            print(
                f"\nUPDATE FAILED: {deployment.service} was stopped and will remain stopped. "
                "The helper does not automatically start old code against a possibly migrated database.",
                file=sys.stderr,
            )
        raise

    _ask_start(deployment)
    print(f"Update to {target} completed.")
    return 0


def status(deployment: Deployment) -> int:
    _require_source_tree(deployment)
    runtime = None
    if deployment.venv_python.is_file() and deployment.config.is_file():
        try:
            runtime = _runtime_paths(deployment)
        except DeployError as exc:
            print(f"Runtime paths: unavailable ({exc})")
    _print_paths(deployment, runtime=runtime)

    print("\nDeployment status:")
    status_rows: list[tuple[str, str]] = []
    if (deployment.root / ".git").exists():
        try:
            status_rows.append(("revision", _current_revision(deployment)))
            status_rows.append(("latest stable tag", _latest_tag(deployment)))
        except DeployError as exc:
            status_rows.append(("Git status", f"unavailable ({exc})"))
    if shutil.which("systemctl"):
        service_state = "active" if _service_active(deployment) else "inactive/not found"
        status_rows.append(("service state", service_state))

    if status_rows:
        width = max(len(label) for label, _value in status_rows)
        for label, value in status_rows:
            print(f"  {label + ':':<{width + 1}}  {value}")
    return 0

def check(deployment: Deployment) -> int:
    _require_source_tree(deployment)
    if not deployment.envsbot.is_file():
        raise DeployError(f"envsbot executable not found: {deployment.envsbot}")

    _envsbot(deployment, "--check", capture=True, announce=False)
    print("OK  envsbot preflight")

    _envsbot(
        deployment,
        "systemd",
        "check",
        "--user",
        deployment.service_user,
        "--group",
        deployment.service_group,
        capture=True,
        announce=False,
    )
    print("OK  systemd path and permission checks")

    if not _check_installed_systemd(deployment):
        raise DeployError(
            "installed systemd service differs from the rendered envsbot service; "
            "review the FAIL entries above"
        )
    print("OK  installed systemd service matches the rendered deployment")
    return 0

def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    options = parser.parse_args(argv)
    if options.command is None:
        parser.print_help()
        return 0
    if options.to and options.command != "update":
        parser.error("--to is only valid with the update command")
    if options.allow_downgrade and options.command != "update":
        parser.error("--allow-downgrade is only valid with the update command")
    if options.allow_downgrade and not options.to:
        parser.error("--allow-downgrade requires an explicit --to TAG")
    deployment = _deployment(options)
    try:
        if options.command == "status":
            return status(deployment)
        if options.command == "check":
            return check(deployment)
        if options.command == "install":
            return install(deployment)
        return update(deployment, options.to, allow_downgrade=options.allow_downgrade)
    except UserCancelled as exc:
        print(f"deploy: {exc}")
        return 2
    except DeployError as exc:
        print(f"deploy: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
