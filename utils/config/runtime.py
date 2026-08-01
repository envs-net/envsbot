"""Runtime config apply helpers."""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from typing import Any

from utils.rate_limiter import TokenBucketRateLimiter
from utils.redaction import redact_named

log = logging.getLogger(__name__)

STARTUP_ONLY_KEYS = {
    "jid",
    "password",
    "resource",
    "host",
    "port",
    "direct_tls",
    "db",
    "message_cache_size",
    "message_cache_max_age_days",
}

_RATE_LIMIT_KEYS = {
    "command_rate_limit_capacity",
    "command_rate_limit_refill_amount",
    "command_rate_limit_refill_interval_seconds",
    "command_rate_limit_deny_window_seconds",
    "command_rate_limit_deny_threshold",
    "command_rate_limit_base_block_seconds",
    "command_rate_limit_backoff_multiplier",
    "command_rate_limit_max_block_seconds",
    "command_rate_limit_notify_cooldown_seconds",
}


def _display_key(key: str) -> str:
    from .defaults import _LOWER_TO_PYTHON_CONFIG_KEY

    return _LOWER_TO_PYTHON_CONFIG_KEY.get(key, key.upper())


def _display_value(key: str, value: object) -> str:
    return repr(redact_named(key, value))


def config_change_lines(before: Mapping[str, object], after: Mapping[str, object]) -> list[str]:
    """Return human-readable changed config values."""
    lines = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        lines.append(
            f"- {_display_key(key)}: "
            f"{_display_value(key, old)} → {_display_value(key, new)}"
        )
    return lines


def startup_change_lines(before: Mapping[str, object], after: Mapping[str, object]) -> list[str]:
    """Return changed startup-only settings."""
    return config_change_lines(
        {key: before.get(key) for key in STARTUP_ONLY_KEYS},
        {key: after.get(key) for key in STARTUP_ONLY_KEYS},
    )


def _module(name: str):
    return sys.modules.get(name)


def _set_module_values(module_name: str, values: Mapping[str, object]) -> int:
    module = _module(module_name)
    if module is None:
        return 0
    changed = 0
    for name, value in values.items():
        if getattr(module, name, object()) != value:
            changed += 1
        setattr(module, name, value)
    return changed


def _to_int(value: object, default: int) -> int:
    return int(value if value is not None else default)


def _to_float(value: object, default: float) -> float:
    return float(value if value is not None else default)


def _to_bool(value: object, default: bool = False) -> bool:
    return bool(value if value is not None else default)


def _to_str(value: object, default: str = "") -> str:
    return str(value if value is not None else default)


def _cfg_group(cfg: Mapping[str, object], name: str) -> dict[str, object]:
    value = cfg.get(name)
    return value if isinstance(value, dict) else {}


def _nested_value(
    cfg: Mapping[str, object],
    group_name: str,
    key: str,
    legacy_key: str,
    default: object,
) -> object:
    group = _cfg_group(cfg, group_name)
    if key in group:
        return group[key]
    return cfg.get(legacy_key, default)


def _idlerpg_values(cfg: Mapping[str, object]) -> dict[str, object]:
    def item(key: str, legacy_key: str, default: object) -> object:
        return _nested_value(cfg, "idlerpg", key, legacy_key, default)

    export_public_base_url = _to_str(
        item("export_public_base_url", "idlerpg_export_public_base_url", ""),
        "",
    ).rstrip("/")
    website_public_base_url = _to_str(
        item(
            "website_public_base_url",
            "idlerpg_website_public_base_url",
            "",
        ),
        "",
    ).rstrip("/")
    if not website_public_base_url and export_public_base_url.lower().endswith("/data"):
        website_public_base_url = export_public_base_url[:-5]
    topic_custom_text = _to_str(
        item("topic_custom_text", "idlerpg_topic_custom_text", ""),
        "",
    ) or website_public_base_url or export_public_base_url or "IdleRPG"
    map_step_per_second = item(
        "map_step_per_second",
        "idlerpg_map_step_per_second",
        item("map_step_per_tick", "idlerpg_map_step_per_tick", 1),
    )
    quest_grid_min_points = max(
        2,
        _to_int(item("quest_grid_min_points", "idlerpg_quest_grid_min_points", 2), 2),
    )
    quest_grid_max_points = max(
        quest_grid_min_points,
        _to_int(item("quest_grid_max_points", "idlerpg_quest_grid_max_points", 3), 3),
    )

    return {
        "TICK_SECONDS": _to_int(item("tick_seconds", "idlerpg_tick_seconds", 60) or 60, 60),
        "RP_BASE": _to_int(item("rp_base", "idlerpg_rp_base", 600) or 600, 600),
        "RP_STEP": _to_float(item("rp_step", "idlerpg_rp_step", 1.16) or 1.16, 1.16),
        "PENALTY_STEP": _to_float(item("penalty_step", "idlerpg_penalty_step", 1.14) or 1.14, 1.14),
        "MESSAGE_PENALTY": _to_int(item("message_penalty", "idlerpg_message_penalty", 1) or 1, 1),
        "LOGOUT_PENALTY": _to_int(item("logout_penalty", "idlerpg_logout_penalty", 20) or 20, 20),
        "LOGOUT_GRACE_SECONDS": _to_int(item("logout_grace_seconds", "idlerpg_logout_grace_seconds", 300) or 0, 0),
        "MAX_PENALTY": _to_int(item("max_penalty", "idlerpg_max_penalty", 604800) or 0, 0),
        "PAGE_SIZE": _to_int(item("page_size", "idlerpg_page_size", 10) or 10, 10),
        "MAP_X": _to_int(item("map_x", "idlerpg_map_x", 500) or 500, 500),
        "MAP_Y": _to_int(item("map_y", "idlerpg_map_y", 500) or 500, 500),
        "QUEST_MIN_LEVEL": _to_int(item("quest_min_level", "idlerpg_quest_min_level", 40) or 40, 40),
        "QUEST_INTERVAL": _to_int(item("quest_interval", "idlerpg_quest_interval", 21600) or 21600, 21600),
        "QUEST_MIN_DURATION": _to_int(item("quest_min_duration", "idlerpg_quest_min_duration", 43200) or 43200, 43200),
        "QUEST_MAX_DURATION": _to_int(item("quest_max_duration", "idlerpg_quest_max_duration", 86400) or 86400, 86400),
        "QUEST_TIME_ENABLED": _to_bool(item("quest_time_enabled", "idlerpg_quest_time_enabled", True), True),
        "QUEST_GRID_ENABLED": _to_bool(item("quest_grid_enabled", "idlerpg_quest_grid_enabled", True), True),
        "QUEST_TIME_WEIGHT": _to_float(item("quest_time_weight", "idlerpg_quest_time_weight", 0.5) or 0.0, 0.5),
        "QUEST_GRID_WEIGHT": _to_float(item("quest_grid_weight", "idlerpg_quest_grid_weight", 0.5) or 0.0, 0.5),
        "QUEST_TIME_MIN_DURATION": _to_int(item("quest_time_min_duration", "idlerpg_quest_time_min_duration", 43200) or 43200, 43200),
        "QUEST_TIME_MAX_DURATION": _to_int(item("quest_time_max_duration", "idlerpg_quest_time_max_duration", 86400) or 86400, 86400),
        "QUEST_MAX_PER_DAY": max(
            0,
            _to_int(item("quest_max_per_day", "idlerpg_quest_max_per_day", 2), 2),
        ),
        "QUEST_GRID_MIN_POINTS": quest_grid_min_points,
        "QUEST_GRID_MAX_POINTS": quest_grid_max_points,
        "EVENT_CHANCE": _to_float(item("event_chance", "idlerpg_event_chance", 0.01), 0.01),
        "ITEM_CHANCE": _to_float(item("item_chance", "idlerpg_item_chance", 0.20), 0.20),
        "BATTLE_EVENT_WEIGHT": _to_float(item("battle_event_weight", "idlerpg_battle_event_weight", 0.55), 0.55),
        "ITEM_EVENT_WEIGHT": _to_float(item("item_event_weight", "idlerpg_item_event_weight", 0.15), 0.15),
        "ALIGNMENT_EVENT_WEIGHT": _to_float(item("alignment_event_weight", "idlerpg_alignment_event_weight", 0.10), 0.10),
        "CRITICAL_STRIKE_CHANCE": _to_float(item("critical_strike_chance", "idlerpg_critical_strike_chance", 1 / 35), 1 / 35),
        "CRITICAL_STRIKE_CHANCE_GOOD": _to_float(item("critical_strike_chance_good", "idlerpg_critical_strike_chance_good", 1 / 50), 1 / 50),
        "CRITICAL_STRIKE_CHANCE_EVIL": _to_float(item("critical_strike_chance_evil", "idlerpg_critical_strike_chance_evil", 1 / 20), 1 / 20),
        "ITEM_DROP_CHANCE": _to_float(item("item_drop_chance", "idlerpg_item_drop_chance", 0.02), 0.02),
        "TEAM_BATTLE_EVENT_WEIGHT": _to_float(item("team_battle_event_weight", "idlerpg_team_battle_event_weight", 0.08), 0.08),
        "BOSS_EVENT_WEIGHT": _to_float(item("boss_event_weight", "idlerpg_boss_event_weight", 0.06), 0.06),
        "BOSS_MIN_PLAYERS": _to_int(item("boss_min_players", "idlerpg_boss_min_players", 3), 3),
        "BOSS_MAX_PLAYERS": _to_int(item("boss_max_players", "idlerpg_boss_max_players", 5), 5),
        "BOSS_MIN_LEVEL": _to_int(item("boss_min_level", "idlerpg_boss_min_level", 10), 10),
        "BOSS_REWARD_PERCENT": _to_int(item("boss_reward_percent", "idlerpg_boss_reward_percent", 12), 12),
        "BOSS_LOSS_PERCENT": _to_int(item("boss_loss_percent", "idlerpg_boss_loss_percent", 4), 4),
        "BOSS_POWER_MIN_FACTOR": _to_float(item("boss_power_min_factor", "idlerpg_boss_power_min_factor", 0.75), 0.75),
        "BOSS_POWER_MAX_FACTOR": _to_float(item("boss_power_max_factor", "idlerpg_boss_power_max_factor", 1.25), 1.25),
        "BATTLE_WIN_MIN_PERCENT": _to_int(item("battle_win_min_percent", "idlerpg_battle_win_min_percent", 7) or 7, 7),
        "BATTLE_LOSS_MIN_PERCENT": _to_int(item("battle_loss_min_percent", "idlerpg_battle_loss_min_percent", 7) or 7, 7),
        "CRITICAL_MIN_PERCENT": _to_int(item("critical_min_percent", "idlerpg_critical_min_percent", 5) or 5, 5),
        "CRITICAL_MAX_PERCENT": _to_int(item("critical_max_percent", "idlerpg_critical_max_percent", 25) or 25, 25),
        "GODSEND_MIN_PERCENT": _to_int(item("godsend_min_percent", "idlerpg_godsend_min_percent", 5) or 5, 5),
        "GODSEND_MAX_PERCENT": _to_int(item("godsend_max_percent", "idlerpg_godsend_max_percent", 12) or 12, 12),
        "CALAMITY_MIN_PERCENT": _to_int(item("calamity_min_percent", "idlerpg_calamity_min_percent", 5) or 5, 5),
        "CALAMITY_MAX_PERCENT": _to_int(item("calamity_max_percent", "idlerpg_calamity_max_percent", 12) or 12, 12),
        "ALIGNMENT_BONUS_PERCENT": _to_int(item("alignment_bonus_percent", "idlerpg_alignment_bonus_percent", 7) or 7, 7),
        "QUEST_REWARD_PERCENT": _to_int(item("quest_reward_percent", "idlerpg_quest_reward_percent", 25) or 25, 25),
        "QUEST_MIN_ONLINE_SECONDS": _to_int(item("quest_min_online_seconds", "idlerpg_quest_min_online_seconds", 36000) or 0, 0),
        "TEAM_BATTLE_PERCENT": _to_int(item("team_battle_percent", "idlerpg_team_battle_percent", 20) or 20, 20),
        "UNIQUE_ITEMS_ENABLED": _to_bool(item("unique_items_enabled", "idlerpg_unique_items_enabled", True), True),
        "UNIQUE_ITEM_MIN_LEVEL": _to_int(item("unique_item_min_level", "idlerpg_unique_item_min_level", 25) or 25, 25),
        "UNIQUE_ITEM_CHANCE": _to_float(item("unique_item_chance", "idlerpg_unique_item_chance", 0.025), 0.025),
        "EVENT_LOG_LIMIT": _to_int(item("event_log_limit", "idlerpg_event_log_limit", 200) or 200, 200),
        "EVENT_RETENTION_DAYS": _to_int(item("event_retention_days", "idlerpg_event_retention_days", 90) or 0, 0),
        "EXPORT_EVENT_LIMIT": _to_int(item("export_event_limit", "idlerpg_export_event_limit", 50) or 50, 50),
        "EXPORT_ENABLED": _to_bool(item("export_enabled", "idlerpg_export_enabled", True), True),
        "EXPORT_INTERVAL_SECONDS": _to_int(
            item(
                "export_interval_seconds",
                "idlerpg_export_interval_seconds",
                300,
            )
            or 0,
            0,
        ),
        "EXPORT_PATH": _to_str(item("export_path", "idlerpg_export_path", "data/idlerpg") or "data/idlerpg", "data/idlerpg"),
        "EXPORT_PUBLIC_BASE_URL": export_public_base_url,
        "WEBSITE_PUBLIC_BASE_URL": website_public_base_url,
        "EXPORT_TOP_LIMIT": _to_int(item("export_top_limit", "idlerpg_export_top_limit", 50) or 50, 50),
        "SEASON_ENABLED": _to_bool(item("season_enabled", "idlerpg_season_enabled", False), False),
        "SEASON_DURATION_DAYS": _to_int(item("season_duration_days", "idlerpg_season_duration_days", 90) or 0, 0),
        "SEASON_RESET_ON_ROLLOVER": _to_bool(item("season_reset_on_rollover", "idlerpg_season_reset_on_rollover", False), False),
        "SEASON_HOF_SIZE": _to_int(item("season_hof_size", "idlerpg_season_hof_size", 10) or 10, 10),
        "MAP_STEP_PER_SECOND": _to_int(map_step_per_second or 0, 0),
        "MAP_STEP_PER_TICK": _to_int(map_step_per_second or 0, 0),
        "GRID_BATTLE_ENABLED": _to_bool(item("grid_battle_enabled", "idlerpg_grid_battle_enabled", True), True),
        "QUEST_GRID_STEP_SECONDS": _to_int(item("quest_grid_step_seconds", "idlerpg_quest_grid_step_seconds", 30) or 30, 30),
        "COUNT_COMMAND_MESSAGES": _to_bool(item("count_command_messages", "idlerpg_count_command_messages", False), False),
        "ANNOUNCE_LOGIN": _to_bool(item("announce_login", "idlerpg_announce_login", True), True),
        "ANNOUNCE_TOP_INTERVAL": _to_int(item("announce_top_interval", "idlerpg_announce_top_interval", 21600) or 0, 0),
        "ANNOUNCE_TOP_LIMIT": _to_int(item("announce_top_limit", "idlerpg_announce_top_limit", 5) or 5, 5),
        "UPDATE_ROOM_TOPIC": _to_bool(item("update_room_topic", "idlerpg_update_room_topic", False), False),
        "TOPIC_UPDATE_INTERVAL": _to_int(item("topic_update_interval", "idlerpg_topic_update_interval", 14400) or 0, 0),
        "TOPIC_CUSTOM_TEXT": topic_custom_text.strip(),
        "ITEM_DAMAGE_EVENT_WEIGHT": _to_float(item("item_damage_event_weight", "idlerpg_item_damage_event_weight", 0.08), 0.08),
        "ITEM_STEAL_EVENT_WEIGHT": _to_float(item("item_steal_event_weight", "idlerpg_item_steal_event_weight", 0.04), 0.04),
        "LEVEL_BATTLE_CHANCE_BELOW_25": _to_float(item("level_battle_chance_below_25", "idlerpg_level_battle_chance_below_25", 0.25), 0.25),
        "LEVEL_BATTLE_CHANCE_AT_25": _to_float(item("level_battle_chance_at_25", "idlerpg_level_battle_chance_at_25", 1.0), 1.0),
        "LEVEL_REWARD_MIN_LEVEL": _to_int(item("level_reward_min_level", "idlerpg_level_reward_min_level", 50) or 50, 50),
        "SEASON_ACHIEVEMENT_GATES_ENABLED": _to_bool(item("season_achievement_gates_enabled", "idlerpg_season_achievement_gates_enabled", True), True),
        "MANUAL_DUEL_MAX_DISTANCE": _to_int(item("manual_duel_max_distance", "idlerpg_manual_duel_max_distance", 10) or 10, 10),
        "MANUAL_DUEL_COOLDOWN_SECONDS": _to_int(item("manual_duel_cooldown_seconds", "idlerpg_manual_duel_cooldown_seconds", 3600) or 0, 0),
    }


def _rss_values(cfg: Mapping[str, object]) -> dict[str, object]:
    trusted_max_feeds = cfg.get("rss_trusted_max_feeds")
    return {
        "DEFAULT_POLL_INTERVAL": _to_int(cfg.get("rss_global_query_interval") or 1200, 1200),
        "RSS_RETRY_INITIAL_DELAY": max(1, _to_int(cfg.get("rss_retry_initial_delay") or 300, 300)),
        "RSS_RETRY_BACKOFF_MULTIPLIER": max(1.0, _to_float(cfg.get("rss_retry_backoff_multiplier") or 2.0, 2.0)),
        "MAX_BACKOFF_TIME": max(1, _to_int(cfg.get("rss_max_backoff_time") or 3600, 3600)),
        "RSS_USER_AGENT": _to_str(cfg.get("rss_user_agent") or cfg.get("http_user_agent") or "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)"),
        "RSS_FETCH_TIMEOUT_SECONDS": _to_float(cfg.get("rss_fetch_timeout_seconds") or cfg.get("http_timeout_seconds") or 8, 8),
        "RSS_STARTUP_STAGGER_SECONDS": max(
            0.0,
            _to_float(
                2.0
                if cfg.get("rss_startup_stagger_seconds") is None
                else cfg.get("rss_startup_stagger_seconds"),
                2.0,
            ),
        ),
        "RSS_MAX_REDIRECTS": max(1, _to_int(cfg.get("rss_max_redirects") or 5, 5)),
        "RSS_MAX_READ_BYTES": max(4096, _to_int(cfg.get("rss_max_read_bytes") or 1048576, 1048576)),
        "ALLOW_PRIVATE_FETCH_URLS": _to_bool(cfg.get("allow_private_fetch_urls"), False),
        "RSS_LIST_PAGE_SIZE": max(1, _to_int(cfg.get("rss_list_page_size") or 10, 10)),
        "RSS_TRUSTED_MAX_FEEDS": max(
            0,
            _to_int(10 if trusted_max_feeds is None else trusted_max_feeds, 10),
        ),
        "RSS_MAX_ENTRIES_PER_POLL": max(1, _to_int(cfg.get("rss_max_entries_per_poll") or 10, 10)),
        "RSS_BROKEN_ERROR_THRESHOLD": max(1, _to_int(cfg.get("rss_broken_error_threshold") or 3, 3)),
        "RSS_TEMPLATE_MAX_LENGTH": max(1, _to_int(cfg.get("rss_template_max_length") or 1000, 1000)),
        "SIMILARITY_THRESHOLD": _to_float(cfg.get("rss_similarity_threshold") or 0.8, 0.8),
    }


def _duck_values(cfg: Mapping[str, object]) -> dict[str, object]:
    duck_cfg = _cfg_group(cfg, "ducks")
    min_messages = max(1, _to_int(duck_cfg.get("min_messages", 150), 150))
    max_messages = max(
        min_messages,
        _to_int(duck_cfg.get("max_messages", 500), 500),
    )
    return {
        "duck_cfg": duck_cfg,
        "DEFAULT_MIN_MESSAGES": min_messages,
        "DEFAULT_MAX_MESSAGES": max_messages,
        "DUCK_SPAWN_CHANCE": max(
            1,
            _to_int(duck_cfg.get("spawn_chance", 20), 20),
        ),
        "MAX_DUCKS_PER_DAY": max(
            0,
            _to_int(duck_cfg.get("max_ducks_per_day", 3), 3),
        ),
        "DUCK_TIMEOUT": max(0, _to_int(duck_cfg.get("timeout", 0), 0)),
        "COUNT_COMMAND_MESSAGES": _to_bool(duck_cfg.get("count_commands"), False),
        "DUCK_STATE_SAVE_EVERY": max(
            1,
            _to_int(duck_cfg.get("state_save_every", 1), 1),
        ),
    }


def refresh_runtime_config_constants(cfg: Mapping[str, object]) -> list[str]:
    """Refresh module-level constants that snapshot config.py at import time."""
    refreshed: list[str] = []
    idlerpg_values = _idlerpg_values(cfg)
    rss_values = _rss_values(cfg)
    reminder_values = {
        "REMINDER_ENABLED": _to_bool(cfg.get("reminder_enabled"), True),
        "REMINDER_DEFAULT_TIMEZONE": _to_str(
            cfg.get("reminder_default_timezone") or "UTC",
            "UTC",
        ),
    }
    max_room_nicks = _cfg_group(cfg, "users").get("max_room_nicks", 5)
    module_values: dict[str, dict[str, object]] = {
        "utils.formatting": {
            "DEFAULT_PAGINATION": cfg.get("default_pagination", "all"),
        },
        "core_plugins.users": {
            "MAX_ROOM_NICKS": max_room_nicks,
        },
        "core_plugins.users.roles": {"MAX_ROOM_NICKS": max_room_nicks},
        "core_plugins.users.tracking": {"MAX_ROOM_NICKS": max_room_nicks},
        "plugins.ducks": _duck_values(cfg),
        "plugins.idlerpg": idlerpg_values,
        "plugins.idlerpg.config": idlerpg_values,
        "plugins.idlerpg.handlers": {
            key: idlerpg_values[key]
            for key in ("COUNT_COMMAND_MESSAGES", "MESSAGE_PENALTY")
        },
        "plugins.rss": rss_values,
        "plugins.rss.config": rss_values,
        "plugins.rss.tasks": {
            key: rss_values[key]
            for key in (
                "DEFAULT_POLL_INTERVAL",
                "RSS_MAX_ENTRIES_PER_POLL",
                "RSS_STARTUP_STAGGER_SECONDS",
            )
        },
        "plugins.rss.commands": {
            "DEFAULT_POLL_INTERVAL": rss_values["DEFAULT_POLL_INTERVAL"],
            "RSS_BROKEN_ERROR_THRESHOLD": rss_values["RSS_BROKEN_ERROR_THRESHOLD"],
            "RSS_TRUSTED_MAX_FEEDS": rss_values["RSS_TRUSTED_MAX_FEEDS"],
        },
        "plugins.rss.store": {
            key: rss_values[key]
            for key in (
                "RSS_RETRY_INITIAL_DELAY",
                "RSS_RETRY_BACKOFF_MULTIPLIER",
                "MAX_BACKOFF_TIME",
            )
        },
        "plugins.rss.fetch": {
            key: rss_values[key]
            for key in (
                "RSS_USER_AGENT",
                "RSS_FETCH_TIMEOUT_SECONDS",
                "RSS_MAX_REDIRECTS",
                "RSS_MAX_READ_BYTES",
                "ALLOW_PRIVATE_FETCH_URLS",
                "SIMILARITY_THRESHOLD",
            )
        },
        "plugins.rss.formatting": {
            "RSS_LIST_PAGE_SIZE": rss_values["RSS_LIST_PAGE_SIZE"],
            "RSS_TEMPLATE_MAX_LENGTH": rss_values["RSS_TEMPLATE_MAX_LENGTH"],
        },
        "plugins.reminder": reminder_values,
        "plugins.reminder.runtime": {
            "REMINDER_ENABLED": reminder_values["REMINDER_ENABLED"],
        },
        "plugins.reminder.parsing": {
            "REMINDER_DEFAULT_TIMEZONE": reminder_values["REMINDER_DEFAULT_TIMEZONE"],
        },
        "plugins.urlcheck": {
            "URLCHECK_WAIT_SECONDS": _to_int(cfg.get("urlcheck_wait_seconds") or 120, 120),
            "URLCHECK_FETCH_TIMEOUT": _to_float(cfg.get("urlcheck_fetch_timeout_seconds") or cfg.get("http_timeout_seconds") or 8, 8),
            "URLCHECK_MAX_REDIRECTS": max(1, _to_int(cfg.get("urlcheck_max_redirects") or 5, 5)),
            "URLCHECK_MAX_READ_BYTES": max(4096, _to_int(cfg.get("urlcheck_max_read_bytes") or 65536, 65536)),
            "URLCHECK_USER_AGENT": _to_str(cfg.get("urlcheck_user_agent") or cfg.get("http_user_agent") or "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)"),
            "ALLOW_PRIVATE_FETCH_URLS": _to_bool(cfg.get("allow_private_fetch_urls"), False),
        },
        "plugins.info": {
            "INFO_HTTP_TIMEOUT": _to_float(cfg.get("http_timeout_seconds") or 8, 8),
            "INFO_HTTP_USER_AGENT": _to_str(cfg.get("http_user_agent") or "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)"),
        },
        "plugins.sed": {
            "REGEX_TIMEOUT": _to_float(cfg.get("sed_regex_timeout") or 1.0, 1.0),
            "MAX_PATTERN_LENGTH": _to_int(cfg.get("sed_max_pattern_length") or 256, 256),
            "MAX_REPLACEMENT_LENGTH": _to_int(cfg.get("sed_max_replacement_length") or 1000, 1000),
            "MAX_INPUT_LENGTH": _to_int(cfg.get("sed_max_input_length") or 5000, 5000),
            "MAX_OUTPUT_LENGTH": _to_int(cfg.get("sed_max_output_length") or 8000, 8000),
        },
        "plugins.poll": {
            "MAX_OPTIONS": _to_int(cfg.get("poll_max_options") or 10, 10),
            "MAX_QUESTION_LEN": _to_int(cfg.get("poll_max_question_len") or 200, 200),
            "MAX_OPTION_LEN": _to_int(cfg.get("poll_max_option_len") or 100, 100),
            "MAX_HISTORY_PER_ROOM": _to_int(cfg.get("poll_max_history_per_room") or 50, 50),
        },
        "plugins.pin": {
            "PAGE_SIZE": _to_int(cfg.get("pin_page_size") or 10, 10),
        },
        "plugins.translate": {
            "TRANSLATE_FROM": _to_str(
                cfg.get("translate_from") or "auto",
                "auto",
            ),
            "TRANSLATE_TO": (
                None
                if cfg.get("translate_to") is None
                else _to_str(cfg.get("translate_to"))
            ),
            "TRANSLATE_TIMEOUT_SECONDS": max(
                1.0,
                _to_float(
                    cfg.get("translate_timeout_seconds")
                    or cfg.get("http_timeout_seconds")
                    or 8,
                    8,
                ),
            ),
            "TRANSLATE_MAX_INPUT_LENGTH": max(
                1, _to_int(cfg.get("translate_max_input_length") or 2000, 2000)
            ),
            "TRANSLATE_MAX_OUTPUT_LENGTH": max(
                1, _to_int(cfg.get("translate_max_output_length") or 6000, 6000)
            ),
            "TRANSLATE_MAX_RESPONSE_BYTES": max(
                4096,
                _to_int(cfg.get("translate_max_response_bytes") or 262144, 262144),
            ),
        },
        "plugins.karma": {
            "KARMA_DELAY_SECONDS": _to_int(cfg.get("karma_delay_seconds") or 60, 60),
        },
        "plugins.tell": {
            "TELL_DELIVERY_DELAY_SECONDS": _to_int(cfg.get("tell_delivery_delay_seconds") or 5, 5),
        },
        "plugins.xkcd": {
            "CHECK_INTERVAL": _to_int(cfg.get("xkcd_check_interval") or 3600, 3600),
            "INDEX_START_DELAY_SECONDS": _to_int(cfg.get("xkcd_index_start_delay_seconds") or 30, 30),
            "INDEX_REQUEST_DELAY_SECONDS": _to_float(cfg.get("xkcd_index_request_delay_seconds") or 0.15, 0.15),
            "XKCD_HTTP_TIMEOUT": _to_float(cfg.get("xkcd_http_timeout") or cfg.get("http_timeout_seconds") or 10, 10),
        },
        "plugins.xmpp": {
            "XMPP_QUERY_TIMEOUT_SECONDS": _to_float(cfg.get("xmpp_query_timeout_seconds") or 8, 8),
            "XMPP_HTTP_TIMEOUT_SECONDS": _to_float(cfg.get("http_timeout_seconds") or 8, 8),
            "XMPP_COMPLIANCE_MAX_READ_BYTES": max(
                8192,
                _to_int(cfg.get("xmpp_compliance_max_read_bytes") or 262144, 262144),
            ),
        },
        "plugins.birthday_notify": {
            "BDAY_CACHE_TTL_SECONDS": _to_int(cfg.get("birthday_cache_ttl_seconds") or 43200, 43200),
            "INITIAL_SCAN_DELAY_SECONDS": _to_int(cfg.get("birthday_initial_scan_delay_seconds") or 10, 10),
            "CHECK_LOOP_INTERVAL_SECONDS": _to_int(cfg.get("birthday_check_interval_seconds") or 3600, 3600),
        },
        "plugins.weather": {
            "WEATHER_HTTP_TIMEOUT": _to_float(cfg.get("http_timeout_seconds") or 8, 8),
        },
    }

    for module_name, values in module_values.items():
        changed = _set_module_values(module_name, values)
        if changed:
            refreshed.append(f"{module_name} ({changed})")

    return refreshed


def apply_log_level(level_name: str | None) -> str:
    """Apply logging level to the running process and return effective name."""
    level_name = str(level_name or "INFO").upper().strip()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level_name = "INFO"
        level = logging.INFO
    logging.getLogger().setLevel(level)
    logging.getLogger("envsbot").setLevel(level)
    third_party_level = max(level, logging.INFO)
    logging.getLogger("slixmpp").setLevel(third_party_level)
    logging.getLogger("aiosqlite").setLevel(third_party_level)
    return level_name


def _rate_limiter_from_config(cfg: Mapping[str, object]) -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(
        capacity=_to_int(cfg.get("command_rate_limit_capacity") or 4, 4),
        refill_amount=_to_int(cfg.get("command_rate_limit_refill_amount") or 1, 1),
        refill_interval=_to_float(cfg.get("command_rate_limit_refill_interval_seconds") or 0.5, 0.5),
        deny_window=_to_float(cfg.get("command_rate_limit_deny_window_seconds") or 10.0, 10.0),
        deny_threshold=_to_int(cfg.get("command_rate_limit_deny_threshold") or 6, 6),
        base_block_seconds=_to_float(cfg.get("command_rate_limit_base_block_seconds") or 30.0, 30.0),
        backoff_multiplier=_to_float(cfg.get("command_rate_limit_backoff_multiplier") or 2.0, 2.0),
        max_block_seconds=_to_float(cfg.get("command_rate_limit_max_block_seconds") or 3600.0, 3600.0),
        notify_cooldown=_to_float(cfg.get("command_rate_limit_notify_cooldown_seconds") or 10.0, 10.0),
    )


def apply_runtime_config(bot: Any, before: Mapping[str, object], after: Mapping[str, object]) -> list[str]:
    """Apply config values that can safely change without reconnecting."""
    notes: list[str] = []

    old_prefix = getattr(bot, "prefix", None)
    bot.prefix = _to_str(after.get("prefix") or old_prefix or ",", ",")
    bot.nick = _to_str(after.get("nick") or getattr(bot, "nick", "bot"), "bot")

    if old_prefix != bot.prefix:
        notes.append(f"Prefix changed from {old_prefix!r} to {bot.prefix!r}.")

    old_loglevel = before.get("loglevel")
    new_loglevel = apply_log_level(str(after.get("loglevel", "INFO")))
    if str(old_loglevel).upper() != new_loglevel:
        notes.append(f"Log level is now {new_loglevel}.")

    if any(before.get(key) != after.get(key) for key in _RATE_LIMIT_KEYS):
        bot.rate_limiter = _rate_limiter_from_config(after)
        notes.append("Command rate limiter settings reloaded; in-memory limiter state was reset.")

    refreshed = refresh_runtime_config_constants(after)
    if refreshed:
        notes.append("Runtime plugin constants refreshed: " + ", ".join(refreshed) + ".")

    return notes


async def restart_reloadable_plugin_tasks(bot: Any, before: Mapping[str, object], after: Mapping[str, object]) -> list[str]:
    """Restart background task-owning plugins when their timing config changed."""
    affected = {
        "birthday_notify": {
            "birthday_initial_scan_delay_seconds",
            "birthday_check_interval_seconds",
        },
        "idlerpg": {"idlerpg", "room_plugin_defaults"},
        "rss": {
            "rss_global_query_interval",
            "rss_retry_initial_delay",
            "rss_retry_backoff_multiplier",
            "rss_max_backoff_time",
            "rss_fetch_timeout_seconds",
            "rss_max_redirects",
            "rss_max_read_bytes",
            "allow_private_fetch_urls",
        },
        "xkcd": {
            "xkcd_check_interval",
            "xkcd_index_start_delay_seconds",
            "xkcd_index_request_delay_seconds",
            "xkcd_http_timeout",
            "http_timeout_seconds",
        },
    }
    manager = getattr(bot, "bot_plugins", None)
    if manager is None or not hasattr(manager, "restart_tasks"):
        return []

    restarted: list[str] = []
    for plugin_name, keys in affected.items():
        if not any(before.get(key) != after.get(key) for key in keys):
            continue
        if getattr(manager, "plugins", {}).get(plugin_name) is None:
            continue
        try:
            ok, message, cancelled = await manager.restart_tasks(plugin_name)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            log.exception("Failed to restart %s tasks after config reload", plugin_name)
            restarted.append(f"{plugin_name}: failed ({exc})")
            continue
        status = "ok" if ok else "skipped"
        restarted.append(f"{plugin_name}: {status}, {cancelled} task(s) cancelled ({message})")
    return restarted


__all__ = [
    "STARTUP_ONLY_KEYS",
    "apply_log_level",
    "apply_runtime_config",
    "config_change_lines",
    "refresh_runtime_config_constants",
    "restart_reloadable_plugin_tasks",
    "startup_change_lines",
]
