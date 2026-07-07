"""Compatibility facade for the split package modules."""
from __future__ import annotations

import sys
import types
from importlib import import_module

_PART_NAMES = ['config', 'constants', 'formatting', 'leveling', 'items', 'map', 'state', 'export', 'seasons', 'events', 'quests', 'commands', 'tasks']
_PARTS = [import_module(f'{__name__}.{name}') for name in _PART_NAMES]
_EXPORTS_BY_PART = {'config': ['log', '_cfg', 'TICK_SECONDS', 'RP_BASE', 'RP_STEP', 'PENALTY_STEP', 'MESSAGE_PENALTY', 'LOGOUT_PENALTY', 'LOGOUT_GRACE_SECONDS', 'MAX_PENALTY', 'PAGE_SIZE', 'MAP_X', 'MAP_Y', 'QUEST_MIN_LEVEL', 'QUEST_INTERVAL', 'QUEST_MIN_DURATION', 'QUEST_MAX_DURATION', 'EVENT_CHANCE', 'ITEM_CHANCE', 'BATTLE_EVENT_WEIGHT', 'ITEM_EVENT_WEIGHT', 'ALIGNMENT_EVENT_WEIGHT', 'CRITICAL_STRIKE_CHANCE', 'ITEM_DROP_CHANCE', 'TEAM_BATTLE_EVENT_WEIGHT', 'BATTLE_WIN_MIN_PERCENT', 'BATTLE_LOSS_MIN_PERCENT', 'CRITICAL_MIN_PERCENT', 'CRITICAL_MAX_PERCENT', 'GODSEND_MIN_PERCENT', 'GODSEND_MAX_PERCENT', 'CALAMITY_MIN_PERCENT', 'CALAMITY_MAX_PERCENT', 'ALIGNMENT_BONUS_PERCENT', 'QUEST_REWARD_PERCENT', 'TEAM_BATTLE_PERCENT', 'UNIQUE_ITEMS_ENABLED', 'UNIQUE_ITEM_MIN_LEVEL', 'UNIQUE_ITEM_CHANCE', 'EVENT_LOG_LIMIT', 'EVENT_RETENTION_DAYS', 'EXPORT_EVENT_LIMIT', 'EXPORT_ENABLED', 'EXPORT_PATH', 'EXPORT_PUBLIC_BASE_URL', 'EXPORT_TOP_LIMIT', 'SEASON_ENABLED', 'SEASON_DURATION_DAYS', 'SEASON_RESET_ON_ROLLOVER', 'SEASON_HOF_SIZE', 'MAP_STEP_PER_TICK', 'COUNT_COMMAND_MESSAGES', 'ANNOUNCE_LOGIN', 'ANNOUNCE_TOP_INTERVAL', 'ANNOUNCE_TOP_LIMIT', 'UPDATE_ROOM_TOPIC', 'TOPIC_UPDATE_INTERVAL', 'TOPIC_CUSTOM_TEXT', 'ITEM_DAMAGE_EVENT_WEIGHT', 'ITEM_STEAL_EVENT_WEIGHT', 'LEVEL_REWARD_MIN_LEVEL', 'SEASON_ACHIEVEMENT_GATES_ENABLED', 'ROOM_TASKS'], 'constants': ['PLUGIN_META', 'IDLERPG_ENABLED_KEY', 'IDLERPG_DATA_KEY', 'PLUGIN_NAME', 'ACHIEVEMENTS', 'ITEMS', 'UNIQUE_ITEMS', 'MAP_REGIONS', 'CALAMITIES', 'GODSENDS', 'QUEST_TEXTS', '_ALIGNMENT_NAMES'], 'formatting': ['_command_prefix', 'get_idlerpg_store', '_reply', '_system_room_message', '_system_reply', '_now', '_duration', '_duration_clock', '_possessive', '_next_level_line', '_safe_name', '_safe_class', '_display_player', '_alignment_name', '_slug', '_room_slug', '_display_title', '_display_character', '_format_top_lines', '_topic_text', '_maybe_set_room_topic', '_maybe_periodic_announcements', '_usage'], 'leveling': ['_add_time', '_remove_time', '_ttl_for_level', '_penalty_for', '_penalty_amount_for', '_stats', '_inc_stat', '_achievement_catalog', '_season_gate_passed', '_award', '_achievement_title', '_achievement_description', '_check_level_achievements', '_apply_logout_penalty', '_maybe_apply_pending_logout_penalty', '_penalize_player'], 'items': ['_unique_defs_by_name', '_unique_bonuses', '_unique_bonus_percent', '_adjust_percent_amount', '_item_sum', '_battle_power', '_percent_amount', '_battle_percent', '_battle_clock_delta', '_random_percent_amount', '_roll_unique_item', '_grant_level_item', '_maybe_critical_strike', '_maybe_battle_item_drop', '_run_item_blessing', '_run_item_damage', '_run_item_swap'], 'map': ['_map_region_name', '_player_region', '_move_player', '_map_marker', '_render_ascii_map'], 'state': ['_blank_room', '_get_data', '_set_data', '_flush_idlerpg_store', '_checkpoint_room_clock', '_room_bucket', '_normalize_player', '_rebuild_name_index', '_find_player', '_online_jids', '_is_player_online', '_format_player_status', '_ranked_players', '_choose_two_players', '_room_from_context', '_sender_can_manage_room', '_enabled_rooms'], 'export': ['_export_root', '_player_public_record', '_atomic_write_json', '_public_url', '_safe_event_kind', '_clean_event_data', '_prune_events', '_record_event', '_event_public_record', '_room_events', '_profile_url', '_public_rules', '_export_room_state', '_export_public_state'], 'seasons': ['_season_id', '_season_duration_seconds', '_season_age_days', '_blank_season', '_season_snapshot', '_reset_player_for_new_season', '_end_season', '_maybe_rollover_season', '_season_end_summary'], 'events': ['_alignment_battle_factor', '_battle_amount', '_maybe_run_random_event', '_run_pvp_battle', '_run_team_battle', '_run_alignment_bonus', '_run_godsend_or_calamity'], 'quests': ['_maybe_run_quest'], 'commands': ['_handle_register', '_handle_login', '_handle_logout', '_handle_status', '_handle_top', '_handle_players', '_handle_items', '_handle_align', '_handle_quest', '_handle_profile', '_handle_achievements', '_handle_title', '_handle_events', '_handle_stats', '_handle_map', '_handle_hof', '_handle_season', '_handle_announce_top', '_handle_topic_update', '_handle_export', '_handle_remove_me', '_handle_admin', 'idlerpg_command', 'on_message', 'on_muc_presence'], 'tasks': ['_ensure_game_task', '_cancel_room_task', '_start_enabled_room_tasks', '_sync_tasks_to_enabled_rooms', '_game_loop', '_tick_room', 'get_runtime_state', 'cleanup_room_state', 'restart_tasks', 'on_ready', 'on_load', 'on_unload']}
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
