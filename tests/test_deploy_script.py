from __future__ import annotations

import importlib.util
import os
import pwd
import grp
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
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
    assert "./scripts/deploy.sh update --dry-run" in readme
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
