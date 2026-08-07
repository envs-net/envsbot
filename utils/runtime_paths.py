"""Resolve mutable support files outside the read-only application tree."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from utils.config.defaults import BASE_DIR


def _resolve(value: object) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def runtime_data_dir(config: Mapping[str, Any]) -> Path:
    """Return the directory for mutable non-database runtime support files.

    The setting is explicit for hardened installs so moving ``DB_FILE`` never
    silently moves unrelated operator-managed files.  When
    ``RUNTIME_DATA_DIR`` is unset, the historical application-root location is
    retained for backwards compatibility.
    """
    configured = config.get("runtime_data_dir")
    if isinstance(configured, str) and configured.strip():
        return _resolve(configured)
    return BASE_DIR.resolve()


def vcard_file(config: Mapping[str, Any]) -> Path:
    return runtime_data_dir(config) / "vcard.py"


def chat_slang_file(config: Mapping[str, Any]) -> Path:
    return runtime_data_dir(config) / "chat_slang.csv"


def chat_slang_additions_file(config: Mapping[str, Any]) -> Path:
    return runtime_data_dir(config) / "slang_additions.csv"


def chat_slang_removals_file(config: Mapping[str, Any]) -> Path:
    return runtime_data_dir(config) / "slang_removals.csv"


def profile_state_file(config: Mapping[str, Any], name: str) -> Path:
    """Return one writable profile-state marker below the runtime directory."""
    return runtime_data_dir(config) / name
