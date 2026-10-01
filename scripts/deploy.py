#!/usr/bin/env python3
"""Interactive, preservation-first deployment helper for envsbot.

The helper intentionally orchestrates existing envsbot deployment primitives
instead of replacing them.  A bare invocation prints help and changes nothing.
"""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from envs_xmpp_ops.deploy import InstallApplyResult

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _envs_xmpp_bootstrap import ensure_envs_xmpp  # noqa: E402

if TYPE_CHECKING:
    from envs_xmpp_ops.deploy import DeploymentTarget as _DeploymentTarget
else:
    try:
        from envs_xmpp_ops.deploy import DeploymentTarget as _DeploymentTarget
    except ImportError:
        # A bare invocation must be able to print help before the shared
        # deploy tooling is installed. Commands call ``ensure_envs_xmpp``
        # before constructing a Deployment and re-exec in a prepared venv.
        class _DeploymentTarget:
            pass

# ``deploy.sh`` executes this file directly, so Python otherwise puts only the
# ``scripts/`` directory on ``sys.path``.  Add the checkout root before loading
# the shared pure helpers; this also keeps the helper usable before envsbot is
# installed into the selected virtualenv.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[1]
if str(_CHECKOUT_ROOT) not in sys.path:
    sys.path.insert(0, str(_CHECKOUT_ROOT))

from utils.deploy_systemd_values import (  # noqa: E402
    _bool_value,
    _display_systemd_value,
    _duration_seconds,
    _environment_assignment,
    _exec_start_executable,
    _path_set,
    _resolved_path_text,
    _umask_value,
    _unit_service_values,
)


class DeployError(RuntimeError):
    """Expected deployment failure with an operator-readable message."""


class UserCancelled(DeployError):
    """Raised when an interactive action is declined."""


class Deployment(_DeploymentTarget):
    """envsbot deployment target with project-specific executable/env."""

    @property
    def envsbot(self) -> Path:
        return self.binary("envsbot")

    @property
    def environment(self) -> dict[str, str]:
        return self.environment_for("ENVSBOT_CONFIG")


_FRONTEND = None


def _frontend():
    """Return the shared deployment frontend after bootstrap has installed it."""
    global _FRONTEND
    if _FRONTEND is None:
        from envs_xmpp_ops import DeploymentFrontend

        _FRONTEND = DeploymentFrontend(
            project_name="envsbot",
            release_remote_environment="ENVSBOT_DEPLOY_REMOTE",
            error_factory=DeployError,
            cancelled_error_factory=UserCancelled,
            announce_prefix="+",
            default_cwd_to_deployment_root=False,
            service_active_capture=False,
        )
    return _FRONTEND


def _project_root() -> Path:
    return _CHECKOUT_ROOT


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
    return _frontend().systemd_property(service, prop)


def _systemd_config_path(service: str) -> Path | None:
    from envs_xmpp_ops.layout import resolve_environment_path, systemd_environment_value

    configured = systemd_environment_value(
        _systemd_property(service, "Environment"),
        "ENVSBOT_CONFIG",
    )
    return resolve_environment_path(
        configured,
        working_directory=_systemd_property(service, "WorkingDirectory"),
        fallback_directory=_project_root(),
    )


def _systemd_venv(service: str) -> Path | None:
    from envs_xmpp_ops.layout import systemd_venv

    return systemd_venv(_systemd_property(service, "ExecStart"), "envsbot")


def _default_service_account(service: str, prop: str, fallback: str) -> str:
    from envs_xmpp_ops.layout import service_account

    return service_account(
        environment=os.environ,
        environment_name=f"ENVSBOT_SERVICE_{prop.upper()}",
        discovered=_systemd_property(service, prop),
        fallback=fallback,
    )


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
    from deploy_profile import PROFILE

    root = (options.root or _project_root()).expanduser().resolve()
    service = options.service
    venv_value = options.venv or os.environ.get("ENVSBOT_VENV") or _systemd_venv(service) or root / PROFILE.venv_name
    venv = Path(venv_value).expanduser().resolve()
    config = (options.config or _default_config(root, service)).expanduser().resolve()
    user = options.user or _default_service_account(service, "User", PROFILE.service_user)
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


def _require_source_tree(deployment: Deployment) -> None:
    from envs_xmpp_ops.paths import require_source_tree

    require_source_tree(
        deployment.root,
        ("pyproject.toml", "config_sample.py", "vcard_sample.py", "scripts/deploy.sh"),
        project_name="envsbot",
        error_factory=DeployError,
    )


def _ensure_parent(path: Path, deployment: Deployment, *, mode: int = 0o750) -> None:
    if path.parent.exists():
        return
    path.parent.mkdir(parents=True, mode=mode)
    if os.geteuid() == 0 and _frontend().account_exists(deployment.service_user):
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
    if os.geteuid() == 0 and _frontend().account_exists(deployment.service_user):
        details = pwd.getpwnam(deployment.service_user)
        try:
            gid = grp.getgrnam(deployment.service_group).gr_gid
        except KeyError:
            gid = details.pw_gid
        os.chown(destination, details.pw_uid, gid)
    print(f"CREATE {destination}")
    return True


def _runtime_paths(deployment: Deployment) -> dict[str, Path | None]:
    code = r"""
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
"""
    result = _frontend().run(
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
    return _frontend().run(
        [deployment.envsbot, *args],
        deployment=deployment,
        as_service_user=True,
        capture=capture,
        cwd=deployment.root,
        announce=announce,
    )


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
    start_timeout = _duration_seconds(one("TimeoutStartSec"))
    stop_timeout = _duration_seconds(one("TimeoutStopSec"))
    if restart_delay is None or start_timeout is None or stop_timeout is None:
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
        "Start timeout": start_timeout,
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


def _actual_systemd_values(deployment: Deployment) -> dict[str, object]:
    environment = _systemd_property(deployment.service, "Environment")
    config_value = _environment_assignment(environment, "ENVSBOT_CONFIG")
    fragment = _systemd_property(deployment.service, "FragmentPath")
    working_directory = _systemd_property(deployment.service, "WorkingDirectory")
    exec_start = _exec_start_executable(_systemd_property(deployment.service, "ExecStart"))
    watchdog = _duration_seconds(_systemd_property(deployment.service, "WatchdogUSec"))
    restart_delay = _duration_seconds(_systemd_property(deployment.service, "RestartUSec"))
    start_timeout = _duration_seconds(_systemd_property(deployment.service, "TimeoutStartUSec"))
    stop_timeout = _duration_seconds(_systemd_property(deployment.service, "TimeoutStopUSec"))
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
        "Start timeout": start_timeout,
        "Stop timeout": stop_timeout,
        "UMask": _umask_value(_systemd_property(deployment.service, "UMask")),
        "NoNewPrivileges": _bool_value(_systemd_property(deployment.service, "NoNewPrivileges")),
        "PrivateTmp": _bool_value(_systemd_property(deployment.service, "PrivateTmp")),
        "PrivateDevices": _bool_value(_systemd_property(deployment.service, "PrivateDevices")),
        "ProtectSystem": _systemd_property(deployment.service, "ProtectSystem"),
        "ProtectHome": _bool_value(_systemd_property(deployment.service, "ProtectHome")),
        "ProtectKernelTunables": _bool_value(_systemd_property(deployment.service, "ProtectKernelTunables")),
        "ProtectKernelModules": _bool_value(_systemd_property(deployment.service, "ProtectKernelModules")),
        "ProtectKernelLogs": _bool_value(_systemd_property(deployment.service, "ProtectKernelLogs")),
        "ProtectControlGroups": _bool_value(_systemd_property(deployment.service, "ProtectControlGroups")),
        "RestrictSUIDSGID": _bool_value(_systemd_property(deployment.service, "RestrictSUIDSGID")),
        "LockPersonality": _bool_value(_systemd_property(deployment.service, "LockPersonality")),
        "ReadWritePaths": _path_set(_systemd_property(deployment.service, "ReadWritePaths")),
    }


def _check_installed_systemd(deployment: Deployment) -> bool:
    """Compare the desired unit with systemd's effective loaded properties."""
    if not shutil.which("systemctl"):
        raise DeployError("systemctl is required for installed service checks")
    if not _frontend().systemctl_exists(deployment):
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


def _latest_tag(deployment: Deployment) -> str:
    from envs_xmpp_ops.git import stable_release_tags

    result = _frontend().git(deployment, "tag", "--sort=-v:refname", capture=True, announce=False)
    tags = stable_release_tags([line.strip() for line in result.stdout.splitlines()])
    if not tags:
        raise DeployError("no stable Git release tags (vX.Y.Z) found")
    return tags[0]


def _approve_update_target(
    deployment: Deployment,
    target: str,
    *,
    requested_tag: str | None,
    allow_downgrade: bool,
) -> bool:
    from envs_xmpp_ops.git import approve_release_target

    current = _frontend().current_revision(deployment)
    relation = _frontend().target_relation(deployment, target)
    return approve_release_target(
        current=current,
        target=target,
        relation=relation,
        requested_tag=requested_tag,
        allow_downgrade=allow_downgrade,
        head_is_detached=_frontend().head_is_detached(deployment) if relation == "same" else False,
        require_confirmation=_frontend().require_confirmation,
        error_factory=DeployError,
    )


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


def _install_unit_if_missing(deployment: Deployment) -> None:
    from envs_xmpp_ops.systemd import install_unit_if_missing

    install_unit_if_missing(
        unit=deployment.unit,
        service=deployment.service,
        render_unit=lambda: (
            _envsbot(
                deployment,
                "systemd",
                "render",
                "--user",
                deployment.service_user,
                "--group",
                deployment.service_group,
                capture=True,
            ).stdout
        ),
        service_exists=lambda: _frontend().systemctl_exists(deployment),
        confirm=_frontend().confirm,
        run_command=_frontend().run,
    )


def _finish_install(deployment: Deployment, *, stopped: bool) -> InstallApplyResult:
    from envs_xmpp_ops.deploy import InstallApplyResult

    _frontend().create_venv_if_missing(deployment)
    _frontend().install_dependencies(deployment)
    created_config = _copy_if_missing(deployment.root / "config_sample.py", deployment.config, deployment, mode=0o600)
    if created_config:
        print(
            "\nConfiguration was created but not guessed or edited. "
            f"Edit {deployment.config} and rerun './scripts/deploy.sh install'."
        )
        print("No database, vCard or systemd unit was changed after creating the config.")
        if stopped:
            print(f"LEAVE {deployment.service} stopped until the new configuration has been reviewed.")
        return InstallApplyResult(ready_for_start=False)

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

    _install_unit_if_missing(deployment)

    return InstallApplyResult()


def install(deployment: Deployment) -> int:
    from envs_xmpp_ops.deploy import run_install_transaction

    _require_source_tree(deployment)
    _install_plan(deployment)
    if deployment.dry_run:
        print("\nDRY RUN: no files, packages or services were changed.")
        return 0

    def validate_preconditions() -> None:
        if not _frontend().account_exists(deployment.service_user):
            raise DeployError(
                f"service user {deployment.service_user!r} does not exist; create it manually or use --user"
            )

    run_install_transaction(
        confirm_install=lambda: _frontend().require_confirmation("Proceed with the envsbot installation shown above?"),
        validate_preconditions=validate_preconditions,
        stop_service=lambda: _frontend().stop_active_service(
            deployment, reason="before installing dependencies and deployment files"
        ),
        apply_install=lambda stopped: _finish_install(deployment, stopped=stopped),
        ask_start=lambda: _frontend().ask_start(deployment),
        failure_message=(f"INSTALL FAILED: {deployment.service} was stopped and will remain stopped."),
    )
    return 0


def _update_plan(deployment: Deployment, requested_tag: str | None) -> None:
    runtime = _runtime_paths(deployment) if deployment.venv_python.is_file() and deployment.config.exists() else None
    _print_paths(deployment, runtime=runtime)
    print("\nUpdate plan:")
    print(f"  current: {_frontend().current_revision(deployment)}")
    print(f"  target:  {requested_tag or 'newest stable vX.Y.Z release (resolved after Git query)'}")
    print("  - require a clean tracked Git worktree")
    print("  - preserve config/database/vCard/operator-avatar/systemd unit files")
    print("  - ask before stopping an active service")
    print(
        "  - query stable vX.Y.Z release tags from the configured Git remote without overwriting unrelated local tags"
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
    from envs_xmpp_ops.deploy import run_release_update_transaction

    _require_source_tree(deployment)
    if not (deployment.root / ".git").exists():
        raise DeployError(f"update requires a Git checkout: {deployment.root}")
    if not deployment.envsbot.is_file() or not deployment.config.is_file():
        raise DeployError("existing virtualenv/envsbot executable and runtime config are required for update")
    _frontend().require_clean_tracked_tree(deployment)
    _update_plan(deployment, requested_tag)
    if deployment.dry_run:
        print("\nDRY RUN: no Git refs, files, packages, database or services were changed.")
        return 0
    _frontend().require_confirmation("Proceed with the envsbot update plan shown above?")

    def apply_target(_target: str) -> None:
        _frontend().install_dependencies(deployment)
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

    run_release_update_transaction(
        root=deployment.root,
        prepare_target=lambda: _frontend().prepare_release_target(deployment, requested_tag),
        approve_target=lambda target: _approve_update_target(
            deployment,
            target,
            requested_tag=requested_tag,
            allow_downgrade=allow_downgrade,
        ),
        protected_paths=lambda: _protected_paths(deployment),
        stop_service=lambda: _frontend().stop_active_service(
            deployment, reason="before changing code, dependencies and database schema"
        ),
        checkout_target=lambda target: _frontend().git(deployment, "checkout", target),
        apply_target=apply_target,
        ask_start=lambda: _frontend().ask_start(deployment),
        temp_prefix="envsbot-deploy-protect.",
        announce_protected=True,
        failure_message=(
            f"UPDATE FAILED: {deployment.service} was stopped and will remain stopped. "
            "The helper does not automatically start old code against a possibly migrated database."
        ),
    )
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
            status_rows.append(("revision", _frontend().current_revision(deployment)))
            status_rows.append(("latest stable tag", _latest_tag(deployment)))
        except DeployError as exc:
            status_rows.append(("Git status", f"unavailable ({exc})"))
    if shutil.which("systemctl"):
        service_state = "active" if _frontend().service_active(deployment) else "inactive/not found"
        status_rows.append(("service state", service_state))
    if deployment.venv_python.is_file():
        try:
            status_rows.append(("dependency drift", _frontend().dependency_drift(deployment).summary()))
        except DeployError as exc:
            status_rows.append(("dependency drift", f"unavailable ({exc})"))

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
            "installed systemd service differs from the rendered envsbot service; review the FAIL entries above"
        )
    print("OK  installed systemd service matches the rendered deployment")
    _frontend().require_clean_dependency_drift(deployment)
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
    ensure_envs_xmpp()
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
