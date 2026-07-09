"""Local preflight checks for envsbot deployments."""

from __future__ import annotations

import asyncio
import importlib
import logging
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from database.manager import DatabaseManager
from database.migrations import available_migrations
from utils.config import (
    ConfigError,
    collect_config_warnings,
    get_runtime_config_path,
    load_default_config_for_diff,
    validate_startup_config,
)
from utils.plugin_metadata import validate_plugin_metadata
from utils.redaction import redact_text

log = logging.getLogger(__name__)


async def _check_database(config: Mapping[str, Any]) -> tuple[bool, str]:
    path = config.get("db", "bot.db")
    db = DatabaseManager(str(path))
    try:
        await db.connect()
        integrity = await db.integrity_check()
        ok = bool(integrity) and str(integrity[0]).lower() == "ok"
        migration_status = await db.migration_status()
        pending = migration_status.get("pending", [])
        await db.verify_read_write()
        suffix = ""
        if pending:
            suffix = f", pending_migrations={','.join(pending)}"
            ok = False
        return ok, f"database: integrity={','.join(map(str, integrity or [])) or 'unknown'}{suffix}"
    except Exception as exc:
        return False, f"database: {type(exc).__name__}: {redact_text(exc)}"
    finally:
        try:
            await db.close()
        except Exception:
            pass


def _check_imports() -> tuple[bool, str]:
    modules = ["envsbot", "core_plugins", "plugins", "utils", "database"]
    try:
        for name in modules:
            importlib.import_module(name)
        return True, "imports: ok"
    except Exception as exc:
        return False, f"imports: {type(exc).__name__}: {redact_text(exc)}"


def _check_plugin_imports_and_metadata() -> tuple[bool, str]:
    try:
        from utils.command_registry import discover_command_modules
    except Exception as exc:
        return False, f"plugins: discovery unavailable: {type(exc).__name__}: {redact_text(exc)}"

    issues: list[str] = []
    count = 0
    try:
        for name, module, source in discover_command_modules():
            count += 1
            meta = getattr(module, "PLUGIN_META", {}) or {}
            for issue in validate_plugin_metadata(name, meta, core=(source == "core")):
                issues.append(issue.format())
    except Exception as exc:
        return False, f"plugins: import failed: {type(exc).__name__}: {redact_text(exc)}"

    if issues:
        preview = "; ".join(issues[:3])
        if len(issues) > 3:
            preview += f"; ... ({len(issues)} issues)"
        return False, f"plugins: metadata issues: {preview}"
    return True, f"plugins: {count} importable, metadata ok"


def _check_command_registry() -> tuple[bool, str]:
    try:
        from utils.command_registry import decorated_command_records

        commands = decorated_command_records()
    except Exception as exc:
        return False, f"command registry: {type(exc).__name__}: {redact_text(exc)}"
    if not commands:
        return False, "command registry: no decorated commands found"
    missing = [cmd.name for _plugin, _meta, cmd in commands if not getattr(cmd, "short", "") or not getattr(cmd, "usage", "")]
    if missing:
        return False, f"command registry: missing metadata for {', '.join(missing[:5])}"
    return True, f"command registry: {len(commands)} decorated commands"


def _check_command_docs() -> tuple[bool, str]:
    script = Path("scripts/check_command_docs.py")
    if not script.exists():
        return False, "command docs: script missing"
    try:
        result = subprocess.run(
            ["python", str(script)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            return True, "command docs: ok"
        return False, "command docs: failed"
    except Exception as exc:
        return False, f"command docs: {type(exc).__name__}: {redact_text(exc)}"


def _check_config_sample(config: Mapping[str, Any]) -> tuple[bool, str]:
    try:
        sample = load_default_config_for_diff()
    except Exception as exc:
        return False, f"config sample: {type(exc).__name__}: {redact_text(exc)}"
    missing = sorted(set(sample) - set(config))
    warnings = collect_config_warnings(config)
    if warnings:
        return False, f"config warnings: {'; '.join(warnings[:3])}"
    if missing:
        return False, f"config sample: {len(missing)} sample key(s) absent from runtime defaults"
    return True, f"config sample: ok ({len(sample)} keys)"


def _check_backup_dir(config: Mapping[str, Any]) -> tuple[bool, str]:
    backup_dir = Path(str(config.get("backup_dir", "data/backups")))
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        test_file = backup_dir / ".envsbot-write-test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return True, f"backup dir: writable ({backup_dir})"
    except Exception as exc:
        return False, f"backup dir: {type(exc).__name__}: {redact_text(exc)}"


def _check_runtime_files(config: Mapping[str, Any]) -> tuple[bool, str]:
    checks: list[str] = []
    avatar = config.get("avatar")
    if avatar:
        avatar_path = Path(str(avatar))
        checks.append(f"avatar={'ok' if avatar_path.exists() else 'missing'}")
        if not avatar_path.exists():
            return False, f"runtime files: {', '.join(checks)}"
    vcard_sample = Path("vcard_sample.py")
    if vcard_sample.exists():
        checks.append("vcard_sample=ok")
    return True, f"runtime files: {', '.join(checks) if checks else 'ok'}"


def _check_config_path() -> tuple[bool, str]:
    path = get_runtime_config_path()
    if path.exists():
        return True, f"config path: {path}"
    return False, f"config path: missing {path}"


def _check_migration_catalog() -> tuple[bool, str]:
    migrations = available_migrations()
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        return False, "migrations: duplicate version identifiers"
    if versions != sorted(versions):
        return False, "migrations: versions are not sorted"
    return True, f"migrations: {len(versions)} known"


async def collect_preflight_checks(config: Mapping[str, Any]) -> list[tuple[bool, str]]:
    """Run preflight checks and return structured results."""
    checks: list[tuple[bool, str]] = []
    try:
        validate_startup_config(config)
        checks.append((True, "config: ok"))
    except ConfigError as exc:
        checks.append((False, f"config: {redact_text(exc)}"))

    checks.append(_check_config_path())
    checks.append(_check_config_sample(config))
    checks.append(_check_imports())
    checks.append(_check_plugin_imports_and_metadata())
    checks.append(_check_command_registry())
    checks.append(_check_command_docs())
    checks.append(_check_migration_catalog())
    checks.append(_check_backup_dir(config))
    checks.append(_check_runtime_files(config))
    checks.append(await _check_database(config))
    return checks


async def run_preflight(config: Mapping[str, Any]) -> int:
    """Run local checks and print a concise summary. Return shell status."""
    checks = await collect_preflight_checks(config)
    overall = all(ok for ok, _message in checks)
    print("🩺 envsbot preflight")
    for ok, message in checks:
        print(("✅" if ok else "❌"), message)
    print("Overall:", "✅ ok" if overall else "❌ failed")
    return 0 if overall else 1


if __name__ == "__main__":
    from utils.config import config

    raise SystemExit(asyncio.run(run_preflight(config)))
