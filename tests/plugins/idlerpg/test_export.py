from .helpers import (
    DummyBot,
    DummyTask,
    idlerpg,
    pytest,
)


@pytest.mark.asyncio
async def test_cleanup_room_state_removes_data_and_task():
    bot = DummyBot()
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {"rooms": {"room@conf": idlerpg._blank_room()}}
    idlerpg.ROOM_TASKS["room@conf"] = DummyTask()

    await idlerpg.cleanup_room_state(bot, "room@conf")

    assert "room@conf" not in bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]
    assert "room@conf" not in idlerpg.ROOM_TASKS


def test_public_rules_include_new_options():
    rules = idlerpg._public_rules()
    assert rules["announce_login"] is True
    assert rules["topic_custom_text"] == idlerpg.TOPIC_CUSTOM_TEXT
    assert "item_damage_event_weight" in rules
    assert "item_steal_event_weight" in rules
    assert rules["manual_duel_max_distance"] == idlerpg.MANUAL_DUEL_MAX_DISTANCE
    assert rules["manual_duel_cooldown_seconds"] == idlerpg.MANUAL_DUEL_COOLDOWN_SECONDS
    assert "season_achievement_gates_enabled" in rules
