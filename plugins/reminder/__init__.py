"""Compatibility facade for the split package modules."""
from __future__ import annotations

import sys
import types
from importlib import import_module

_PART_NAMES = ['parsing', 'store', 'formatting', 'commands', 'tasks']
_PARTS = [import_module(f'{__name__}.{name}') for name in _PART_NAMES]
_EXPORTS_BY_PART = {'parsing': ['_timezone_lookup_jid', '_localize_naive_datetime', '_format_local_datetime', 'format_seconds', '_ensure_utc', '_timezone_from_token', '_reminder_default_tzinfo', 'get_reminder_tzinfo', 'REMINDER_DEFAULT_TIMEZONE', 'parse_absolute_datetime', 'parse_reminder_when', '_format_overdue', '_parse_datetime'], 'store': ['log', 'PLUGIN_META', 'ACTIVE_REMINDERS', 'REMINDER_ENABLED', 'REMINDER_KEY', 'REMINDER_DB_READY', 'get_reminder_store', '_get_room_reminder_state', '_handle_reminder_control_command', '_init_reminder_db', '_create_reminder', '_delete_reminder', 'schedule_reminder_task', '_restore_pending_reminders', 'remind_command', 'delete_reminder', 'on_ready', 'get_runtime_state', 'doctor'], 'formatting': ['_display_nick', '_reminder_context', '_room_jid_from_context', '_is_reminder_enabled_for_context', '_send_reminder_message'], 'commands': ['_utcnow', '_utc_tz', '_get_reminder', '_get_pending_reminders', '_get_all_pending_reminders', 'list_reminders'], 'tasks': ['_schedule_task', '_cancel_all_active_tasks', '_cancel_active_tasks_for_room', 'on_unload', 'cleanup_room_state']}
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
