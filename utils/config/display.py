"""Split module for utils/config.py: display."""

from __future__ import annotations

from pathlib import Path

from envs_xmpp_core.config.changes import (
    flatten_config_value as _core_flatten_config_value,
)
from envs_xmpp_core.config.changes import (
    flattened_config_value_changes,
)

from .defaults import (
    _LOWER_TO_PYTHON_CONFIG_KEY,
    BASE_DIR,
    CONFIG_DISPLAY_SECTIONS,
    DOCUMENTED_DEFAULT_CONFIG,
    PYTHON_CONFIG_KEY_MAP,
)
from .validation import validate_config


def get_config_display_sections(cfg: dict) -> list[tuple[str, list[tuple[str, object]]]]:
    """Return config items grouped like config_sample.py for bot output."""
    seen = set()
    sections = []

    for title, python_keys in CONFIG_DISPLAY_SECTIONS:
        entries = []
        for python_key in python_keys:
            normalized_key = PYTHON_CONFIG_KEY_MAP[python_key]
            if normalized_key not in cfg:
                continue
            entries.append((python_key, cfg[normalized_key]))
            seen.add(normalized_key)
        if entries:
            sections.append((title, entries))

    extra_entries = []
    for key in sorted(k for k in cfg if k not in seen):
        display_key = _LOWER_TO_PYTHON_CONFIG_KEY.get(key, key.upper())
        extra_entries.append((display_key, cfg[key]))
    if extra_entries:
        sections.append(("Other", extra_entries))

    return sections


def _sample_config_path() -> Path:
    return BASE_DIR / "config_sample.py"


def load_default_config_for_diff() -> dict:
    """Return operator-facing documented defaults from the declarative schema."""
    defaults = DOCUMENTED_DEFAULT_CONFIG.copy()
    validate_config(defaults, require_required_keys=False)
    return defaults


def _flatten_config_value(name: str, value: object) -> list[tuple[str, object]]:
    """Compatibility wrapper around the shared dotted-value flattener."""
    return list(_core_flatten_config_value(name, value))


def get_config_diff_sections(
    current_cfg: dict | None = None,
    default_cfg: dict | None = None,
) -> list[tuple[str, list[tuple[str, object, object]]]]:
    """Return config values that differ from documented defaults.

    The result mirrors ``get_config_display_sections`` but entries are
    ``(display_name, current_value, default_value)`` tuples. Nested dictionaries
    are compared recursively as dotted keys such as ``DUCKS.spawn_chance`` or
    ``IDLERPG.topic_custom_text``.
    """
    if current_cfg is None:
        from . import config as current
    else:
        current = current_cfg
    defaults = load_default_config_for_diff() if default_cfg is None else default_cfg
    sections = []
    seen = set()

    for title, python_keys in CONFIG_DISPLAY_SECTIONS:
        entries = []
        for python_key in python_keys:
            normalized_key = PYTHON_CONFIG_KEY_MAP[python_key]
            if normalized_key not in current:
                continue

            current_value = current.get(normalized_key)
            default_value = defaults.get(normalized_key)
            seen.add(normalized_key)

            for change in flattened_config_value_changes(
                python_key,
                default_value,
                current_value,
            ):
                entries.append((change.key, change.after, change.before))

        if entries:
            sections.append((title, entries))

    extra_entries = []
    for key in sorted(k for k in current if k not in seen):
        display_key = _LOWER_TO_PYTHON_CONFIG_KEY.get(key, key.upper())
        current_value = current.get(key)
        default_value = defaults.get(key)
        if current_value != default_value:
            extra_entries.append((display_key, current_value, default_value))
    if extra_entries:
        sections.append(("Other", extra_entries))

    return sections
