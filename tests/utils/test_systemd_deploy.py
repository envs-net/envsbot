from __future__ import annotations

import grp
import os
import pwd
import sys
from pathlib import Path

from utils import systemd_deploy


def _current_account() -> tuple[str, str]:
    user = pwd.getpwuid(os.getuid()).pw_name
    group = grp.getgrgid(os.getgid()).gr_name
    return user, group


def test_render_systemd_unit_uses_runtime_paths(monkeypatch, tmp_path):
    project = tmp_path / "envsbot"
    project.mkdir()
    config_dir = tmp_path / "etc-envsbot"
    config_dir.mkdir()
    config_file = config_dir / "config.py"
    config_file.write_text("# test\n", encoding="utf-8")
    external_backup = tmp_path / "external-backups"
    external_backup.mkdir()
    external_logs = tmp_path / "external-logs"
    external_logs.mkdir()
    external_runtime = tmp_path / "external-runtime"
    external_runtime.mkdir()

    monkeypatch.setattr(systemd_deploy, "PROJECT_ROOT", project)
    monkeypatch.setattr(systemd_deploy, "get_runtime_config_path", lambda: config_file)
    monkeypatch.setattr(systemd_deploy, "_exec_start", lambda: "/srv/envsbot/.venv/bin/envsbot")

    unit = systemd_deploy.render_systemd_unit(
        {
            "db": "data/bot.db",
            "log_dir": str(external_logs),
            "runtime_data_dir": str(external_runtime),
            "backup_dir": str(external_backup),
            "restart_notification_file": "data/restart.json",
            "idlerpg": {"export_path": "data/idlerpg"},
        },
        user="botuser",
        group="botgroup",
        environment_file="/etc/default/envsbot-local",
    )

    assert f"WorkingDirectory={project}" in unit
    assert "ExecStart=/srv/envsbot/.venv/bin/envsbot" in unit
    assert "EnvironmentFile=-/etc/default/envsbot-local" in unit
    assert f"Environment=ENVSBOT_CONFIG={config_file}" in unit
    assert (
        f"ReadWritePaths={config_dir} {project / 'data'} {external_logs} "
        f"{external_runtime} {external_backup}"
    ) in unit
    assert f"ReadWritePaths={project} " not in unit
    assert "WatchdogSec=60" in unit
    assert "ProtectSystem=strict" in unit


def test_check_systemd_installation_validates_service_account_permissions(
    monkeypatch, tmp_path
):
    user, group = _current_account()
    project = tmp_path / "envsbot"
    project.mkdir(mode=0o700)
    (project / "data").mkdir(mode=0o700)
    (project / "data" / "backups").mkdir(mode=0o700)
    (project / "data" / "idlerpg").mkdir(mode=0o700)
    (project / "logs").mkdir(mode=0o700)
    config_dir = tmp_path / "etc-envsbot"
    config_dir.mkdir(mode=0o700)
    config_file = config_dir / "config.py"
    config_file.write_text("# test\n", encoding="utf-8")
    config_file.chmod(0o600)

    monkeypatch.setattr(systemd_deploy, "PROJECT_ROOT", project)
    monkeypatch.setattr(systemd_deploy, "get_runtime_config_path", lambda: config_file)
    monkeypatch.setattr(systemd_deploy, "_exec_start", lambda: sys.executable)

    status, output = systemd_deploy.check_systemd_installation(
        {
            "db": "data/bot.db",
            "runtime_data_dir": "data",
            "backup_dir": "data/backups",
            "restart_notification_file": "data/restart.json",
            "idlerpg": {"export_path": "data/idlerpg"},
        },
        user=user,
        group=group,
    )

    assert status == 0
    assert "FAIL" not in output
    assert "Rendered unit:" in output
    assert f"User: {user}" in output


def test_systemd_check_rejects_writable_application_tree(monkeypatch, tmp_path):
    user, group = _current_account()
    project = tmp_path / "envsbot"
    project.mkdir(mode=0o700)
    config_file = project / "config.py"
    config_file.write_text("# test\n", encoding="utf-8")
    config_file.chmod(0o600)

    monkeypatch.setattr(systemd_deploy, "PROJECT_ROOT", project)
    monkeypatch.setattr(systemd_deploy, "get_runtime_config_path", lambda: config_file)
    monkeypatch.setattr(systemd_deploy, "_exec_start", lambda: sys.executable)

    status, output = systemd_deploy.check_systemd_installation(
        {
            "db": "bot.db",
            "backup_dir": "data/backups",
            "restart_notification_file": "data/restart.json",
            "idlerpg": {"export_path": "data/idlerpg"},
        },
        user=user,
        group=group,
    )

    assert status == 1
    assert "FAIL  Application tree read-only" in output
