"""Compatibility facade for the split package modules."""
from __future__ import annotations

import sys
import types
from importlib import import_module

_PART_NAMES = ['config', 'store', 'fetch', 'formatting', 'commands', 'tasks']
_PARTS = [import_module(f'{__name__}.{name}') for name in _PART_NAMES]
_EXPORTS_BY_PART = {'config': ['PLUGIN_META', 'RSS_KEY', 'RSS_TEMPLATES_KEY', 'DEFAULT_RSS_TEMPLATE', 'RSS_TEMPLATE_MAX_LENGTH', 'RSS_TEMPLATE_VARIABLES', 'DEFAULT_POLL_INTERVAL', 'RSS_RETRY_INITIAL_DELAY', 'RSS_RETRY_BACKOFF_MULTIPLIER', 'MAX_BACKOFF_TIME', 'RSS_USER_AGENT', 'RSS_FETCH_TIMEOUT_SECONDS', 'RSS_MAX_REDIRECTS', 'RSS_MAX_READ_BYTES', 'ALLOW_PRIVATE_FETCH_URLS', 'RSS_LIST_PAGE_SIZE', 'RSS_MAX_ENTRIES_PER_POLL'], 'store': ['log', '_flush_user_store', 'get_rss_store', 'get_room_templates', 'save_room_templates', 'get_room_template', 'set_room_template', 'unset_room_template', '_set_retry_state', '_apply_retry_state', '_reset_retry_state', '_retry_delay', '_sleep_for_retry', '_format_retry_status', '_reset_feed_retry', 'cleanup_room_state', 'get_runtime_state'], 'fetch': ['SIMILARITY_THRESHOLD', 'entry_get', 'html_to_text_with_links', '_should_include_description', '_extract_entry_link', '_generate_entry_id', '_get_entry_id', '_get_latest_entry_id', '_normalize_url', '_resolve_relative_url', '_get_feed_headers', 'get_feeds', 'save_feeds', '_fetch_feed_bytes', '_github_feed_hint', '_format_feed_fetch_error', '_is_expected_feed_fetch_error', '_log_feed_fetch_error', '_parsed_value', '_has_feed_metadata', '_validate_parsed_feed', 'fetch_feed', '_load_feed', '_update_feed', '_set_feed_field', '_update_feed_link', '_entry_is_new', '_post_entry_to_rooms', '_handle_fetch_error', '_handle_empty_feed', '_format_feed_list_item', '_filter_feeds_for_room', '_format_feed_list', '_handle_feed_recovery', '_maybe_update_feed_link', '_cancel_feed_task'], 'formatting': ['_SAMPLE_TEMPLATE_CONTEXT', '_rss_template_usage', '_rss_template_variables_text', '_normalize_rss_template_input', '_validate_rss_template', '_entry_date', '_build_rss_template_context', '_render_rss_template', '_build_rss_message_from_context', '_build_rss_message', '_format_duration', '_post_rss_entry_to_rooms', '_post_new_entries'], 'commands': ['_command_prefix', '_room_for_feed_command', '_sender_is_global_rss_manager', '_sender_can_manage_rss_room', '_sender_can_manage_rss_globally', '_looks_like_room_arg', '_normalize_room_jid', '_now', '_read_limited_response', '_mapping_value', '_set_mapping_value', '_initialize_last_id', '_save_last_id', '_rss_list_usage', '_rss_list_page', '_initialize_missing_last_id', '_collect_new_entries', 'burst_recent_entries', '_split_template_room_args', '_join_template_args', '_sample_rss_template_preview', '_sender_can_manage_template', '_rss_template_command', 'rss_command', '_add_feed', '_delete_feed_everywhere', '_delete_feed_room', '_reset_all_feed_retries', '_del_feed'], 'tasks': ['CHECK_TASKS', 'rss_check_loop', 'ensure_task', 'restart_all_tasks', 'on_load', 'restart_tasks', 'on_unload']}
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
