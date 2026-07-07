"""Compatibility facade for the split package modules."""
from __future__ import annotations

import sys
import types
from importlib import import_module

_PART_NAMES = ['state', 'defaults', 'permissions', 'invites', 'settings', 'presence', 'commands', 'lifecycle']
_PARTS = [import_module(f'{__name__}.{name}') for name in _PART_NAMES]
_EXPORTS_BY_PART = {'state': ['log', 'JOINED_ROOMS', '_LEAVING_ROOMS', '_DIRECT_INVITE_NS', '_MUC_USER_NS', '_WARNED_ROOM_PLUGIN_DEFAULT_KEYS', '_safe_get_plugin', '_safe_plugin_value', '_maybe_await_result', '_get_plugin_store', '_store_get_global', '_store_set_global', '_room_matches', '_merge_plugin_cleanup_summary', '_plugin_cleanup_changed', '_plugin_hook_cleanup_changed', '_room_in_runtime_state', '_leave_runtime_room', 'room_status_get', 'room_status_set', 'room_status_delete', '_yes_no', '_room_diagnose_lines'], 'defaults': ['PLUGIN_META', 'INTERNAL_PLUGIN_DEFAULTS', 'PLUGIN_DEFAULTS', 'PLUGIN_STORE_CONFIG', 'ROOM_TOGGLE_STORES', '_normalize_room_plugin_default_name', '_coerce_room_plugin_default', 'get_room_plugin_defaults', '_cleanup_room_plugin_state', 'cmd_room_plugins'], 'permissions': ['_maybe_get_user_role', '_sender_has_room_affiliation', '_sender_can_manage_room_settings', 'bot_has_privilege'], 'invites': ['room_invites_enabled', 'room_invite_notify_target', 'room_invite_admin_rooms', '_room_invite_max_age_days', '_room_invite_is_expired', '_invite_inviter_from_attr', '_room_invite_reason_from_invite', '_room_invite_from_muc_plugin', '_room_invite_from_direct_plugin', 'extract_room_invite', 'setup_room_invites_db', 'load_pending_room_invites', '_store_pending_room_invite', '_delete_pending_room_invite', 'cleanup_expired_room_invites', 'cleanup_all_room_invites', '_notify_room_invite', 'handle_room_invite', 'on_room_invite_message', 'on_room_invite', '_join_invited_room', 'rooms_invite'], 'settings': ['_cleanup_room_toggle_state', 'set_room_control_defaults', '_handle_room_feature_toggle'], 'presence': ['_jid_bare', '_looks_like_room_jid', '_message_context_room', '_room_is_known', '_resolve_room_settings_target', 'is_nick_change', 'on_muc_presence', 'is_valid_muc_domain', 'is_valid_room_jid'], 'commands': ['autojoin_rooms', 'cmd_room_setdefaults', 'cmd_room_diagnose', 'cmd_room_enable', 'cmd_room_disable', 'rooms_add', 'rooms_update', 'rooms_delete', 'rooms_list', 'rooms_join', 'rooms_leave', 'rooms_sync'], 'lifecycle': ['on_ready', 'on_load', 'on_unload']}
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
del _name, _names, _value
del import_module, sys, types
