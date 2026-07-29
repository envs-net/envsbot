from types import SimpleNamespace

import utils.config.runtime as runtime


def test_message_cache_age_is_startup_only():
    assert "message_cache_size" in runtime.STARTUP_ONLY_KEYS
    assert "message_cache_max_age_days" in runtime.STARTUP_ONLY_KEYS

    lines = runtime.startup_change_lines(
        {"message_cache_max_age_days": 30},
        {"message_cache_max_age_days": 14},
    )

    assert any("MESSAGE_CACHE_MAX_AGE_DAYS" in line for line in lines)


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


def test_idlerpg_runtime_values_use_balanced_grid_quest_step_default():
    values = runtime._idlerpg_values({"idlerpg": {}})

    assert values["QUEST_GRID_STEP_SECONDS"] == 30


def test_idlerpg_runtime_values_include_original_grid_options():
    values = runtime._idlerpg_values({
        "idlerpg": {
            "map_step_per_second": "2",
            "grid_battle_enabled": False,
            "quest_grid_step_seconds": "5",
        }
    })

    assert values["MAP_STEP_PER_SECOND"] == 2
    assert values["MAP_STEP_PER_TICK"] == 2
    assert values["GRID_BATTLE_ENABLED"] is False
    assert values["QUEST_GRID_STEP_SECONDS"] == 5


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
    from plugins.rss import commands as rss_commands
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
    monkeypatch.setattr(rss_commands, "RSS_BROKEN_ERROR_THRESHOLD", 3)
    monkeypatch.setattr(rss_formatting, "RSS_LIST_PAGE_SIZE", 10)
    monkeypatch.setattr(rss_formatting, "RSS_TEMPLATE_MAX_LENGTH", 1000)
    monkeypatch.setattr(rss_tasks, "RSS_STARTUP_STAGGER_SECONDS", 2.0)

    refreshed = runtime.refresh_runtime_config_constants({
        "rss_trusted_max_feeds": 0,
        "rss_list_page_size": 25,
        "rss_broken_error_threshold": 7,
        "rss_template_max_length": 1500,
        "rss_startup_stagger_seconds": 0,
    })

    assert rss.RSS_TRUSTED_MAX_FEEDS == 0
    assert rss_commands.RSS_TRUSTED_MAX_FEEDS == 0
    assert rss_commands.RSS_BROKEN_ERROR_THRESHOLD == 7
    assert rss_formatting.RSS_LIST_PAGE_SIZE == 25
    assert rss_formatting.RSS_TEMPLATE_MAX_LENGTH == 1500
    assert rss_tasks.RSS_STARTUP_STAGGER_SECONDS == 0.0
    assert any("plugins.rss.commands" in line for line in refreshed)
    assert any("plugins.rss.formatting" in line for line in refreshed)


def test_runtime_refresh_updates_translate_defaults(monkeypatch):
    from plugins import translate

    monkeypatch.setattr(translate, "TRANSLATE_FROM", "auto")
    monkeypatch.setattr(translate, "TRANSLATE_TO", None)

    refreshed = runtime.refresh_runtime_config_constants(
        {
            "translate_from": "en",
            "translate_to": "de",
        }
    )

    assert translate.TRANSLATE_FROM == "en"
    assert translate.TRANSLATE_TO == "de"
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
