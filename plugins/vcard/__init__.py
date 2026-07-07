"""Compatibility facade for the split package modules."""
from __future__ import annotations

import sys
import types
from importlib import import_module

_PART_NAMES = ['config', 'fetch', 'formatting', 'timezone', 'commands']
_PARTS = [import_module(f'{__name__}.{name}') for name in _PART_NAMES]
_EXPORTS_BY_PART = {'config': ['VCARD_KEY', 'PLUGIN_META', 'log'], 'fetch': ['get_user_vcard', 'vcard_field', '_vcard_get_joined_nick_info', '_vcard_fetch_value'], 'formatting': ['_format_vcard_header', '_append_empty_vcard_value', '_append_vcard_list_values', '_append_vcard_note_values', '_format_vcard_field_for_nick', '_vcard_value_is_empty', '_vcard_should_format_field', '_vcard_reply_missing_nick', '_vcard_reply_missing_field', '_vcard_reply_empty_requested_user', '_vcard_reply_result', '_vcard_handle_missing_nick', '_format_vcard_reply', '_append_name_info', '_append_nickname_info', '_append_birthday_info', '_append_url_info', '_append_org_info', '_append_note_info', '_append_email_info', '_append_address_info'], 'timezone': ['set_timezone', '_get_vcard_timezone', 'get_timezone'], 'commands': ['_vcard_handle_room_lookup', '_get_vcard_field', 'get_vcard', 'get_info', '_get_all_field_values_by_tag', '_get_nested_field_values_by_tag', '_extract_email_addresses', 'get_vcard_store', '_resolve_vcard_target', 'vcard_command', 'get_fullname', 'get_nicknames', 'get_organisations', 'get_notes', 'get_email', 'get_urls', 'get_birthday']}
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
