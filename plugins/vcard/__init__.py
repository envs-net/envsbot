"""Public facade for the vCard plugin package."""
from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fetch import get_user_vcard

_PART_NAMES = ['config', 'formatting', 'fetch', 'store', 'fields', 'timezone', 'commands']
_PARTS = [import_module(f"{__name__}.{name}") for name in _PART_NAMES]
_EXPORTS_BY_PART = {'config': ['VCARD_KEY', 'PLUGIN_META', 'log'], 'formatting': ['_format_vcard_header', '_append_empty_vcard_value', '_append_vcard_list_values', '_append_vcard_note_values', '_format_vcard_field_for_nick', '_vcard_value_is_empty', '_vcard_should_format_field', '_vcard_reply_missing_nick', '_vcard_reply_missing_field', '_vcard_reply_empty_requested_user', '_vcard_reply_result', '_vcard_handle_missing_nick', '_format_vcard_reply', '_append_name_info', '_append_nickname_info', '_append_birthday_info', '_append_url_info', '_append_org_info', '_append_note_info', '_append_email_info', '_append_address_info', '_get_all_field_values_by_tag', '_get_nested_field_values_by_tag', '_extract_email_addresses'], 'fetch': ['get_vcard', 'get_info', 'get_user_vcard', 'vcard_field', '_vcard_get_joined_nick_info', '_vcard_fetch_value'], 'store': ['get_vcard_store'], 'fields': ['_vcard_handle_room_lookup', '_get_vcard_field'], 'timezone': ['set_timezone', '_get_vcard_timezone', 'get_timezone'], 'commands': ['_resolve_vcard_target', 'vcard_command', 'get_fullname', 'get_nicknames', 'get_organisations', 'get_notes', 'get_email', 'get_urls', 'get_birthday', 'get_runtime_state', 'doctor']}
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
