"""Public facade for the reminder plugin package."""
from __future__ import annotations

from importlib import import_module

_PART_NAMES = ['config', 'runtime', 'parsing', 'store', 'formatting', 'events', 'tasks', 'commands', 'lifecycle']
_PARTS = [import_module(f"{__name__}.{name}") for name in _PART_NAMES]
_EXPORTS_BY_PART = {'config': ['PLUGIN_META', 'REMINDER_KEY', 'REMINDER_REPLY_FALLBACK_NAMESPACE'], 'runtime': ['log', 'ACTIVE_REMINDERS', 'REMINDER_ENABLED', 'REMINDER_DB_READY'], 'parsing': ['_timezone_lookup_jid', '_localize_naive_datetime', '_format_local_datetime', 'format_seconds', '_ensure_utc', '_timezone_from_token', '_reminder_default_tzinfo', 'get_reminder_tzinfo', 'REMINDER_DEFAULT_TIMEZONE', 'parse_absolute_datetime', 'parse_reminder_when', 'explain_invalid_reminder_time', '_format_overdue', '_parse_datetime', '_utcnow'], 'store': ['get_reminder_store', '_get_room_reminder_state', '_init_reminder_db', '_create_reminder', '_delete_reminder', '_get_reminder', '_get_pending_reminders', '_get_all_pending_reminders'], 'formatting': ['_display_nick', '_reminder_context', '_room_jid_from_context', '_is_reminder_enabled_for_context', '_send_reminder_message'], 'events': ['_body_without_reply_quote', '_is_remind_command_body', '_is_own_room_message', '_reply_message_text', '_redispatch_reply_fallback', '_on_groupchat_message', '_on_private_message'], 'tasks': ['_schedule_task', '_cancel_all_active_tasks', '_cancel_active_tasks_for_room', 'schedule_reminder_task', '_restore_pending_reminders'], 'commands': ['remind_command', 'remind_status_command', 'remind_on_command', 'remind_off_command', 'delete_reminder', 'list_reminders'], 'lifecycle': ['on_load', 'on_ready', 'on_unload', 'cleanup_room_state', 'get_runtime_state', 'doctor']}
_EXPORTED: dict[str, object] = {}
for _part, _names in zip(
    _PARTS,
    (_EXPORTS_BY_PART[name] for name in _PART_NAMES),
    strict=True,
):
    for _name in _names:
        if hasattr(_part, _name):
            _EXPORTED[_name] = getattr(_part, _name)

globals().update(_EXPORTED)
__all__ = sorted(_EXPORTED)
del _name, _names, _part
del import_module
