"""IdleRPG configuration derived from the central declarative config schema."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from utils.config import config
from utils.config.runtime import _idlerpg_values
from utils.config.spec import IDLERPG_FIELDS

log = logging.getLogger(__name__)

_cfg = config.get("idlerpg", {}) if isinstance(config.get("idlerpg", {}), dict) else {}


def _setting(key: str, legacy_key: str, default: object) -> object:
    """Return one IdleRPG setting while preserving explicit zero values."""
    field = IDLERPG_FIELDS.get(key)
    fallback = field.default if field is not None else default
    effective_legacy = field.legacy_key if field is not None else legacy_key
    value = _cfg[key] if key in _cfg else config.get(str(effective_legacy), fallback)
    return fallback if value is None else value


def _derived_website_public_base_url(export_base_url: str) -> str:
    """Derive a website root from an export URL that ends in /data."""
    normalized = str(export_base_url or "").rstrip("/")
    if normalized.lower().endswith("/data"):
        return normalized[:-5]
    return ""


TICK_SECONDS: Any
RP_BASE: Any
RP_STEP: Any
PENALTY_STEP: Any
MESSAGE_PENALTY: Any
LOGOUT_PENALTY: Any
LOGOUT_GRACE_SECONDS: Any
MAX_PENALTY: Any
COUNT_COMMAND_MESSAGES: Any
PAGE_SIZE: Any
MAP_X: Any
MAP_Y: Any
MAP_STEP_PER_SECOND: Any
MAP_STEP_PER_TICK: Any
GRID_BATTLE_ENABLED: Any
QUEST_GRID_STEP_SECONDS: Any
QUEST_MIN_LEVEL: Any
QUEST_MIN_ONLINE_SECONDS: Any
QUEST_INTERVAL: Any
QUEST_MAX_PER_DAY: Any
QUEST_MIN_DURATION: Any
QUEST_MAX_DURATION: Any
QUEST_GRID_ENABLED: Any
QUEST_GRID_WEIGHT: Any
QUEST_GRID_MIN_POINTS: Any
QUEST_GRID_MAX_POINTS: Any
QUEST_TIME_ENABLED: Any
QUEST_TIME_WEIGHT: Any
QUEST_TIME_MIN_DURATION: Any
QUEST_TIME_MAX_DURATION: Any
EVENT_CHANCE: Any
ITEM_CHANCE: Any
BATTLE_EVENT_WEIGHT: Any
TEAM_BATTLE_EVENT_WEIGHT: Any
BOSS_EVENT_WEIGHT: Any
ITEM_EVENT_WEIGHT: Any
ITEM_DAMAGE_EVENT_WEIGHT: Any
ITEM_STEAL_EVENT_WEIGHT: Any
ALIGNMENT_EVENT_WEIGHT: Any
CRITICAL_STRIKE_CHANCE: Any
CRITICAL_STRIKE_CHANCE_GOOD: Any
CRITICAL_STRIKE_CHANCE_EVIL: Any
ITEM_DROP_CHANCE: Any
LEVEL_BATTLE_CHANCE_BELOW_25: Any
LEVEL_BATTLE_CHANCE_AT_25: Any
BATTLE_WIN_MIN_PERCENT: Any
BATTLE_LOSS_MIN_PERCENT: Any
CRITICAL_MIN_PERCENT: Any
CRITICAL_MAX_PERCENT: Any
GODSEND_MIN_PERCENT: Any
GODSEND_MAX_PERCENT: Any
CALAMITY_MIN_PERCENT: Any
CALAMITY_MAX_PERCENT: Any
ALIGNMENT_BONUS_PERCENT: Any
QUEST_REWARD_PERCENT: Any
TEAM_BATTLE_PERCENT: Any
BOSS_MIN_PLAYERS: Any
BOSS_MAX_PLAYERS: Any
BOSS_MIN_LEVEL: Any
BOSS_REWARD_PERCENT: Any
BOSS_LOSS_PERCENT: Any
BOSS_POWER_MIN_FACTOR: Any
BOSS_POWER_MAX_FACTOR: Any
MANUAL_DUEL_MAX_DISTANCE: Any
MANUAL_DUEL_COOLDOWN_SECONDS: Any
UNIQUE_ITEMS_ENABLED: Any
UNIQUE_ITEM_MIN_LEVEL: Any
UNIQUE_ITEM_CHANCE: Any
ANNOUNCE_LOGIN: Any
ANNOUNCE_TOP_INTERVAL: Any
ANNOUNCE_TOP_LIMIT: Any
UPDATE_ROOM_TOPIC: Any
TOPIC_UPDATE_INTERVAL: Any
TOPIC_CUSTOM_TEXT: Any
LEVEL_REWARD_MIN_LEVEL: Any
SEASON_ACHIEVEMENT_GATES_ENABLED: Any
EVENT_LOG_LIMIT: Any
EVENT_RETENTION_DAYS: Any
EXPORT_EVENT_LIMIT: Any
EXPORT_FULL_SEASON_EVENTS: Any
EXPORT_ENABLED: Any
EXPORT_INTERVAL_SECONDS: Any
EXPORT_PATH: Any
EXPORT_PUBLIC_BASE_URL: Any
WEBSITE_PUBLIC_BASE_URL: Any
EXPORT_TOP_LIMIT: Any
SEASON_ENABLED: Any
SEASON_DURATION_DAYS: Any
SEASON_RESET_ON_ROLLOVER: Any
SEASON_HOF_SIZE: Any

_RUNTIME_VALUES = _idlerpg_values(config)
globals().update(_RUNTIME_VALUES)

ROOM_TASKS: dict[str, asyncio.Task] = {}

__all__ = [
    "log",
    "_cfg",
    *_RUNTIME_VALUES,
    "ROOM_TASKS",
]
