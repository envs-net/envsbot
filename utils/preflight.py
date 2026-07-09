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
from utils.config import ConfigError, validate_startup_config

log = logging.getLogger(__name__)


async def _check_database(config: Mapping[str, Any]) -> tuple[bool, str]:
    path = config.get("db", "bot.db")
    db = DatabaseManager(path)
    try:
        await db.connect()
        integrity = await db.integrity_check()
        ok = bool(integrity) and str(integrity[0]).lower() == "ok"
        return ok, f"database: integrity={','.join(map(str, integrity or [])) or 'unknown'}"
    except Exception as exc:
        return False, f"database: {type(exc).__name__}: {exc}"
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
        return False, f"imports: {type(exc).__name__}: {exc}"


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
        return False, f"command docs: {type(exc).__name__}: {exc}"


def _check_backup_dir(config: Mapping[str, Any]) -> tuple[bool, str]:
    backup_dir = Path(str(config.get("backup_dir", "data/backups")))
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        test_file = backup_dir / ".envsbot-write-test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return True, f"backup dir: writable ({backup_dir})"
    except Exception as exc:
        return False, f"backup dir: {type(exc).__name__}: {exc}"


async def run_preflight(config: Mapping[str, Any]) -> int:
    """Run local checks and print a concise summary. Return shell status."""
    checks: list[tuple[bool, str]] = []
    try:
        validate_startup_config(config)
        checks.append((True, "config: ok"))
    except ConfigError as exc:
        checks.append((False, f"config: {exc}"))

    checks.append(_check_imports())
    checks.append(_check_backup_dir(config))
    checks.append(_check_command_docs())
    checks.append(await _check_database(config))

    overall = all(ok for ok, _message in checks)
    print("🩺 envsbot preflight")
    for ok, message in checks:
        print(("✅" if ok else "❌"), message)
    print("Overall:", "✅ ok" if overall else "❌ failed")
    return 0 if overall else 1


if __name__ == "__main__":
    from utils.config import config

    raise SystemExit(asyncio.run(run_preflight(config)))
