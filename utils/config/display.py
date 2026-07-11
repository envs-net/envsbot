"""Split module for utils/config.py: display."""

from __future__ import annotations
from pathlib import Path

from .defaults import (
    BASE_DIR,
    CONFIG_DISPLAY_SECTIONS,
    DEFAULT_CONFIG,
    PYTHON_CONFIG_KEY_MAP,
    _LOWER_TO_PYTHON_CONFIG_KEY,
)
from .loader import (
    _load_python_config,
    _merge_room_plugin_default_config,
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
    """Return documented defaults used by ``config diff``.

    ``config_sample.py`` is the operator-facing source of truth for defaults.
    We merge it onto ``DEFAULT_CONFIG`` so legacy/internal fallback keys still
    have stable comparison values, then validate only optional types because
    sample credentials are placeholders by design.
    """
    defaults = DEFAULT_CONFIG.copy()
    sample_path = _sample_config_path()
    if sample_path.exists():
        loaded = _merge_room_plugin_default_config(
            DEFAULT_CONFIG,
            _load_python_config(sample_path),
        )
        defaults.update(loaded)
    validate_config(defaults, require_required_keys=False)
    return defaults


def _flatten_config_value(name: str, value: object) -> list[tuple[str, object]]:
    """Return leaf-level config entries using dotted names for nested dicts."""
    if not isinstance(value, dict):
        return [(name, value)]

    flattened: list[tuple[str, object]] = []
    for key in sorted(value):
        child_name = f"{name}.{key}"
        child_value = value[key]
        if isinstance(child_value, dict):
            flattened.extend(_flatten_config_value(child_name, child_value))
        else:
            flattened.append((child_name, child_value))
    return flattened


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

            current_items = dict(_flatten_config_value(python_key, current_value))
            default_items = dict(_flatten_config_value(python_key, default_value))
            for display_name in sorted(set(current_items) | set(default_items)):
                current_item = current_items.get(display_name)
                default_item = default_items.get(display_name)
                if current_item != default_item:
                    entries.append((display_name, current_item, default_item))

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
