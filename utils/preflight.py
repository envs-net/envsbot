"""Local preflight checks for envsbot deployments."""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from database.manager import DatabaseManager
from database.migrations import (
    available_migrations,
    migration_catalog_fingerprint,
    migration_checksum,
)
from utils.bundled_assets import resolve_bundled_asset
from utils.config import (
    ConfigError,
    collect_config_warnings,
    get_runtime_config_path,
    load_default_config_for_diff,
    validate_startup_config,
)
from utils.file_security import (
    ensure_private_directory,
    format_mode,
    has_group_or_other_access,
    sensitive_permission_targets,
)
from utils.plugin_metadata import validate_plugin_metadata
from utils.redaction import redact_text

log = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _runtime_path(value: Any) -> Path:
    """Resolve runtime resource paths relative to the project root."""
    path = Path(str(value))
    return path if path.is_absolute() else _PROJECT_ROOT / path


async def _check_database(config: Mapping[str, Any]) -> tuple[bool, str]:
    path = config.get("db", "bot.db")
    db = DatabaseManager(str(path))
    try:
        await db.connect(
            run_migrations=False,
            start_background=False,
            enforce_schema_compatibility=False,
        )
        integrity = await db.integrity_check()
        ok = bool(integrity) and str(integrity[0]).lower() == "ok"
        migration_status = await db.migration_status()
        pending = migration_status.get("pending", [])
        unknown = migration_status.get("unknown", [])
        changed = migration_status.get("checksum_mismatches", [])
        await db.verify_read_write()
        suffix_parts = []
        if pending:
            suffix_parts.append(f"pending_migrations={','.join(pending)}")
        if unknown:
            suffix_parts.append(f"unknown_migrations={','.join(unknown)}")
            ok = False
        if changed:
            suffix_parts.append(f"changed_migrations={','.join(changed)}")
            ok = False
        suffix = f", {', '.join(suffix_parts)}" if suffix_parts else ""
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
        if not commands:
            return False, "command registry: no decorated commands found"
        missing = [
            str(getattr(cmd, "name", "") or "<unnamed>")
            for _plugin, _meta, cmd in commands
            if not str(getattr(cmd, "short", "") or "").strip()
            or not str(getattr(cmd, "usage", "") or "").strip()
        ]
    except Exception as exc:
        return False, f"command registry: {type(exc).__name__}: {redact_text(exc)}"
    if missing:
        return False, f"command registry: missing metadata for {', '.join(missing[:5])}"
    return True, f"command registry: {len(commands)} decorated commands"


def _check_command_docs() -> tuple[bool, str]:
    try:
        from utils.command_docs import validate_command_docs

        errors, command_count = validate_command_docs()
    except Exception as exc:
        return False, f"command docs: {type(exc).__name__}: {redact_text(exc)}"
    if errors:
        preview = "; ".join(errors[:3])
        if len(errors) > 3:
            preview += f"; ... ({len(errors)} errors)"
        return False, f"command docs: {preview}"
    return True, f"command docs: ok ({command_count} commands)"


def _check_config_sample(config: Mapping[str, Any]) -> tuple[bool, str]:
    try:
        sample = load_default_config_for_diff()
        missing = sorted(set(sample) - set(config))
        warnings = list(collect_config_warnings(config))
    except Exception as exc:
        return False, f"config sample: {type(exc).__name__}: {redact_text(exc)}"
    if warnings:
        return False, f"config warnings: {'; '.join(warnings[:3])}"
    if missing:
        return False, f"config sample: {len(missing)} sample key(s) absent from runtime defaults"
    return True, f"config sample: ok ({len(sample)} keys)"


def _check_backup_dir(config: Mapping[str, Any]) -> tuple[bool, str]:
    backup_dir = Path(str(config.get("backup_dir", "data/backups")))
    try:
        ensure_private_directory(backup_dir)
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
        avatar_path = resolve_bundled_asset(str(avatar), base_dir=_PROJECT_ROOT)
        checks.append(f"avatar={'ok' if avatar_path.exists() else 'missing'}")
        if not avatar_path.exists():
            return False, f"runtime files: {', '.join(checks)}"
    vcard_sample = _PROJECT_ROOT / "vcard_sample.py"
    if vcard_sample.exists():
        checks.append("vcard_sample=ok")
    return True, f"runtime files: {', '.join(checks) if checks else 'ok'}"


def _check_sensitive_permissions(config: Mapping[str, Any]) -> tuple[bool, str]:
    """Reject runtime secrets that are readable by group or other users."""
    paths = sensitive_permission_targets(
        config_path=get_runtime_config_path(),
        database_path=_runtime_path(config.get("db", "bot.db")),
        backup_directory=_runtime_path(config.get("backup_dir", "data/backups")),
    )
    unsafe = [
        f"{label}={format_mode(path)}"
        for label, path in paths
        if path.exists() and has_group_or_other_access(path)
    ]
    if unsafe:
        return False, "file permissions: group/other access: " + ", ".join(unsafe)
    return True, "file permissions: owner-only"


def _check_config_path() -> tuple[bool, str]:
    path = get_runtime_config_path()
    if path.exists():
        return True, f"config path: {path}"
    return False, f"config path: missing {path}"


def _check_migration_catalog() -> tuple[bool, str]:
    migrations = tuple(available_migrations())
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        return False, "migrations: duplicate version identifiers"
    if versions != sorted(versions):
        return False, "migrations: versions are not sorted"
    checksums = [migration_checksum(migration) for migration in migrations]
    if any(len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value) for value in checksums):
        return False, "migrations: invalid checksum"
    fingerprint = migration_catalog_fingerprint(migrations)
    return True, f"migrations: {len(versions)} known, catalog={fingerprint[:12]}"


async def collect_preflight_checks(config: Mapping[str, Any]) -> list[tuple[bool, str]]:
    """Run preflight checks and return structured results."""
    checks: list[tuple[bool, str]] = []
    try:
        validate_startup_config(config)
        checks.append((True, "config: ok"))
    except ConfigError as exc:
        checks.append((False, f"config: {redact_text(exc)}"))

    checks.append(_check_config_path())
    checks.append(_check_sensitive_permissions(config))
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
