"""Split module for plugins/idlerpg.py: config."""

from __future__ import annotations
import asyncio
import logging
from utils.config import config


log = logging.getLogger(__name__)


_cfg = config.get("idlerpg", {}) if isinstance(config.get("idlerpg", {}), dict) else {}


TICK_SECONDS = int(_cfg.get("tick_seconds", config.get("idlerpg_tick_seconds", 60)) or 60)


RP_BASE = int(_cfg.get("rp_base", config.get("idlerpg_rp_base", 600)) or 600)


RP_STEP = float(_cfg.get("rp_step", config.get("idlerpg_rp_step", 1.16)) or 1.16)


PENALTY_STEP = float(
    _cfg.get("penalty_step", config.get("idlerpg_penalty_step", 1.14)) or 1.14
)


MESSAGE_PENALTY = int(
    _cfg.get("message_penalty", config.get("idlerpg_message_penalty", 1)) or 1
)


LOGOUT_PENALTY = int(
    _cfg.get("logout_penalty", config.get("idlerpg_logout_penalty", 20)) or 20
)


LOGOUT_GRACE_SECONDS = int(
    _cfg.get("logout_grace_seconds", config.get("idlerpg_logout_grace_seconds", 300)) or 0
)


MAX_PENALTY = int(_cfg.get("max_penalty", config.get("idlerpg_max_penalty", 604800)) or 0)


PAGE_SIZE = int(_cfg.get("page_size", config.get("idlerpg_page_size", 10)) or 10)


MAP_X = int(_cfg.get("map_x", config.get("idlerpg_map_x", 500)) or 500)


MAP_Y = int(_cfg.get("map_y", config.get("idlerpg_map_y", 500)) or 500)


QUEST_MIN_LEVEL = int(
    _cfg.get("quest_min_level", config.get("idlerpg_quest_min_level", 40)) or 40
)


QUEST_INTERVAL = int(
    _cfg.get("quest_interval", config.get("idlerpg_quest_interval", 21600)) or 21600
)


QUEST_MIN_DURATION = int(
    _cfg.get("quest_min_duration", config.get("idlerpg_quest_min_duration", 43200)) or 43200
)


QUEST_MAX_DURATION = int(
    _cfg.get("quest_max_duration", config.get("idlerpg_quest_max_duration", 86400)) or 86400
)


EVENT_CHANCE = float(
    _cfg.get("event_chance", config.get("idlerpg_event_chance", 0.01)) or 0.01
)


ITEM_CHANCE = float(
    _cfg.get("item_chance", config.get("idlerpg_item_chance", 0.20)) or 0.20
)


BATTLE_EVENT_WEIGHT = float(
    _cfg.get("battle_event_weight", config.get("idlerpg_battle_event_weight", 0.55)) or 0.55
)


ITEM_EVENT_WEIGHT = float(
    _cfg.get("item_event_weight", config.get("idlerpg_item_event_weight", 0.15)) or 0.15
)


ALIGNMENT_EVENT_WEIGHT = float(
    _cfg.get("alignment_event_weight", config.get("idlerpg_alignment_event_weight", 0.10)) or 0.10
)


CRITICAL_STRIKE_CHANCE = float(
    _cfg.get("critical_strike_chance", config.get("idlerpg_critical_strike_chance", 0.10)) or 0.10
)


ITEM_DROP_CHANCE = float(
    _cfg.get("item_drop_chance", config.get("idlerpg_item_drop_chance", 0.12)) or 0.12
)


TEAM_BATTLE_EVENT_WEIGHT = float(
    _cfg.get("team_battle_event_weight", config.get("idlerpg_team_battle_event_weight", 0.08)) or 0.08
)


BATTLE_WIN_MIN_PERCENT = int(
    _cfg.get("battle_win_min_percent", config.get("idlerpg_battle_win_min_percent", 7)) or 7
)


BATTLE_LOSS_MIN_PERCENT = int(
    _cfg.get("battle_loss_min_percent", config.get("idlerpg_battle_loss_min_percent", 7)) or 7
)


CRITICAL_MIN_PERCENT = int(
    _cfg.get("critical_min_percent", config.get("idlerpg_critical_min_percent", 5)) or 5
)


CRITICAL_MAX_PERCENT = int(
    _cfg.get("critical_max_percent", config.get("idlerpg_critical_max_percent", 25)) or 25
)


GODSEND_MIN_PERCENT = int(
    _cfg.get("godsend_min_percent", config.get("idlerpg_godsend_min_percent", 5)) or 5
)


GODSEND_MAX_PERCENT = int(
    _cfg.get("godsend_max_percent", config.get("idlerpg_godsend_max_percent", 12)) or 12
)


CALAMITY_MIN_PERCENT = int(
    _cfg.get("calamity_min_percent", config.get("idlerpg_calamity_min_percent", 5)) or 5
)


CALAMITY_MAX_PERCENT = int(
    _cfg.get("calamity_max_percent", config.get("idlerpg_calamity_max_percent", 12)) or 12
)


ALIGNMENT_BONUS_PERCENT = int(
    _cfg.get("alignment_bonus_percent", config.get("idlerpg_alignment_bonus_percent", 7)) or 7
)


QUEST_REWARD_PERCENT = int(
    _cfg.get("quest_reward_percent", config.get("idlerpg_quest_reward_percent", 25)) or 25
)


TEAM_BATTLE_PERCENT = int(
    _cfg.get("team_battle_percent", config.get("idlerpg_team_battle_percent", 20)) or 20
)


UNIQUE_ITEMS_ENABLED = bool(
    _cfg.get("unique_items_enabled", config.get("idlerpg_unique_items_enabled", True))
)


UNIQUE_ITEM_MIN_LEVEL = int(
    _cfg.get("unique_item_min_level", config.get("idlerpg_unique_item_min_level", 25)) or 25
)


UNIQUE_ITEM_CHANCE = float(
    _cfg.get("unique_item_chance", config.get("idlerpg_unique_item_chance", 0.025)) or 0.025
)


EVENT_LOG_LIMIT = int(
    _cfg.get("event_log_limit", config.get("idlerpg_event_log_limit", 200)) or 200
)


EVENT_RETENTION_DAYS = int(
    _cfg.get("event_retention_days", config.get("idlerpg_event_retention_days", 90)) or 0
)


EXPORT_EVENT_LIMIT = int(
    _cfg.get("export_event_limit", config.get("idlerpg_export_event_limit", 50)) or 50
)


EXPORT_ENABLED = bool(_cfg.get("export_enabled", config.get("idlerpg_export_enabled", True)))


EXPORT_PATH = str(_cfg.get("export_path", config.get("idlerpg_export_path", "data/idlerpg")) or "data/idlerpg")


EXPORT_PUBLIC_BASE_URL = str(_cfg.get("export_public_base_url", config.get("idlerpg_export_public_base_url", "")) or "").rstrip("/")


EXPORT_TOP_LIMIT = int(_cfg.get("export_top_limit", config.get("idlerpg_export_top_limit", 50)) or 50)


SEASON_ENABLED = bool(_cfg.get("season_enabled", config.get("idlerpg_season_enabled", False)))


SEASON_DURATION_DAYS = int(_cfg.get("season_duration_days", config.get("idlerpg_season_duration_days", 90)) or 0)


SEASON_RESET_ON_ROLLOVER = bool(_cfg.get("season_reset_on_rollover", config.get("idlerpg_season_reset_on_rollover", False)))


SEASON_HOF_SIZE = int(_cfg.get("season_hof_size", config.get("idlerpg_season_hof_size", 10)) or 10)


MAP_STEP_PER_TICK = int(_cfg.get("map_step_per_tick", config.get("idlerpg_map_step_per_tick", 5)) or 0)


COUNT_COMMAND_MESSAGES = bool(
    _cfg.get("count_command_messages", config.get("idlerpg_count_command_messages", False))
)


ANNOUNCE_LOGIN = bool(_cfg.get("announce_login", config.get("idlerpg_announce_login", True)))


ANNOUNCE_TOP_INTERVAL = int(
    _cfg.get("announce_top_interval", config.get("idlerpg_announce_top_interval", 21600)) or 0
)


ANNOUNCE_TOP_LIMIT = int(
    _cfg.get("announce_top_limit", config.get("idlerpg_announce_top_limit", 5)) or 5
)


UPDATE_ROOM_TOPIC = bool(
    _cfg.get("update_room_topic", config.get("idlerpg_update_room_topic", False))
)


TOPIC_UPDATE_INTERVAL = int(
    _cfg.get("topic_update_interval", config.get("idlerpg_topic_update_interval", 14400)) or 0
)


TOPIC_CUSTOM_TEXT = str(
    _cfg.get("topic_custom_text", config.get("idlerpg_topic_custom_text", ""))
    or EXPORT_PUBLIC_BASE_URL
    or "IdleRPG"
).strip()


ITEM_DAMAGE_EVENT_WEIGHT = float(
    _cfg.get("item_damage_event_weight", config.get("idlerpg_item_damage_event_weight", 0.08)) or 0.08
)


ITEM_STEAL_EVENT_WEIGHT = float(
    _cfg.get("item_steal_event_weight", config.get("idlerpg_item_steal_event_weight", 0.04)) or 0.04
)


LEVEL_REWARD_MIN_LEVEL = int(
    _cfg.get("level_reward_min_level", config.get("idlerpg_level_reward_min_level", 50)) or 50
)


SEASON_ACHIEVEMENT_GATES_ENABLED = bool(
    _cfg.get("season_achievement_gates_enabled", config.get("idlerpg_season_achievement_gates_enabled", True))
)


MANUAL_DUEL_MAX_DISTANCE = int(
    _cfg.get("manual_duel_max_distance", config.get("idlerpg_manual_duel_max_distance", 10)) or 10
)


MANUAL_DUEL_COOLDOWN_SECONDS = int(
    _cfg.get("manual_duel_cooldown_seconds", config.get("idlerpg_manual_duel_cooldown_seconds", 3600)) or 0
)


ROOM_TASKS: dict[str, asyncio.Task] = {}

__all__ = [
    'log',
    '_cfg',
    'TICK_SECONDS',
    'RP_BASE',
    'RP_STEP',
    'PENALTY_STEP',
    'MESSAGE_PENALTY',
    'LOGOUT_PENALTY',
    'LOGOUT_GRACE_SECONDS',
    'MAX_PENALTY',
    'PAGE_SIZE',
    'MAP_X',
    'MAP_Y',
    'QUEST_MIN_LEVEL',
    'QUEST_INTERVAL',
    'QUEST_MIN_DURATION',
    'QUEST_MAX_DURATION',
    'EVENT_CHANCE',
    'ITEM_CHANCE',
    'BATTLE_EVENT_WEIGHT',
    'ITEM_EVENT_WEIGHT',
    'ALIGNMENT_EVENT_WEIGHT',
    'CRITICAL_STRIKE_CHANCE',
    'ITEM_DROP_CHANCE',
    'TEAM_BATTLE_EVENT_WEIGHT',
    'BATTLE_WIN_MIN_PERCENT',
    'BATTLE_LOSS_MIN_PERCENT',
    'CRITICAL_MIN_PERCENT',
    'CRITICAL_MAX_PERCENT',
    'GODSEND_MIN_PERCENT',
    'GODSEND_MAX_PERCENT',
    'CALAMITY_MIN_PERCENT',
    'CALAMITY_MAX_PERCENT',
    'ALIGNMENT_BONUS_PERCENT',
    'QUEST_REWARD_PERCENT',
    'TEAM_BATTLE_PERCENT',
    'UNIQUE_ITEMS_ENABLED',
    'UNIQUE_ITEM_MIN_LEVEL',
    'UNIQUE_ITEM_CHANCE',
    'EVENT_LOG_LIMIT',
    'EVENT_RETENTION_DAYS',
    'EXPORT_EVENT_LIMIT',
    'EXPORT_ENABLED',
    'EXPORT_PATH',
    'EXPORT_PUBLIC_BASE_URL',
    'EXPORT_TOP_LIMIT',
    'SEASON_ENABLED',
    'SEASON_DURATION_DAYS',
    'SEASON_RESET_ON_ROLLOVER',
    'SEASON_HOF_SIZE',
    'MAP_STEP_PER_TICK',
    'COUNT_COMMAND_MESSAGES',
    'ANNOUNCE_LOGIN',
    'ANNOUNCE_TOP_INTERVAL',
    'ANNOUNCE_TOP_LIMIT',
    'UPDATE_ROOM_TOPIC',
    'TOPIC_UPDATE_INTERVAL',
    'TOPIC_CUSTOM_TEXT',
    'ITEM_DAMAGE_EVENT_WEIGHT',
    'ITEM_STEAL_EVENT_WEIGHT',
    'LEVEL_REWARD_MIN_LEVEL',
    'SEASON_ACHIEVEMENT_GATES_ENABLED',
    'MANUAL_DUEL_MAX_DISTANCE',
    'MANUAL_DUEL_COOLDOWN_SECONDS',
    'ROOM_TASKS',
]
