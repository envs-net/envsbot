"""Compatibility facade for the split package modules."""
from __future__ import annotations

import sys
import types
from importlib import import_module

_PART_NAMES = ['defaults', 'errors', 'display', 'loader', 'validation', 'logging_setup', 'runtime']
_PARTS = [import_module(f'{__name__}.{name}') for name in _PART_NAMES]
_EXPORTS_BY_PART = {'defaults': ['BASE_DIR', 'CONFIG_FILENAME', 'LEGACY_CONFIG_FILENAME', 'DEFAULT_CONFIG', 'REQUIRED_CONFIG_KEYS', 'OPTIONAL_CONFIG_TYPES', 'PYTHON_CONFIG_KEY_MAP', 'NORMALIZED_CONFIG_KEYS', 'CONFIG_DISPLAY_SECTIONS', '_LOWER_TO_PYTHON_CONFIG_KEY'], 'errors': ['ConfigError', 'exit_on_config_error'], 'display': ['get_config_display_sections', '_sample_config_path', 'load_default_config_for_diff', '_flatten_config_value', 'get_config_diff_sections'], 'loader': ['_config_path_from_env', '_default_config_path', '_legacy_config_path', 'get_runtime_config_path', '_format_json_error', '_format_python_error', '_load_python_config', '_merge_room_plugin_default_config', '_load_legacy_json_config', 'load_config'], 'validation': ['_validate_string', '_validate_jid', '_validate_numeric_ranges', '_validate_timezone', '_validate_avatar', 'collect_config_warnings', 'check_required_keys', 'check_optional_keys', '_validate_room_plugin_defaults', 'validate_config', 'validate_startup_config'], 'logging_setup': ['setup_logging'], 'runtime': ['STARTUP_ONLY_KEYS', 'apply_log_level', 'apply_runtime_config', 'config_change_lines', 'refresh_runtime_config_constants', 'restart_reloadable_plugin_tasks', 'startup_change_lines']}
_SHARED: dict[str, object] = {}
for _part, _names in zip(_PARTS, (_EXPORTS_BY_PART[name] for name in _PART_NAMES), strict=True):
    for _name in _names:
        if hasattr(_part, _name):
            _SHARED[_name] = getattr(_part, _name)
# Also keep imported helper modules available for backwards-compatible tests/monkeypatching.
for _part in _PARTS:
    for _name, _value in vars(_part).items():
        if not _name.startswith('__') and _name not in _SHARED:
            _SHARED[_name] = _value
for _part in _PARTS:
    vars(_part).update(_SHARED)
globals().update(_SHARED)

# Backwards-compatible global config object.
config = None
_load_config = _SHARED["load_config"]
_ConfigError = _SHARED["ConfigError"]
_exit_on_config_error = _SHARED["exit_on_config_error"]
try:
    config = _load_config(require_required_keys=False)
except _ConfigError as e:
    _exit_on_config_error(e)
_SHARED['config'] = config
for _part in _PARTS:
    vars(_part)['config'] = config
globals().update(_SHARED)
__all__ = sorted(_SHARED)

class _SplitPackageModule(types.ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name in globals().get('_SHARED', {}):
            _SHARED[name] = value
            for _part in _PARTS:
                if hasattr(_part, name):
                    setattr(_part, name, value)

sys.modules[__name__].__class__ = _SplitPackageModule

# Avoid leaking temporary loop variables into the public package namespace.
# Command registration scans module attributes; a leaked _value can otherwise
# expose the last decorated command a second time.
del _name, _names, _value, _part
del import_module, sys, types
