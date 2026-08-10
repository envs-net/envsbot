from __future__ import annotations

import importlib.util
import os
import pwd
import grp
import subprocess
import sys
from pathlib import Path

import pytest


_TEST_ROOT = Path(__file__).resolve().parents[1]


def _checkout_root(path: Path) -> Path:
    """Return the real checkout when tests run from mutmut's copy."""
    if path.name == "mutants":
        checkout = path.parent
        if (
            (checkout / "pyproject.toml").is_file()
            and (checkout / "scripts" / "deploy.py").is_file()
            and (checkout / "scripts" / "deploy.sh").is_file()
        ):
            return checkout
    return path


ROOT = _checkout_root(_TEST_ROOT)
DEPLOY_PATH = ROOT / "scripts" / "deploy.py"


def _load_deploy_module():
    spec = importlib.util.spec_from_file_location("envsbot_deploy_script", DEPLOY_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


deploy = _load_deploy_module()



def test_checkout_root_uses_repository_outside_mutmut_copy(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "deploy.py").write_text("# test\n", encoding="utf-8")
    (scripts / "deploy.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    mutants = tmp_path / "mutants"
    mutants.mkdir()

    assert _checkout_root(mutants) == tmp_path
    assert _checkout_root(tmp_path) == tmp_path


def _current_deployment(tmp_path: Path, *, dry_run: bool = False):
    user = pwd.getpwuid(os.getuid()).pw_name
    group = grp.getgrgid(os.getgid()).gr_name
    root = tmp_path / "envsbot"
    root.mkdir()
    return deploy.Deployment(
        root=root,
        venv=root / ".venv",
        config=tmp_path / "config.py",
        service="envsbot-test.service",
        service_user=user,
        service_group=group,
        unit=tmp_path / "envsbot-test.service",
        python="python3",
        dry_run=dry_run,
    )


def _write_source_markers(deployment) -> None:
    for name in ("pyproject.toml", "config_sample.py", "vcard_sample.py"):
        (deployment.root / name).write_text("# test\n", encoding="utf-8")
    scripts = deployment.root / "scripts"
    scripts.mkdir()
    (scripts / "deploy.sh").write_text("#!/bin/sh\n", encoding="utf-8")


def test_bare_deploy_command_only_prints_help(capsys):
    result = deploy.main([])
    output = capsys.readouterr().out

    assert result == 0

    assert "Interactive, preservation-first envsbot deployment helper" in output
    assert "{status,check,install,update}" in output
    assert "existing config, database, vCard, operator avatar and systemd unit files are kept" in output


def test_deploy_shell_wrapper_is_executable_and_defaults_to_help():
    wrapper = ROOT / "scripts" / "deploy.sh"

    executable = os.access(wrapper, os.X_OK)
    result = subprocess.run(
        [str(wrapper)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert executable is True
    assert result.returncode == 0
    assert "{status,check,install,update}" in result.stdout


def test_copy_if_missing_never_overwrites_existing_operator_file(tmp_path):
    deployment = _current_deployment(tmp_path)
    source = tmp_path / "sample.py"
    destination = tmp_path / "operator.py"
    source.write_text("new\n", encoding="utf-8")
    destination.write_text("keep\n", encoding="utf-8")

    copied = deploy._copy_if_missing(source, destination, deployment, mode=0o600)
    contents = destination.read_text(encoding="utf-8")

    assert copied is False
    assert contents == "keep\n"


def test_project_protected_files_are_restored_after_checkout_changes(tmp_path):
    deployment = _current_deployment(tmp_path)
    config = deployment.root / "config.py"
    database = deployment.root / "data" / "bot.db"
    external_vcard = tmp_path / "runtime" / "vcard.py"
    database.parent.mkdir()
    external_vcard.parent.mkdir()
    config.write_text("operator config\n", encoding="utf-8")
    database.write_bytes(b"operator database")
    external_vcard.write_text("operator vcard\n", encoding="utf-8")

    backup_dir = tmp_path / "protect"
    backup_dir.mkdir()
    backups = deploy._backup_project_protected_paths(
        deployment,
        {"config": config, "database": database, "vcard": external_vcard},
        backup_dir,
    )

    assert set(backups) == {"config", "database"}
    config.unlink()
    database.write_bytes(b"checkout replacement")
    deploy._restore_project_protected_paths(backups)

    restored_config = config.read_text(encoding="utf-8")
    restored_database = database.read_bytes()
    untouched_vcard = external_vcard.read_text(encoding="utf-8")

    assert restored_config == "operator config\n"
    assert restored_database == b"operator database"
    assert untouched_vcard == "operator vcard\n"


def test_install_dry_run_requires_no_confirmation_and_changes_nothing(tmp_path, monkeypatch, capsys):
    deployment = _current_deployment(tmp_path, dry_run=True)
    _write_source_markers(deployment)
    monkeypatch.setattr(deploy, "_confirm", lambda _prompt: pytest.fail("dry-run must not prompt"))

    result = deploy.install(deployment)

    assert result == 0
    assert not deployment.config.exists()
    assert not deployment.venv.exists()
    output = capsys.readouterr().out
    assert "DRY RUN" in output


def test_install_preserves_existing_config_database_vcard_avatar_and_unit(tmp_path, monkeypatch):
    deployment = _current_deployment(tmp_path)
    _write_source_markers(deployment)
    deployment.config.write_text("existing config\n", encoding="utf-8")
    database = tmp_path / "bot.db"
    vcard = tmp_path / "vcard.py"
    avatar = tmp_path / "avatar.jpg"
    database.write_bytes(b"existing db")
    vcard.write_text("existing vcard\n", encoding="utf-8")
    avatar.write_bytes(b"existing avatar")
    deployment.unit.write_text("existing unit\n", encoding="utf-8")

    monkeypatch.setattr(deploy, "_confirm", lambda _prompt: True)
    monkeypatch.setattr(deploy, "_stop_active_service", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(deploy, "_account_exists", lambda _user: True)
    monkeypatch.setattr(deploy, "_create_venv_if_missing", lambda _deployment: None)
    monkeypatch.setattr(deploy, "_install_dependencies", lambda _deployment: None)
    monkeypatch.setattr(
        deploy,
        "_envsbot",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        deploy,
        "_runtime_paths",
        lambda _deployment: {
            "database": database,
            "runtime_data": tmp_path,
            "vcard": vcard,
            "avatar": avatar,
        },
    )
    monkeypatch.setattr(deploy, "_systemctl_exists", lambda _deployment: True)
    monkeypatch.setattr(deploy, "_ask_start", lambda _deployment: None)

    result = deploy.install(deployment)
    config_contents = deployment.config.read_text(encoding="utf-8")

    assert result == 0
    assert config_contents == "existing config\n"
    database_contents = database.read_bytes()
    vcard_contents = vcard.read_text(encoding="utf-8")
    avatar_contents = avatar.read_bytes()
    unit_contents = deployment.unit.read_text(encoding="utf-8")

    assert database_contents == b"existing db"
    assert vcard_contents == "existing vcard\n"
    assert avatar_contents == b"existing avatar"
    assert unit_contents == "existing unit\n"


def test_update_dry_run_does_not_fetch_stop_or_change_files(tmp_path, monkeypatch, capsys):
    deployment = _current_deployment(tmp_path, dry_run=True)
    _write_source_markers(deployment)
    (deployment.root / ".git").mkdir()
    (deployment.venv / "bin").mkdir(parents=True)
    deployment.envsbot.write_text("#!/bin/sh\n", encoding="utf-8")
    deployment.config.write_text("config\n", encoding="utf-8")

    monkeypatch.setattr(deploy, "_require_clean_tracked_tree", lambda _deployment: None)
    monkeypatch.setattr(deploy, "_update_plan", lambda _deployment, _tag: print("PLAN"))
    monkeypatch.setattr(deploy, "_git", lambda *_args, **_kwargs: pytest.fail("dry-run must not fetch"))
    monkeypatch.setattr(deploy, "_stop_active_service", lambda _deployment: pytest.fail("dry-run must not stop"))

    result = deploy.update(deployment, "v1.8.0")
    config_contents = deployment.config.read_text(encoding="utf-8")

    assert result == 0
    assert config_contents == "config\n"
    assert "DRY RUN" in capsys.readouterr().out


def test_protected_paths_skip_packaged_default_avatar(tmp_path, monkeypatch):
    deployment = _current_deployment(tmp_path)
    bundled = deployment.root / "utils" / "bundled" / "avatar.jpg"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"package asset")
    database = tmp_path / "bot.db"
    vcard = tmp_path / "vcard.py"

    monkeypatch.setattr(
        deploy,
        "_runtime_paths",
        lambda _deployment: {
            "database": database,
            "runtime_data": tmp_path,
            "vcard": vcard,
            "avatar": bundled,
        },
    )

    protected = deploy._protected_paths(deployment)

    assert protected["database"] == database
    assert protected["vcard"] == vcard
    assert "avatar" not in protected


def test_deployment_docs_keep_helper_and_manual_workflows():
    deployment_doc = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Interactive deployment helper (optional)" in deployment_doc
    assert "## Manual updates" in deployment_doc
    assert "sudo systemctl stop envsbot.service" in deployment_doc
    assert "envsbot db migrate --dry-run" in deployment_doc
    assert "without\na command only prints its help" in deployment_doc
    assert "existing systemd service/unit is **never overwritten**" in deployment_doc
    assert "currently loaded by systemd" in deployment_doc
    assert "envsbot systemd render" in deployment_doc
    assert "never deploys `main`" in deployment_doc
    assert "--allow-downgrade" in deployment_doc
    assert "./scripts/deploy.sh update --dry-run" in readme
    assert "never deploy `main`" in readme
    assert "--allow-downgrade" in readme
    assert "## Updating" in readme


def test_deployment_discovers_existing_systemd_paths(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    venv = tmp_path / "custom-venv"
    config = tmp_path / "etc" / "bot.py"
    unit = tmp_path / "units" / "custom.service"

    values = {
        "User": "bot-user",
        "Group": "bot-group",
        "ExecStart": f"{{ path={venv}/bin/envsbot ; argv[]={venv}/bin/envsbot ; }}",
        "Environment": f"PYTHONUNBUFFERED=1 ENVSBOT_CONFIG={config}",
        "FragmentPath": str(unit),
    }
    monkeypatch.delenv("ENVSBOT_CONFIG", raising=False)
    monkeypatch.delenv("ENVSBOT_VENV", raising=False)
    monkeypatch.delenv("ENVSBOT_SYSTEMD_UNIT", raising=False)
    monkeypatch.setattr(deploy, "_systemd_property", lambda _service, prop: values.get(prop, ""))

    parser = deploy._build_parser()
    options = parser.parse_args(["status", "--root", str(root), "--service", "custom.service"])
    deployment = deploy._deployment(options)

    assert deployment.venv == venv.resolve()
    assert deployment.config == config.resolve()
    assert deployment.unit == unit.resolve()
    assert deployment.service_user == "bot-user"
    assert deployment.service_group == "bot-group"


def test_install_confirmation_decline_changes_nothing(tmp_path, monkeypatch):
    deployment = _current_deployment(tmp_path)
    _write_source_markers(deployment)
    monkeypatch.setattr(deploy, "_confirm", lambda _prompt: False)
    monkeypatch.setattr(
        deploy,
        "_account_exists",
        lambda _user: pytest.fail("account check must happen only after install confirmation"),
    )

    with pytest.raises(deploy.UserCancelled):
        deploy.install(deployment)

    assert not deployment.config.exists()
    assert not deployment.venv.exists()


def test_stop_and_start_are_separately_confirmed(tmp_path, monkeypatch):
    deployment = _current_deployment(tmp_path)
    commands = []
    answers = iter((False, False))
    monkeypatch.setattr(deploy, "_service_active", lambda _deployment: True)
    monkeypatch.setattr(deploy, "_confirm", lambda _prompt: next(answers))
    monkeypatch.setattr(deploy, "_run", lambda args, **_kwargs: commands.append(tuple(args)))

    with pytest.raises(deploy.UserCancelled):
        deploy._stop_active_service(deployment, reason="before update")

    assert commands == []

    monkeypatch.setattr(deploy, "_systemctl_exists", lambda _deployment: True)
    monkeypatch.setattr(deploy, "_service_active", lambda _deployment: False)
    deploy._ask_start(deployment)

    assert commands == []


def test_status_is_quiet_and_formats_labels_unambiguously(tmp_path, monkeypatch, capsys):
    deployment = _current_deployment(tmp_path)
    _write_source_markers(deployment)
    (deployment.root / ".git").mkdir()
    (deployment.venv / "bin").mkdir(parents=True)
    deployment.venv_python.write_text("", encoding="utf-8")
    deployment.config.write_text("# config\n", encoding="utf-8")

    monkeypatch.setattr(
        deploy,
        "_runtime_paths",
        lambda _deployment: {
            "database": tmp_path / "bot.db",
            "runtime_data": tmp_path / "runtime",
            "vcard": tmp_path / "runtime" / "vcard.py",
            "avatar": deployment.root / "utils" / "bundled" / "avatar.jpg",
        },
    )
    monkeypatch.setattr(deploy, "_current_revision", lambda _deployment: "v1.7.3-58-gabcdef")
    monkeypatch.setattr(deploy, "_latest_tag", lambda _deployment: "v1.7.3")
    monkeypatch.setattr(deploy, "_service_active", lambda _deployment: True)
    monkeypatch.setattr(deploy.shutil, "which", lambda name: "/bin/systemctl" if name == "systemctl" else None)

    result = deploy.status(deployment)
    output = capsys.readouterr().out

    assert result == 0
    assert "\n+ " not in output
    assert "database:" in output
    assert "runtime data:" in output
    assert "latest local tag:" in output
    assert "service state:" in output
    output_without_latest = output.replace("latest local tag:", "")
    assert "local tag:" not in output_without_latest


def test_actual_systemd_values_normalize_effective_properties(tmp_path, monkeypatch):
    deployment = _current_deployment(tmp_path)
    expected_paths = {
        str((tmp_path / "etc").resolve()),
        str((tmp_path / "var").resolve()),
    }
    properties = {
        "Environment": f"PYTHONUNBUFFERED=1 ENVSBOT_CONFIG={deployment.config}",
        "FragmentPath": str(deployment.unit),
        "User": deployment.service_user,
        "Group": deployment.service_group,
        "WorkingDirectory": str(deployment.root),
        "ExecStart": (
            f"{{ path={deployment.envsbot} ; argv[]={deployment.envsbot} ; "
            "ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }}"
        ),
        "Type": "notify",
        "NotifyAccess": "main",
        "Restart": "on-failure",
        "RestartUSec": "5s",
        "WatchdogUSec": "1min",
        "TimeoutStopUSec": "45s",
        "UMask": "0077",
        "NoNewPrivileges": "true",
        "PrivateTmp": "yes",
        "PrivateDevices": "yes",
        "ProtectSystem": "strict",
        "ProtectHome": "yes",
        "ProtectKernelTunables": "yes",
        "ProtectKernelModules": "yes",
        "ProtectKernelLogs": "yes",
        "ProtectControlGroups": "yes",
        "RestrictSUIDSGID": "yes",
        "LockPersonality": "yes",
        "ReadWritePaths": f"{tmp_path / 'var'} {tmp_path / 'etc'}",
    }
    monkeypatch.setattr(
        deploy,
        "_systemd_property",
        lambda _service, prop: properties.get(prop, ""),
    )

    values = deploy._actual_systemd_values(deployment)

    expected_unit = str(deployment.unit.resolve())
    expected_exec = str(deployment.envsbot.resolve())
    expected_config = str(deployment.config.resolve())
    assert values["Unit file"] == expected_unit
    assert values["ExecStart"] == expected_exec
    assert values["ENVSBOT_CONFIG"] == expected_config
    assert values["Type"] == "notify"
    assert values["NotifyAccess"] == "main"
    assert values["Restart delay"] == 5.0
    assert values["Watchdog"] == 60.0
    assert values["Stop timeout"] == 45.0
    assert values["UMask"] == 0o077
    assert values["ProtectHome"] is True
    assert values["PrivateTmp"] is True
    assert values["NoNewPrivileges"] is True
    assert values["LockPersonality"] is True
    assert values["ReadWritePaths"] == expected_paths



def test_desired_systemd_values_are_derived_from_rendered_unit(tmp_path, monkeypatch):
    deployment = _current_deployment(tmp_path)
    writable_a = tmp_path / "runtime"
    writable_b = tmp_path / "logs"
    rendered = f"""[Service]
Type=notify
NotifyAccess=main
User={deployment.service_user}
Group={deployment.service_group}
WorkingDirectory={deployment.root}
Environment=PYTHONUNBUFFERED=1
Environment=ENVSBOT_CONFIG={deployment.config}
ExecStart={deployment.envsbot}
Restart=on-failure
RestartSec=5
WatchdogSec=60
TimeoutStopSec=45
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths={writable_a} {writable_b}
"""

    monkeypatch.setattr(
        deploy,
        "_envsbot",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=rendered, stderr=""
        ),
    )

    values = deploy._desired_systemd_values(deployment)

    assert values["Unit file"] == str(deployment.unit)
    assert values["Type"] == "notify"
    assert values["NotifyAccess"] == "main"
    assert values["Watchdog"] == 60.0
    assert values["Restart delay"] == 5.0
    assert values["Stop timeout"] == 45.0
    assert values["UMask"] == 0o077
    assert values["PrivateDevices"] is True
    assert values["ProtectSystem"] == "strict"
    expected_writable = {
        str(writable_a.resolve()),
        str(writable_b.resolve()),
    }
    assert values["ReadWritePaths"] == expected_writable


def test_installed_systemd_check_reports_effective_mismatch(tmp_path, monkeypatch, capsys):
    deployment = _current_deployment(tmp_path)
    desired = {
        "Unit file": str(deployment.unit),
        "User": deployment.service_user,
        "Group": deployment.service_group,
        "WorkingDirectory": str(deployment.root),
        "ExecStart": str(deployment.envsbot),
        "ENVSBOT_CONFIG": str(deployment.config),
        "Restart": "on-failure",
        "Watchdog": 60.0,
        "ProtectSystem": "strict",
        "ProtectHome": True,
        "NoNewPrivileges": True,
        "ReadWritePaths": {str(tmp_path.resolve())},
    }
    actual = dict(desired)
    actual["Watchdog"] = 0.0
    actual["ProtectSystem"] = "full"

    monkeypatch.setattr(deploy.shutil, "which", lambda _name: "/bin/systemctl")
    monkeypatch.setattr(deploy, "_systemctl_exists", lambda _deployment: True)
    monkeypatch.setattr(deploy, "_desired_systemd_values", lambda _deployment: desired)
    monkeypatch.setattr(deploy, "_actual_systemd_values", lambda _deployment: actual)

    ok = deploy._check_installed_systemd(deployment)
    output = capsys.readouterr().out

    assert ok is False
    assert "FAIL  Watchdog: 0s" in output
    assert "expected: 60s" in output
    assert "FAIL  ProtectSystem: full" in output
    assert "expected: strict" in output


def test_deploy_check_is_compact_and_fails_on_installed_unit_drift(
    tmp_path, monkeypatch, capsys
):
    deployment = _current_deployment(tmp_path)
    _write_source_markers(deployment)
    (deployment.venv / "bin").mkdir(parents=True)
    deployment.envsbot.write_text("#!/bin/sh\n", encoding="utf-8")

    calls = []

    def fake_envsbot(_deployment, *args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess([], 0, stdout="verbose internal output\n", stderr="")

    monkeypatch.setattr(deploy, "_envsbot", fake_envsbot)
    monkeypatch.setattr(deploy, "_check_installed_systemd", lambda _deployment: False)

    with pytest.raises(deploy.DeployError, match="differs from the rendered envsbot service"):
        deploy.check(deployment)

    output = capsys.readouterr().out
    assert "verbose internal output" not in output
    assert "OK  envsbot preflight" in output
    assert "OK  systemd path and permission checks" in output
    assert all(kwargs.get("capture") is True for _args, kwargs in calls)
    assert all(kwargs.get("announce") is False for _args, kwargs in calls)


def test_deploy_check_succeeds_when_effective_service_matches(
    tmp_path, monkeypatch, capsys
):
    deployment = _current_deployment(tmp_path)
    _write_source_markers(deployment)
    (deployment.venv / "bin").mkdir(parents=True)
    deployment.envsbot.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(
        deploy,
        "_envsbot",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(deploy, "_check_installed_systemd", lambda _deployment: True)

    result = deploy.check(deployment)
    output = capsys.readouterr().out

    assert result == 0
    assert "OK  installed systemd service matches the rendered deployment" in output


def test_read_write_path_normalization_keeps_systemd_prefix_semantics(tmp_path):
    plain = tmp_path / "plain"
    optional = tmp_path / "optional"

    paths = deploy._path_set(f"{plain} -{optional}")

    expected_plain = str(plain.resolve())
    expected_optional = f"-{optional.resolve()}"
    assert expected_plain in paths
    assert expected_optional in paths


@pytest.mark.parametrize(
    ("head_before_target", "target_before_head", "expected"),
    (
        (True, True, "same"),
        (True, False, "upgrade"),
        (False, True, "downgrade"),
        (False, False, "diverged"),
    ),
)
def test_target_relation_uses_git_ancestry(
    tmp_path,
    monkeypatch,
    head_before_target,
    target_before_head,
    expected,
):
    deployment = _current_deployment(tmp_path)

    def fake_is_ancestor(_deployment, older, newer):
        if (older, newer) == ("HEAD", "v1.8.0"):
            return head_before_target
        if (older, newer) == ("v1.8.0", "HEAD"):
            return target_before_head
        raise AssertionError(f"unexpected ancestry comparison: {older} -> {newer}")

    monkeypatch.setattr(deploy, "_git_is_ancestor", fake_is_ancestor)

    relation = deploy._target_relation(deployment, "v1.8.0")

    assert relation == expected


def test_automatic_update_refuses_latest_release_behind_current_head(
    tmp_path,
    monkeypatch,
    capsys,
):
    deployment = _current_deployment(tmp_path)
    _write_source_markers(deployment)
    (deployment.root / ".git").mkdir()
    (deployment.venv / "bin").mkdir(parents=True)
    deployment.envsbot.write_text("#!/bin/sh\n", encoding="utf-8")
    deployment.config.write_text("# config\n", encoding="utf-8")
    git_calls = []

    monkeypatch.setattr(deploy, "_require_clean_tracked_tree", lambda _deployment: None)
    monkeypatch.setattr(deploy, "_update_plan", lambda _deployment, _tag: None)
    monkeypatch.setattr(deploy, "_confirm", lambda _prompt: True)
    monkeypatch.setattr(deploy, "_latest_tag", lambda _deployment: "v1.7.3")
    monkeypatch.setattr(deploy, "_validate_tag", lambda _deployment, _tag: None)
    monkeypatch.setattr(deploy, "_current_revision", lambda _deployment: "v1.7.3-60-gabcdef")
    monkeypatch.setattr(deploy, "_target_relation", lambda _deployment, _tag: "downgrade")
    monkeypatch.setattr(
        deploy,
        "_git",
        lambda _deployment, *args, **_kwargs: git_calls.append(args)
        or subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        deploy,
        "_protected_paths",
        lambda _deployment: pytest.fail("no operator files should be prepared without an upgrade"),
    )
    monkeypatch.setattr(
        deploy,
        "_stop_active_service",
        lambda *_args, **_kwargs: pytest.fail("service must not stop without an upgrade"),
    )

    result = deploy.update(deployment, None)
    output = capsys.readouterr().out

    assert result == 0
    assert git_calls == [("fetch", "--tags", "--prune")]
    assert "No newer release is available (latest release: v1.7.3)." in output
    assert "contains commits newer than v1.7.3" in output
    assert "development branch is never deployed automatically" in output


def test_explicit_older_release_requires_allow_downgrade(tmp_path, monkeypatch):
    deployment = _current_deployment(tmp_path)
    monkeypatch.setattr(deploy, "_current_revision", lambda _deployment: "v1.8.0")
    monkeypatch.setattr(deploy, "_target_relation", lambda _deployment, _tag: "downgrade")
    monkeypatch.setattr(
        deploy,
        "_confirm",
        lambda _prompt: pytest.fail("refused downgrade must not prompt for approval"),
    )

    with pytest.raises(deploy.DeployError, match="refusing downgrade"):
        deploy._approve_update_target(
            deployment,
            "v1.7.3",
            requested_tag="v1.7.3",
            allow_downgrade=False,
        )


def test_explicit_downgrade_requires_additional_warning_confirmation(
    tmp_path,
    monkeypatch,
    capsys,
):
    deployment = _current_deployment(tmp_path)
    prompts = []
    monkeypatch.setattr(deploy, "_current_revision", lambda _deployment: "v1.8.0")
    monkeypatch.setattr(deploy, "_target_relation", lambda _deployment, _tag: "downgrade")
    monkeypatch.setattr(deploy, "_confirm", lambda prompt: prompts.append(prompt) or True)

    approved = deploy._approve_update_target(
        deployment,
        "v1.7.3",
        requested_tag="v1.7.3",
        allow_downgrade=True,
    )
    output = capsys.readouterr().out

    assert approved is True
    assert len(prompts) == 1
    assert prompts[0].startswith("Downgrade v1.8.0 to v1.7.3?")
    assert "explicit code downgrade" in output
    assert "does not downgrade the database schema" in output


def test_same_release_commit_on_branch_is_pinned_to_tag(tmp_path, monkeypatch):
    deployment = _current_deployment(tmp_path)
    prompts = []
    monkeypatch.setattr(deploy, "_current_revision", lambda _deployment: "v1.8.0")
    monkeypatch.setattr(deploy, "_target_relation", lambda _deployment, _tag: "same")
    monkeypatch.setattr(deploy, "_head_is_detached", lambda _deployment: False)
    monkeypatch.setattr(deploy, "_confirm", lambda prompt: prompts.append(prompt) or True)

    approved = deploy._approve_update_target(
        deployment,
        "v1.8.0",
        requested_tag=None,
        allow_downgrade=False,
    )

    assert approved is True
    assert prompts == ["Current HEAD already matches v1.8.0. Pin this checkout to the release tag?"]


def test_same_release_commit_already_detached_is_noop(tmp_path, monkeypatch, capsys):
    deployment = _current_deployment(tmp_path)
    monkeypatch.setattr(deploy, "_current_revision", lambda _deployment: "v1.8.0")
    monkeypatch.setattr(deploy, "_target_relation", lambda _deployment, _tag: "same")
    monkeypatch.setattr(deploy, "_head_is_detached", lambda _deployment: True)
    monkeypatch.setattr(
        deploy,
        "_confirm",
        lambda _prompt: pytest.fail("already pinned release must not prompt"),
    )

    approved = deploy._approve_update_target(
        deployment,
        "v1.8.0",
        requested_tag=None,
        allow_downgrade=False,
    )
    output = capsys.readouterr().out

    assert approved is False
    assert "Already at release v1.8.0; nothing to update." in output


def test_diverged_release_history_is_refused(tmp_path, monkeypatch):
    deployment = _current_deployment(tmp_path)
    monkeypatch.setattr(deploy, "_current_revision", lambda _deployment: "feature-abcdef")
    monkeypatch.setattr(deploy, "_target_relation", lambda _deployment, _tag: "diverged")

    with pytest.raises(deploy.DeployError, match="non-fast-forward deployment"):
        deploy._approve_update_target(
            deployment,
            "v1.8.0",
            requested_tag="v1.8.0",
            allow_downgrade=False,
        )


def test_allow_downgrade_cli_requires_explicit_update_target(capsys):
    with pytest.raises(SystemExit) as exc_info:
        deploy.main(["update", "--allow-downgrade"])

    assert exc_info.value.code == 2
    assert "--allow-downgrade requires an explicit --to TAG" in capsys.readouterr().err


def test_git_helper_forwards_nonchecking_mode(tmp_path, monkeypatch):
    deployment = _current_deployment(tmp_path)
    observed = {}

    def fake_run(args, **kwargs):
        observed["args"] = args
        observed["check"] = kwargs["check"]
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

    monkeypatch.setattr(deploy, "_run", fake_run)

    result = deploy._git(
        deployment,
        "rev-parse",
        "--verify",
        "missing",
        capture=True,
        check=False,
        announce=False,
    )

    assert result.returncode == 1
    assert observed["args"] == ["git", "rev-parse", "--verify", "missing"]
    assert observed["check"] is False
