from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import utils.config.runtime as runtime


def test_message_cache_age_is_startup_only():
    assert "message_cache_size" in runtime.STARTUP_ONLY_KEYS
    assert "message_cache_max_age_days" in runtime.STARTUP_ONLY_KEYS

    lines = runtime.startup_change_lines(
        {"message_cache_max_age_days": 30},
        {"message_cache_max_age_days": 14},
    )

    assert any("MESSAGE_CACHE_MAX_AGE_DAYS" in line for line in lines)


def test_database_connection_pragmas_are_startup_only():
    assert "database_busy_timeout_ms" in runtime.STARTUP_ONLY_KEYS
    assert "database_wal_enabled" in runtime.STARTUP_ONLY_KEYS

    lines = runtime.startup_change_lines(
        {
            "database_busy_timeout_ms": 5000,
            "database_wal_enabled": False,
        },
        {
            "database_busy_timeout_ms": 10000,
            "database_wal_enabled": True,
        },
    )

    assert any("DATABASE_BUSY_TIMEOUT_MS" in line for line in lines)
    assert any("DATABASE_WAL_ENABLED" in line for line in lines)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed_key,new_value",
    [
        ("version_check_enabled", True),
        ("version_check_interval", 7200),
        ("version_check_url", "https://example.org/releases/latest"),
        ("version_check_notify_jid", "admin@example.org"),
    ],
)
async def test_version_check_config_changes_restart_admin_worker(
    changed_key,
    new_value,
):
    restart = AsyncMock(return_value=(True, "Plugin _admin tasks restarted", 1))
    manager = SimpleNamespace(
        plugins={"_admin": object()},
        restart_tasks=restart,
    )
    bot = SimpleNamespace(bot_plugins=manager)
    before = {
        "version_check_enabled": False,
        "version_check_interval": 3600,
        "version_check_url": "https://github.com/envs-net/envsbot/releases/latest",
        "version_check_notify_jid": "",
    }
    after = dict(before)
    after[changed_key] = new_value

    result = await runtime.restart_reloadable_plugin_tasks(bot, before, after)

    restart.assert_awaited_once_with("_admin")
    assert result == [
        "_admin: ok, 1 task(s) cancelled (Plugin _admin tasks restarted)"
    ]


def test_rate_limiter_from_config_uses_defaults():
    limiter = runtime._rate_limiter_from_config({})

    assert limiter.capacity == 4.0
    assert limiter.refill_amount == 1.0
    assert limiter.refill_interval == 0.5
    assert limiter.deny_window == 10.0
    assert limiter.deny_threshold == 6
    assert limiter.base_block_seconds == 30.0
    assert limiter.backoff_multiplier == 2.0
    assert limiter.max_block_seconds == 3600.0
    assert limiter.notify_cooldown == 10.0
    assert limiter.max_clients == 2048
    assert limiter.idle_ttl_seconds == 3600.0
    assert limiter.prune_interval_seconds == 60.0


def test_rate_limiter_from_config_uses_all_configured_values():
    limiter = runtime._rate_limiter_from_config({
        "command_rate_limit_capacity": "9",
        "command_rate_limit_refill_amount": "3",
        "command_rate_limit_refill_interval_seconds": "1.25",
        "command_rate_limit_deny_window_seconds": "12.5",
        "command_rate_limit_deny_threshold": "7",
        "command_rate_limit_base_block_seconds": "45.5",
        "command_rate_limit_backoff_multiplier": "3.5",
        "command_rate_limit_max_block_seconds": "7200.5",
        "command_rate_limit_notify_cooldown_seconds": "20.25",
        "command_rate_limit_max_clients": "123",
        "command_rate_limit_idle_ttl_seconds": "456.5",
        "command_rate_limit_prune_interval_seconds": "7.5",
    })

    assert limiter.capacity == 9.0
    assert limiter.refill_amount == 3.0
    assert limiter.refill_interval == 1.25
    assert limiter.deny_window == 12.5
    assert limiter.deny_threshold == 7
    assert limiter.base_block_seconds == 45.5
    assert limiter.backoff_multiplier == 3.5
    assert limiter.max_block_seconds == 7200.5
    assert limiter.notify_cooldown == 20.25
    # The hard client-state ceiling is an internal implementation guard and
    # must not be tunable through runtime configuration.
    assert limiter.max_clients == 2048
    assert limiter.idle_ttl_seconds == 456.5
    assert limiter.prune_interval_seconds == 7.5


def test_apply_runtime_config_replaces_limiter_when_rate_limit_changes():
    old_limiter = object()
    bot = SimpleNamespace(prefix=",", nick="Bot", rate_limiter=old_limiter)

    notes = runtime.apply_runtime_config(
        bot,
        {"prefix": ",", "nick": "Bot", "command_rate_limit_capacity": 4},
        {"prefix": ",", "nick": "Bot", "command_rate_limit_capacity": 6},
    )

    assert bot.rate_limiter is not old_limiter
    assert bot.rate_limiter.capacity == 6.0
    assert any("rate limiter" in note for note in notes)


def test_idlerpg_runtime_values_derive_or_override_website_url():
    derived = runtime._idlerpg_values({
        "idlerpg": {
            "export_public_base_url": "https://envs.net/idlerpg/data/",
        }
    })
    assert derived["EXPORT_PUBLIC_BASE_URL"] == "https://envs.net/idlerpg/data"
    assert derived["WEBSITE_PUBLIC_BASE_URL"] == "https://envs.net/idlerpg"

    explicit = runtime._idlerpg_values({
        "idlerpg": {
            "export_public_base_url": "https://cdn.example.org/game",
            "website_public_base_url": "https://example.org/idlerpg/",
        }
    })
    assert explicit["WEBSITE_PUBLIC_BASE_URL"] == "https://example.org/idlerpg"


def test_idlerpg_runtime_values_use_balanced_quest_defaults():
    values = runtime._idlerpg_values({"idlerpg": {}})

    assert values["QUEST_GRID_STEP_SECONDS"] == 30
    assert values["QUEST_GRID_MIN_POINTS"] == 2
    assert values["QUEST_GRID_MAX_POINTS"] == 3
    assert values["QUEST_MAX_PER_DAY"] == 2


def test_idlerpg_runtime_values_include_original_grid_options():
    values = runtime._idlerpg_values({
        "idlerpg": {
            "map_step_per_second": "2",
            "grid_battle_enabled": False,
            "quest_grid_step_seconds": "5",
            "quest_grid_min_points": "3",
            "quest_grid_max_points": "2",
            "quest_max_per_day": "0",
        }
    })

    assert values["MAP_STEP_PER_SECOND"] == 2
    assert values["MAP_STEP_PER_TICK"] == 2
    assert values["GRID_BATTLE_ENABLED"] is False
    assert values["QUEST_GRID_STEP_SECONDS"] == 5
    assert values["QUEST_GRID_MIN_POINTS"] == 3
    assert values["QUEST_GRID_MAX_POINTS"] == 3
    assert values["QUEST_MAX_PER_DAY"] == 0


def test_idlerpg_runtime_values_support_legacy_map_step_alias():
    values = runtime._idlerpg_values({"idlerpg": {"map_step_per_tick": "3"}})

    assert values["MAP_STEP_PER_SECOND"] == 3
    assert values["MAP_STEP_PER_TICK"] == 3


def test_idlerpg_runtime_values_include_time_quest_options():
    values = runtime._idlerpg_values({
        "idlerpg": {
            "quest_time_enabled": False,
            "quest_grid_enabled": True,
            "quest_time_weight": "0.75",
            "quest_grid_weight": "0.25",
            "quest_time_min_duration": "111",
            "quest_time_max_duration": "222",
        }
    })

    assert values["QUEST_TIME_ENABLED"] is False
    assert values["QUEST_GRID_ENABLED"] is True
    assert values["QUEST_TIME_WEIGHT"] == 0.75
    assert values["QUEST_GRID_WEIGHT"] == 0.25
    assert values["QUEST_TIME_MIN_DURATION"] == 111
    assert values["QUEST_TIME_MAX_DURATION"] == 222


def test_idlerpg_runtime_values_include_original_balance_options():
    values = runtime._idlerpg_values({"idlerpg": {}})

    assert values["CRITICAL_STRIKE_CHANCE"] == 1 / 35
    assert values["CRITICAL_STRIKE_CHANCE_GOOD"] == 1 / 50
    assert values["CRITICAL_STRIKE_CHANCE_EVIL"] == 1 / 20
    assert values["ITEM_DROP_CHANCE"] == 0.02
    assert values["QUEST_MIN_ONLINE_SECONDS"] == 36000
    assert values["LEVEL_BATTLE_CHANCE_BELOW_25"] == 0.25
    assert values["LEVEL_BATTLE_CHANCE_AT_25"] == 1.0


def test_idlerpg_runtime_values_preserve_zero_chances_and_include_boss_options():
    values = runtime._idlerpg_values({
        "idlerpg": {
            "event_chance": 0,
            "item_chance": 0,
            "battle_event_weight": 0,
            "team_battle_event_weight": 0,
            "boss_event_weight": 0,
            "item_event_weight": 0,
            "item_damage_event_weight": 0,
            "item_steal_event_weight": 0,
            "alignment_event_weight": 0,
            "critical_strike_chance": 0,
            "critical_strike_chance_good": 0,
            "critical_strike_chance_evil": 0,
            "item_drop_chance": 0,
            "unique_item_chance": 0,
            "level_battle_chance_below_25": 0,
            "level_battle_chance_at_25": 0,
            "boss_min_players": 4,
            "boss_max_players": 7,
            "boss_min_level": 20,
            "boss_reward_percent": 15,
            "boss_loss_percent": 6,
            "boss_power_min_factor": 0.8,
            "boss_power_max_factor": 1.4,
        }
    })

    zero_keys = {
        "EVENT_CHANCE",
        "ITEM_CHANCE",
        "BATTLE_EVENT_WEIGHT",
        "TEAM_BATTLE_EVENT_WEIGHT",
        "BOSS_EVENT_WEIGHT",
        "ITEM_EVENT_WEIGHT",
        "ITEM_DAMAGE_EVENT_WEIGHT",
        "ITEM_STEAL_EVENT_WEIGHT",
        "ALIGNMENT_EVENT_WEIGHT",
        "CRITICAL_STRIKE_CHANCE",
        "CRITICAL_STRIKE_CHANCE_GOOD",
        "CRITICAL_STRIKE_CHANCE_EVIL",
        "ITEM_DROP_CHANCE",
        "UNIQUE_ITEM_CHANCE",
        "LEVEL_BATTLE_CHANCE_BELOW_25",
        "LEVEL_BATTLE_CHANCE_AT_25",
    }
    assert {key: values[key] for key in zero_keys} == {
        key: 0.0 for key in zero_keys
    }
    assert values["BOSS_MIN_PLAYERS"] == 4
    assert values["BOSS_MAX_PLAYERS"] == 7
    assert values["BOSS_MIN_LEVEL"] == 20
    assert values["BOSS_REWARD_PERCENT"] == 15
    assert values["BOSS_LOSS_PERCENT"] == 6
    assert values["BOSS_POWER_MIN_FACTOR"] == 0.8
    assert values["BOSS_POWER_MAX_FACTOR"] == 1.4


def test_idlerpg_runtime_values_include_export_interval_and_preserve_zero():
    assert runtime._idlerpg_values({})["EXPORT_INTERVAL_SECONDS"] == 300
    assert runtime._idlerpg_values({
        "idlerpg": {"export_interval_seconds": 0}
    })["EXPORT_INTERVAL_SECONDS"] == 0
    assert runtime._idlerpg_values({
        "idlerpg_export_interval_seconds": 900
    })["EXPORT_INTERVAL_SECONDS"] == 900


def test_idlerpg_runtime_values_include_full_season_event_export():
    assert runtime._idlerpg_values({})["EXPORT_FULL_SEASON_EVENTS"] is False
    assert runtime._idlerpg_values({
        "idlerpg": {"export_full_season_events": True}
    })["EXPORT_FULL_SEASON_EVENTS"] is True
    assert runtime._idlerpg_values({
        "idlerpg_export_full_season_events": True
    })["EXPORT_FULL_SEASON_EVENTS"] is True


def test_idlerpg_runtime_values_cover_all_reloadable_config_constants():
    from plugins.idlerpg import config as idlerpg_config

    non_runtime_names = {"ROOM_TASKS"}
    expected = {
        name
        for name in idlerpg_config.__all__
        if name.isupper() and name not in non_runtime_names
    }

    assert expected <= runtime._idlerpg_values({}).keys()


def test_runtime_refresh_updates_reminder_default_timezone(monkeypatch):
    from plugins import reminder

    monkeypatch.setattr(reminder, "REMINDER_DEFAULT_TIMEZONE", "UTC")

    refreshed = runtime.refresh_runtime_config_constants({
        "reminder_enabled": True,
        "reminder_default_timezone": "Europe/Berlin",
    })

    assert reminder.REMINDER_DEFAULT_TIMEZONE == "Europe/Berlin"
    assert str(reminder._reminder_default_tzinfo()) == "Europe/Berlin"
    assert any("plugins.reminder" in line for line in refreshed)


def test_rss_runtime_values_preserve_zero_limit_and_reload_all_command_settings(
    monkeypatch,
):
    from plugins import rss
    from plugins.rss import command_support as rss_command_support
    from plugins.rss import commands as rss_commands
    from plugins.rss import config as rss_config
    from plugins.rss import fetch as rss_fetch
    from plugins.rss import formatting as rss_formatting
    from plugins.rss import tasks as rss_tasks

    values = runtime._rss_values({
        "rss_trusted_max_feeds": 0,
        "rss_list_page_size": 25,
        "rss_max_entries_per_poll": 4,
        "rss_broken_error_threshold": 7,
        "rss_template_max_length": 1500,
        "rss_startup_stagger_seconds": 0,
    })

    assert values["RSS_TRUSTED_MAX_FEEDS"] == 0
    assert values["RSS_LIST_PAGE_SIZE"] == 25
    assert values["RSS_MAX_ENTRIES_PER_POLL"] == 4
    assert values["RSS_BROKEN_ERROR_THRESHOLD"] == 7
    assert values["RSS_TEMPLATE_MAX_LENGTH"] == 1500
    assert values["RSS_STARTUP_STAGGER_SECONDS"] == 0.0

    monkeypatch.setattr(rss, "RSS_TRUSTED_MAX_FEEDS", 10)
    monkeypatch.setattr(rss_commands, "RSS_TRUSTED_MAX_FEEDS", 10)
    monkeypatch.setattr(rss_command_support, "RSS_BROKEN_ERROR_THRESHOLD", 3)
    monkeypatch.setattr(rss_fetch, "SIMILARITY_THRESHOLD", 0.8)
    monkeypatch.setattr(rss_formatting, "RSS_LIST_PAGE_SIZE", 10)
    monkeypatch.setattr(rss_formatting, "RSS_TEMPLATE_MAX_LENGTH", 1000)
    monkeypatch.setattr(rss_tasks, "RSS_STARTUP_STAGGER_SECONDS", 2.0)

    refreshed = runtime.refresh_runtime_config_constants({
        "rss_trusted_max_feeds": 0,
        "rss_list_page_size": 25,
        "rss_broken_error_threshold": 7,
        "rss_similarity_threshold": 0.72,
        "rss_template_max_length": 1500,
        "rss_startup_stagger_seconds": 0,
    })

    assert rss.RSS_TRUSTED_MAX_FEEDS == 0
    assert rss_commands.RSS_TRUSTED_MAX_FEEDS == 0
    assert not hasattr(rss_commands, "RSS_BROKEN_ERROR_THRESHOLD")
    assert rss_command_support.RSS_BROKEN_ERROR_THRESHOLD == 7
    assert rss_fetch.SIMILARITY_THRESHOLD == 0.72
    assert not hasattr(rss_config, "SIMILARITY_THRESHOLD")
    assert rss_formatting.RSS_LIST_PAGE_SIZE == 25
    assert rss_formatting.RSS_TEMPLATE_MAX_LENGTH == 1500
    assert rss_tasks.RSS_STARTUP_STAGGER_SECONDS == 0.0
    assert any("plugins.rss.command_support" in line for line in refreshed)
    assert any("plugins.rss.commands" in line for line in refreshed)
    assert any("plugins.rss.formatting" in line for line in refreshed)


def test_runtime_refresh_updates_wikipedia_language(monkeypatch):
    from plugins import info

    monkeypatch.setattr(info, "WIKIPEDIA_LANGUAGE", "en")

    refreshed = runtime.refresh_runtime_config_constants({
        "wikipedia_language": "de",
    })

    assert info.WIKIPEDIA_LANGUAGE == "de"
    assert info._parse_wikipedia_args(["XMPP"]) == ("de", "XMPP")
    assert info._parse_wikipedia_args(["en", "XMPP"]) == ("en", "XMPP")
    assert any("plugins.info" in line for line in refreshed)


def test_runtime_refresh_updates_translate_defaults(monkeypatch):
    from plugins import translate

    monkeypatch.setattr(translate, "TRANSLATE_FROM", "auto")
    monkeypatch.setattr(translate, "TRANSLATE_TO", None)
    monkeypatch.setattr(translate, "TRANSLATE_PROVIDER_QUEUE_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(translate, "TRANSLATE_RATE_LIMIT_INITIAL_SECONDS", 60.0)
    monkeypatch.setattr(translate, "TRANSLATE_RATE_LIMIT_MAX_SECONDS", 900.0)
    monkeypatch.setattr(translate, "TRANSLATE_RATE_LIMIT_BACKOFF_MULTIPLIER", 2.0)

    refreshed = runtime.refresh_runtime_config_constants(
        {
            "translate_from": "en",
            "translate_to": "de",
            "translate_provider_queue_timeout_seconds": 3,
            "translate_rate_limit_initial_seconds": 45,
            "translate_rate_limit_max_seconds": 600,
            "translate_rate_limit_backoff_multiplier": 1.5,
        }
    )

    assert translate.TRANSLATE_FROM == "en"
    assert translate.TRANSLATE_TO == "de"
    assert translate.TRANSLATE_PROVIDER_QUEUE_TIMEOUT_SECONDS == 3
    assert translate.TRANSLATE_RATE_LIMIT_INITIAL_SECONDS == 45
    assert translate.TRANSLATE_RATE_LIMIT_MAX_SECONDS == 600
    assert translate.TRANSLATE_RATE_LIMIT_BACKOFF_MULTIPLIER == 1.5
    assert translate._parse_translation_args(["Hello"]) == (
        translate.TranslationRequest("en", "de", "Hello")
    )
    assert any("plugins.translate" in line for line in refreshed)


def test_runtime_refresh_updates_default_pagination(monkeypatch):
    from utils import formatting

    monkeypatch.setattr(formatting, "DEFAULT_PAGINATION", "all")

    refreshed = runtime.refresh_runtime_config_constants({"default_pagination": 20})

    assert formatting.DEFAULT_PAGINATION == 20
    assert formatting.parse_page_args([]) == formatting.PageRequest(page=1, all=False, page_size=20)
    assert any("utils.formatting" in line for line in refreshed)


def test_runtime_refresh_updates_xmpp_compliance_limit(monkeypatch):
    from plugins import xmpp

    monkeypatch.setattr(xmpp, "XMPP_COMPLIANCE_MAX_READ_BYTES", 262144)

    refreshed = runtime.refresh_runtime_config_constants({
        "xmpp_compliance_max_read_bytes": 131072,
    })

    assert xmpp.XMPP_COMPLIANCE_MAX_READ_BYTES == 131072
    assert any("plugins.xmpp" in line for line in refreshed)


def test_duck_runtime_values_refresh_all_global_defaults():
    values = runtime._duck_values({
        "ducks": {
            "min_messages": "40",
            "max_messages": "20",
            "spawn_chance": "7",
            "max_ducks_per_day": "0",
            "timeout": "300",
            "count_commands": "yes",
            "state_save_every": "5",
        }
    })

    assert values["DEFAULT_MIN_MESSAGES"] == 40
    assert values["DEFAULT_MAX_MESSAGES"] == 40
    assert values["DUCK_SPAWN_CHANCE"] == 7
    assert values["MAX_DUCKS_PER_DAY"] == 0
    assert values["DUCK_TIMEOUT"] == 300
    assert values["COUNT_COMMAND_MESSAGES"] is True
    assert values["DUCK_STATE_SAVE_EVERY"] == 5


def test_nested_schema_covers_reloadable_runtime_values():
    from utils.config.spec import DUCK_FIELDS, IDLERPG_FIELDS, USER_FIELDS

    idlerpg_expected = {
        runtime_key
        for field in IDLERPG_FIELDS.values()
        for runtime_key in field.runtime_keys
    }
    duck_expected = {
        runtime_key
        for field in DUCK_FIELDS.values()
        for runtime_key in field.runtime_keys
    }
    user_expected = {
        runtime_key
        for field in USER_FIELDS.values()
        for runtime_key in field.runtime_keys
    }

    assert idlerpg_expected == runtime._idlerpg_values({}).keys()
    assert duck_expected <= runtime._duck_values({}).keys()
    assert user_expected == {"MAX_ROOM_NICKS"}
