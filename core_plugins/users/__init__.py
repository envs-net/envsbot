"""Compatibility facade for the split package modules."""
from __future__ import annotations

import sys
import types
from importlib import import_module

_PART_NAMES = ['roles', 'tracking', 'lookup', 'permissions', 'formatting', 'commands']
_PARTS = [import_module(f'{__name__}.{name}') for name in _PART_NAMES]
_EXPORTS_BY_PART = {'roles': ['log', 'prefix', 'MAX_ROOM_NICKS', 'ASSIGNABLE_ROLES', 'ROLE_NAMES', 'GRANTABLE_PLUGINS', 'GRANTS_FIELD', 'PLUGIN_META'], 'tracking': ['on_muc_presence', 'on_groupchat_message', 'on_load', 'track_room_nick', 'update_last_seen'], 'lookup': ['find_users_by_nick_safe', '_parse_user_jid', '_plugin_name', '_valid_plugin_names', '_maybe_await'], 'permissions': ['_owner_jid', '_is_config_owner', '_actor_role', '_role_from_user', '_role_label', '_available_role_names', '_can_manage_roles', '_can_change_role', '_can_delete_user', '_grantable_plugin_names', '_normalize_plugin_grants', 'get_user_plugin_grants', 'set_user_plugin_grants', 'user_has_plugin_grant', '_bare_jid_from_affiliation_item', '_normalize_affiliation_result', '_query_affiliation_jids', '_live_room_affiliation_allows', '_cached_room_affiliation_allows', 'user_is_room_owner_or_admin', 'user_has_room_plugin_grant', 'users_roles', '_validate_grant_change', '_resolve_permission_target', '_room_affiliation_status', '_can_manage_plugin_from_diagnostics', 'users_permissions', 'users_grant', 'users_grants', 'users_admins'], 'formatting': ['_send_user_info', '_write_user_audit', '_audit_reason', '_yes_no'], 'commands': ['_command_prefix', 'users_info', 'users_list', 'users_update', 'users_revoke', 'users_delete']}
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

del import_module, sys, types
