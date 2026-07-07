"""Split module for plugins/idlerpg.py: tasks."""

from __future__ import annotations
import asyncio
import random
from functools import partial
from utils.task_supervisor import create_plugin_task


async def _ensure_game_task(bot, room_jid: str) -> asyncio.Task | None:
    task = ROOM_TASKS.get(room_jid)
    if task and not task.done():
        return task
    if task and task.done():
        ROOM_TASKS.pop(room_jid, None)
    ROOM_TASKS[room_jid] = create_plugin_task(
        bot,
        PLUGIN_NAME,
        _game_loop(bot, room_jid),
        name=f"idlerpg-{room_jid}",
    )
    return ROOM_TASKS[room_jid]


async def _cancel_room_task(room_jid: str) -> None:
    task = ROOM_TASKS.pop(room_jid, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            log.debug("[IDLERPG] Room task for %s cancelled cleanly", room_jid)


async def _start_enabled_room_tasks(bot) -> None:
    for room_jid, enabled in (await _enabled_rooms(bot)).items():
        if enabled:
            await _ensure_game_task(bot, str(room_jid))


async def _sync_tasks_to_enabled_rooms(bot) -> None:
    enabled = {str(room) for room, value in (await _enabled_rooms(bot)).items() if value}
    for room_jid in sorted(enabled):
        await _ensure_game_task(bot, room_jid)
    for room_jid in list(ROOM_TASKS):
        if room_jid not in enabled:
            await _cancel_room_task(room_jid)


async def _game_loop(bot, room_jid: str) -> None:
    while True:
        try:
            await asyncio.sleep(max(1, TICK_SECONDS))
            await _tick_room(bot, room_jid, announce=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[IDLERPG] Game loop failed for %s", room_jid)
            await asyncio.sleep(max(5, TICK_SECONDS))


async def _tick_room(bot, room_jid: str, *, announce: bool = False) -> None:
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    now = _now()
    last_tick = int(room.get("last_tick", now) or now)
    delta = max(0, min(now - last_tick, 24 * 3600))
    room["last_tick"] = now
    if delta <= 0:
        await _set_data(bot, data)
        return

    players = room.get("players", {})
    if not isinstance(players, dict):
        room["players"] = {}
        await _set_data(bot, data)
        return

    online_jids = _online_jids(room_jid)
    messages: list[str] = []
    _maybe_rollover_season(room_jid, room, messages)
    movement_steps = max(1, delta // max(1, TICK_SECONDS))
    for jid, raw_player in list(players.items()):
        if not isinstance(raw_player, dict):
            players.pop(jid, None)
            continue
        player = _normalize_player(str(jid), raw_player)
        if player.get("logged_out"):
            _maybe_apply_pending_logout_penalty(player, messages)
            continue
        if str(jid) not in online_jids:
            continue
        player["next"] = max(0, int(player.get("next", 0)) - delta)
        player["idled"] = int(player.get("idled", 0)) + delta
        player["last_seen"] = now
        _check_level_achievements(player, room)
        _move_player(player, movement_steps)
        leveled = False
        while int(player.get("next", 0)) <= 0:
            player["level"] = int(player.get("level", 0)) + 1
            player["next"] = int(player.get("next", 0)) + _ttl_for_level(player["level"])
            leveled = True
        if leveled:
            _check_level_achievements(player, room)
            messages.append(
                f"🏆 {_display_character(player)} has reached level {player['level']}! "
                f"Next level in {_duration_clock(player['next'])}."
            )
            if int(player.get("level", 0) or 0) >= LEVEL_REWARD_MIN_LEVEL and _award(player, "level_reward_50"):
                messages.append(f"🎖️ {_display_player(player)} has unlocked the level {LEVEL_REWARD_MIN_LEVEL} reward badge.")
            if int(player.get("level", 0) or 0) >= 75 and _award(player, "level_reward_75"):
                messages.append(f"🏷️ {_display_player(player)} has unlocked the rare title pool at level 75.")
            if random.random() < ITEM_CHANCE:
                messages.append(_grant_level_item(player))
    _maybe_periodic_announcements(bot, room_jid, room, messages)
    await _maybe_run_random_event(room, room_jid, messages)
    await _maybe_run_quest(room, room_jid, messages)
    for text in messages:
        _record_event(room, "game", text)
    await _set_data(bot, data)
    if announce:
        for text in messages[:8]:
            _system_reply(bot, room_jid, text)


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int]:
    data = await _get_data(bot)
    rooms = data.get("rooms", {}) if isinstance(data, dict) else {}
    if not isinstance(rooms, dict):
        rooms = {}
    selected = {room_jid: rooms.get(room_jid, {})} if room_jid else rooms
    players = 0
    online = 0
    active_quests = 0
    for room, bucket in selected.items():
        if not isinstance(bucket, dict):
            continue
        room_players = bucket.get("players", {})
        if not isinstance(room_players, dict):
            continue
        players += len(room_players)
        online += sum(
            1
            for jid, player in room_players.items()
            if isinstance(player, dict) and _is_player_online(str(room), str(jid), player)
        )
        quest = bucket.get("quest", {})
        if isinstance(quest, dict) and quest.get("active"):
            active_quests += 1
    return {
        "rooms": len(selected),
        "players": players,
        "online_players": online,
        "active_quests": active_quests,
        "tasks": len([task for task in ROOM_TASKS.values() if not task.done()]),
    }


async def cleanup_room_state(bot, room_jid: str):
    await _cancel_room_task(room_jid)
    data = await _get_data(bot)
    rooms = data.get("rooms") if isinstance(data, dict) else None
    if isinstance(rooms, dict):
        rooms.pop(room_jid, None)
        await _set_data(bot, data)


async def restart_tasks(bot):
    for room_jid in list(ROOM_TASKS):
        await _cancel_room_task(room_jid)
    await _start_enabled_room_tasks(bot)


async def on_ready(bot):
    await _start_enabled_room_tasks(bot)


async def on_load(bot):
    log.info("[IDLERPG] Plugin loading...")
    bot.bot_plugins.register_event(
        PLUGIN_NAME,
        "groupchat_message",
        partial(on_message, bot),
    )
    bot.bot_plugins.register_event(
        PLUGIN_NAME,
        "groupchat_presence",
        partial(on_muc_presence, bot),
    )
    log.info("[IDLERPG] Plugin loaded")


async def on_unload(bot):
    for room_jid in list(ROOM_TASKS):
        await _cancel_room_task(room_jid)
    log.info("[IDLERPG] Plugin unloaded")
