"""Public facade for the RSS plugin package."""
from __future__ import annotations

from importlib import import_module

_PART_NAMES = ['config', 'store', 'fetch', 'formatting', 'tasks', 'commands', 'lifecycle']
_PARTS = [import_module(f"{__name__}.{name}") for name in _PART_NAMES]
_EXPORTS_BY_PART = {'config': ['PLUGIN_META', 'RSS_KEY', 'RSS_DEFAULT_TEMPLATE_KEY', 'RSS_TEMPLATES_KEY', 'RSS_FEED_TEMPLATES_KEY', 'DEFAULT_RSS_TEMPLATE', 'RSS_TEMPLATE_MAX_LENGTH', 'RSS_TEMPLATE_VARIABLES', 'DEFAULT_POLL_INTERVAL', 'RSS_RETRY_INITIAL_DELAY', 'RSS_RETRY_BACKOFF_MULTIPLIER', 'MAX_BACKOFF_TIME', 'RSS_USER_AGENT', 'RSS_FETCH_TIMEOUT_SECONDS', 'RSS_MAX_REDIRECTS', 'RSS_MAX_READ_BYTES', 'ALLOW_PRIVATE_FETCH_URLS', 'RSS_LIST_PAGE_SIZE', 'RSS_MAX_ENTRIES_PER_POLL', 'RSS_BROKEN_ERROR_THRESHOLD'], 'store': ['_now', '_normalize_room_jid', '_normalize_template_room_jid', '_normalize_template_feed_url', '_flush_user_store', 'get_rss_store', 'get_default_template', 'set_default_template', 'unset_default_template', 'get_room_templates', 'save_room_templates', 'get_feed_templates', 'save_feed_templates', 'get_feed_template', 'set_feed_template', 'unset_feed_template', 'unset_feed_templates_for_feed', 'unset_feed_templates_for_room', 'get_effective_template', 'get_room_template', 'set_room_template', 'unset_room_template', '_apply_retry_state', '_normalize_subscription_room', '_feed_paused_rooms', '_feed_active_rooms', '_feed_is_globally_paused', '_format_rss_timestamp', '_feed_status_label', '_record_feed_check', '_record_feed_post', '_set_retry_state', '_reset_retry_state', '_retry_delay', '_sleep_for_retry', 'get_feeds', 'save_feeds', '_load_feed', '_update_feed', '_set_feed_field', '_update_feed_link'], 'fetch': ['SIMILARITY_THRESHOLD', '_mapping_value', '_set_mapping_value', 'entry_get', 'html_to_text_with_links', '_should_include_description', '_extract_entry_link', '_generate_entry_id', '_get_entry_id', '_get_latest_entry_id', '_normalize_url', '_resolve_relative_url', '_get_feed_headers', '_fetch_feed_bytes', '_github_feed_hint', '_format_feed_fetch_error', '_is_expected_feed_fetch_error', '_log_feed_fetch_error', '_parsed_value', '_has_feed_metadata', '_validate_parsed_feed', 'fetch_feed', '_entry_is_new'], 'formatting': ['_SAMPLE_TEMPLATE_CONTEXT', '_template_command_prefix', '_rss_template_usage', '_rss_template_variables_text', '_normalize_rss_template_input', '_validate_rss_template', '_entry_date', '_build_rss_template_context', '_render_rss_template', '_build_rss_message_from_context', '_build_rss_message', '_format_duration', '_post_rss_entry_to_rooms', '_post_new_entries', '_set_last_id_in_feed', '_feed_now', '_update_feed_for_post', '_rss_list_page', '_post_entry_to_rooms', '_format_feed_list_item', '_filter_feeds_for_room', '_format_feed_list', '_format_retry_status'], 'tasks': ['CHECK_TASKS', '_initialize_last_id', 'rss_check_loop', 'ensure_task', 'restart_all_tasks', 'on_load', 'restart_tasks', 'on_unload', '_handle_fetch_error', '_handle_empty_feed', '_handle_feed_recovery', '_maybe_update_feed_link', '_cancel_feed_task', '_initialize_missing_last_id', '_collect_new_entries'], 'commands': ['_command_prefix', '_room_for_feed_command', '_sender_is_global_rss_manager', '_sender_can_manage_rss_room', '_sender_can_manage_rss_globally', '_looks_like_room_arg', '_save_last_id', '_rss_list_usage', 'burst_recent_entries', '_looks_like_feed_arg', '_split_template_scope_args', '_template_feed_for_room', '_sample_template_context_for_feed', '_sample_rss_template_preview', '_join_template_args', '_sender_can_manage_template', '_rss_template_command', '_rss_health_lines', '_rss_health_summary', '_rss_normalize_room_list', '_rss_set_pause_state', 'rss_command', '_add_feed', '_delete_feed_everywhere', '_delete_feed_room', '_reset_all_feed_retries', '_del_feed', '_reset_feed_retry'], 'lifecycle': ['cleanup_room_state', 'get_runtime_state', 'doctor']}
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
