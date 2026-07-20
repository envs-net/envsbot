"""Compatibility facade for the split package modules."""
from __future__ import annotations

from importlib import import_module

_PART_NAMES = ['roles', 'tracking', 'lookup', 'permissions', 'formatting', 'commands', 'permission_commands']
_PARTS = [import_module(f'{__name__}.{name}') for name in _PART_NAMES]
_EXPORTS_BY_PART = {'roles': ['Role', 'log', 'prefix', 'MAX_ROOM_NICKS', 'ASSIGNABLE_ROLES', 'ROLE_NAMES', 'GRANTABLE_PLUGINS', 'GRANTS_FIELD', 'PLUGIN_META'], 'tracking': ['on_muc_presence', 'on_groupchat_message', 'on_load', 'track_room_nick', 'update_last_seen'], 'lookup': ['find_users_by_nick_safe', '_parse_user_jid', '_plugin_name', '_valid_plugin_names', '_maybe_await'], 'permissions': ['_owner_jid', '_is_config_owner', '_actor_role', '_role_from_user', '_role_label', '_available_role_names', '_can_manage_roles', '_can_change_role', '_can_delete_user', '_grantable_plugin_names', '_normalize_plugin_grants', 'get_user_plugin_grants', 'set_user_plugin_grants', 'user_has_plugin_grant', '_bare_jid_from_affiliation_item', '_normalize_affiliation_result', '_query_affiliation_jids', '_live_room_affiliation_allows', '_cached_room_affiliation_allows', 'user_is_room_owner_or_admin', 'user_has_room_plugin_grant', '_validate_grant_change', '_resolve_permission_target', '_room_affiliation_status', '_can_manage_plugin_from_diagnostics'], 'formatting': ['_send_user_info', '_write_user_audit', '_audit_reason', '_yes_no'], 'commands': ['_command_prefix', 'users_info', 'users_list', 'users_update', 'users_revoke', 'users_delete'], 'permission_commands': ['users_roles', 'users_permissions', 'users_grant', 'users_grants', 'users_admins']}
_SHARED: dict[str, object] = {}
for _part, _names in zip(_PARTS, (_EXPORTS_BY_PART[name] for name in _PART_NAMES), strict=True):
    for _name in _names:
        if hasattr(_part, _name):
            _SHARED[_name] = getattr(_part, _name)
globals().update(_SHARED)
__all__ = sorted(_SHARED)
del _name, _names, _part
del import_module
