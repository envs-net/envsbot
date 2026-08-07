"""Split module for utils/config.py: defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]


CONFIG_FILENAME = "config.py"


LEGACY_CONFIG_FILENAME = "config.json"


from .spec import (
    CONFIG_DISPLAY_SECTIONS,
    config_defaults,
    optional_config_types,
    python_config_key_map,
    required_config_types,
    sample_config_defaults,
)

DEFAULT_CONFIG: dict[str, Any] = config_defaults()
DOCUMENTED_DEFAULT_CONFIG: dict[str, Any] = sample_config_defaults()
REQUIRED_CONFIG_KEYS = required_config_types()
OPTIONAL_CONFIG_TYPES = optional_config_types()
PYTHON_CONFIG_KEY_MAP = python_config_key_map()


NORMALIZED_CONFIG_KEYS = (
    set(DEFAULT_CONFIG)
    | set(REQUIRED_CONFIG_KEYS)
    | set(OPTIONAL_CONFIG_TYPES)
    | set(PYTHON_CONFIG_KEY_MAP.values())
)



_LOWER_TO_PYTHON_CONFIG_KEY = {
    normalized_key: python_key
    for python_key, normalized_key in PYTHON_CONFIG_KEY_MAP.items()
}

__all__ = [
    'BASE_DIR',
    'CONFIG_FILENAME',
    'LEGACY_CONFIG_FILENAME',
    'DEFAULT_CONFIG',
    'DOCUMENTED_DEFAULT_CONFIG',
    'REQUIRED_CONFIG_KEYS',
    'OPTIONAL_CONFIG_TYPES',
    'PYTHON_CONFIG_KEY_MAP',
    'NORMALIZED_CONFIG_KEYS',
    'CONFIG_DISPLAY_SECTIONS',
    '_LOWER_TO_PYTHON_CONFIG_KEY',
]
