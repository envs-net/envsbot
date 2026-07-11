from types import SimpleNamespace

import utils.config.runtime as runtime


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


def test_runtime_refresh_updates_default_pagination(monkeypatch):
    from utils import formatting

    monkeypatch.setattr(formatting, "DEFAULT_PAGINATION", "all")

    refreshed = runtime.refresh_runtime_config_constants({"default_pagination": 20})

    assert formatting.DEFAULT_PAGINATION == 20
    assert formatting.parse_page_args([]) == formatting.PageRequest(page=1, all=False, page_size=20)
    assert any("utils.formatting" in line for line in refreshed)
