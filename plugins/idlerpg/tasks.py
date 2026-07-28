"""Split module for plugins/idlerpg.py: tasks."""

from __future__ import annotations
import asyncio
import random
from functools import partial
from utils.task_supervisor import create_plugin_task
from .handlers import on_message, on_muc_presence
from .state import _checkpoint_room_clock, _flush_idlerpg_store


_ROOM_TASK_LOCKS: dict[str, asyncio.Lock] = {}
_ROOM_TICK_LOCKS: dict[str, asyncio.Lock] = {}


def _room_lock(locks: dict[str, asyncio.Lock], room_jid: str) -> asyncio.Lock:
    room_key = str(room_jid)
    lock = locks.get(room_key)
    if lock is None:
        lock = asyncio.Lock()
        locks[room_key] = lock
    return lock


def _clear_room_locks(room_jid: str) -> None:
    room_key = str(room_jid)
    _ROOM_TASK_LOCKS.pop(room_key, None)
    _ROOM_TICK_LOCKS.pop(room_key, None)


def _maybe_run_level_battle(
    player: dict,
    online_players: list[tuple[str, dict]],
    messages: list[str],
    room: dict | None = None,
) -> bool:
    opponents = [candidate for _jid, candidate in online_players if candidate is not player]
    if not opponents:
        return False
    level = max(0, int(player.get("level", 0) or 0))
    chance = _dep_config.LEVEL_BATTLE_CHANCE_AT_25 if level >= 25 else _dep_config.LEVEL_BATTLE_CHANCE_BELOW_25
    if random.random() >= max(0.0, float(chance)):
        return False
    defender = random.choice(opponents)
    _dep_events._run_duel_between(player, defender, messages, room)
    return True


def _room_jid_from_task_name(name: str) -> str | None:
    """Return the IdleRPG room JID represented by a supervised task name.

    Older builds used ``idlerpg-<room>`` while newer builds use the plain
    room JID.  Topic-update tasks intentionally use ``idlerpg-topic-<room>``
    and are not room game-loop workers.
    """
    if name.startswith("idlerpg-topic-"):
        return None
    if name.startswith("idlerpg-"):
        legacy_name = name.removeprefix("idlerpg-")
        return legacy_name if "@" in legacy_name else None
    if "@" in name:
        return name
    return None


async def _cancel_duplicate_supervised_room_tasks(
    bot,
    room_jid: str,
    *,
    keep: asyncio.Task | None = None,
) -> int:
    """Cancel supervised duplicate game-loop tasks for one room.

    During upgrades or plugin reloads, a previously supervised room task can
    remain tracked even though the split package's ``ROOM_TASKS`` mapping no
    longer owns it.  Without this reconciliation, the task status command can
    show two running IdleRPG loops for one room.
    """
    supervisor = getattr(bot, "tasks", None)
    task_meta = getattr(supervisor, "_tasks", None)
    cancel_task = getattr(supervisor, "cancel_task", None)
    if not isinstance(task_meta, dict) or not callable(cancel_task):
        return 0

    cancelled = 0
    for task, meta in tuple(task_meta.items()):
        if task is keep or task.done():
            continue
        if not isinstance(meta, dict) or meta.get("plugin") != _dep_constants.PLUGIN_NAME:
            continue
        task_room = _room_jid_from_task_name(str(meta.get("name") or ""))
        if task_room != room_jid:
            continue
        await cancel_task(task)
        cancelled += 1
    return cancelled


async def _ensure_game_task(bot, room_jid: str) -> asyncio.Task | None:
    room_jid = str(room_jid)
    async with _room_lock(_ROOM_TASK_LOCKS, room_jid):
        return await _ensure_game_task_locked(bot, room_jid)


async def _ensure_game_task_locked(bot, room_jid: str) -> asyncio.Task | None:
    room_jid = str(room_jid)
    task = _dep_config.ROOM_TASKS.get(room_jid)
    if task and not task.done():
        await _cancel_duplicate_supervised_room_tasks(bot, room_jid, keep=task)
        return task
    if task and task.done():
        _dep_config.ROOM_TASKS.pop(room_jid, None)

    await _cancel_duplicate_supervised_room_tasks(bot, room_jid)
    await _checkpoint_room_clock(bot, room_jid, flush=True)
    _dep_config.ROOM_TASKS[room_jid] = create_plugin_task(
        bot,
        _dep_constants.PLUGIN_NAME,
        _game_loop(bot, room_jid),
        name=room_jid,
    )
    await _cancel_duplicate_supervised_room_tasks(
        bot, room_jid, keep=_dep_config.ROOM_TASKS[room_jid]
    )
    return _dep_config.ROOM_TASKS[room_jid]


async def _cancel_room_task(room_jid: str) -> None:
    task = _dep_config.ROOM_TASKS.pop(room_jid, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            _dep_config.log.debug("[IDLERPG] Room task for %s cancelled cleanly", room_jid)
    _clear_room_locks(room_jid)


async def _start_enabled_room_tasks(bot) -> None:
    for room_jid, enabled in (await _dep_state._enabled_rooms(bot)).items():
        if enabled:
            await _ensure_game_task(bot, str(room_jid))


async def _sync_tasks_to_enabled_rooms(bot) -> None:
    enabled = {str(room) for room, value in (await _dep_state._enabled_rooms(bot)).items() if value}
    for room_jid in sorted(enabled):
        await _ensure_game_task(bot, room_jid)
    for room_jid in list(_dep_config.ROOM_TASKS):
        if room_jid not in enabled:
            await _cancel_room_task(room_jid)


async def _game_loop(bot, room_jid: str) -> None:
    while True:
        try:
            await asyncio.sleep(max(1, _dep_config.TICK_SECONDS))
            await _tick_room(bot, room_jid, announce=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            _dep_config.log.exception("[IDLERPG] Game loop failed for %s", room_jid)
            await asyncio.sleep(max(5, _dep_config.TICK_SECONDS))


async def _tick_room(bot, room_jid: str, *, announce: bool = False) -> None:
    room_jid = str(room_jid)
    async with _room_lock(_ROOM_TICK_LOCKS, room_jid):
        await _tick_room_locked(bot, room_jid, announce=announce)


async def _tick_room_locked(bot, room_jid: str, *, announce: bool = False) -> None:
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    now = _dep_formatting._now()
    last_tick = int(room.get("last_tick", now) or now)
    delta = max(0, min(now - last_tick, 24 * 3600))
    room["last_tick"] = now
    if delta <= 0:
        await _dep_state._set_data(bot, data)
        return

    players = room.get("players", {})
    if not isinstance(players, dict):
        room["players"] = {}
        await _dep_state._set_data(bot, data)
        return

    online_jids = _dep_state._online_jids(room_jid)
    messages: list[str] = []
    _dep_seasons._maybe_rollover_season(room_jid, room, messages)
    online_players: list[tuple[str, dict]] = []
    pending_level_battles: list[dict] = []
    active_quest = room.get("quest") if isinstance(room.get("quest"), dict) else None
    achievement_snapshots = {
        str(jid): _dep_leveling._achievement_keys(player)
        for jid, player in players.items()
        if isinstance(player, dict)
    }
    for jid, raw_player in list(players.items()):
        if not isinstance(raw_player, dict):
            players.pop(jid, None)
            continue
        player = _dep_state._normalize_player(str(jid), raw_player)
        if player.get("logged_out"):
            _dep_leveling._maybe_apply_pending_logout_penalty(
                player,
                messages,
                room,
                room_jid=room_jid,
                jid=str(jid),
            )
            continue
        if str(jid) not in online_jids:
            continue
        player["next"] = max(0, int(player.get("next", 0)) - delta)
        player["idled"] = int(player.get("idled", 0)) + delta
        player["last_seen"] = now
        _dep_leveling._check_level_achievements(player, room)
        _dep_map._move_player(player, delta, quest=active_quest, jid=str(jid))
        online_players.append((str(jid), player))
        leveled = False
        while int(player.get("next", 0)) <= 0:
            player["level"] = int(player.get("level", 0)) + 1
            player["next"] = int(player.get("next", 0)) + _dep_leveling._ttl_for_level(player["level"])
            leveled = True
        if leveled:
            _dep_leveling._check_level_achievements(player, room)
            messages.append(
                f"🏆 {_dep_formatting._display_character(player)} has reached level {player['level']}! "
                f"Next level in {_dep_formatting._duration_clock(player['next'])}."
            )
            if random.random() < _dep_config.ITEM_CHANCE:
                messages.append(_dep_items._grant_level_item(player, room))
            pending_level_battles.append(player)
    for player in pending_level_battles:
        _maybe_run_level_battle(player, online_players, messages, room)
    _dep_events._maybe_run_grid_battle(online_players, messages, room)
    _dep_formatting._maybe_periodic_announcements(bot, room_jid, room, messages)
    await _dep_events._maybe_run_random_event(room, room_jid, messages)
    await _dep_quests._maybe_run_quest(room, room_jid, messages)
    achievement_messages: list[str] = []
    for jid, player in players.items():
        if isinstance(player, dict):
            achievement_messages.extend(
                _dep_leveling._achievement_announcements(player, achievement_snapshots.get(str(jid), set()))
            )
    messages.extend(achievement_messages)
    for text in messages:
        _dep_export._record_event(room, "game", text)
    await _dep_state._set_data(bot, data)
    if announce:
        announced: list[str] = []
        for text in messages[:8]:
            _dep_formatting._system_reply(bot, room_jid, text)
            announced.append(text)
        for text in achievement_messages:
            if text not in announced:
                _dep_formatting._system_reply(bot, room_jid, text)
                announced.append(text)


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int]:
    data = await _dep_state._get_data(bot)
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
            if isinstance(player, dict) and _dep_state._is_player_online(str(room), str(jid), player)
        )
        quest = bucket.get("quest", {})
        if isinstance(quest, dict) and quest.get("active"):
            active_quests += 1
    return {
        "rooms": len(selected),
        "players": players,
        "online_players": online,
        "active_quests": active_quests,
        "tasks": len([task for task in _dep_config.ROOM_TASKS.values() if not task.done()]),
    }


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return IdleRPG room/task diagnostics."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    tasks = int(state.get("tasks", 0) or 0)
    players = int(state.get("players", 0) or 0)
    online = int(state.get("online_players", 0) or 0)
    rooms = int(state.get("rooms", 0) or 0)
    quests = int(state.get("active_quests", 0) or 0)
    ok = tasks > 0 or rooms == 0
    icon = "✅" if ok else "⚠️"
    return [
        f"{icon} IdleRPG{scope}: rooms={rooms}, players={players}, online={online}, active_quests={quests}, tasks={tasks}"
    ]

async def cleanup_room_state(bot, room_jid: str):
    await _cancel_room_task(room_jid)
    data = await _dep_state._get_data(bot)
    rooms = data.get("rooms") if isinstance(data, dict) else None
    if isinstance(rooms, dict):
        rooms.pop(room_jid, None)
        await _dep_state._set_data(bot, data, force_export=True)


async def restart_tasks(bot):
    for room_jid in list(_dep_config.ROOM_TASKS):
        await _cancel_room_task(room_jid)
    await _start_enabled_room_tasks(bot)
    await _dep_state._refresh_public_export(bot)


async def on_ready(bot):
    await _start_enabled_room_tasks(bot)
    await _dep_state._refresh_public_export(bot)


async def on_load(bot):
    _dep_config.log.info("[IDLERPG] Plugin loading...")
    message_handler = partial(on_message, bot)
    bot.bot_plugins.register_event(
        _dep_constants.PLUGIN_NAME,
        "groupchat_message",
        message_handler,
    )
    bot.bot_plugins.register_event(
        _dep_constants.PLUGIN_NAME,
        "message",
        message_handler,
    )
    register_runtime_event = getattr(bot.bot_plugins, "register_runtime_event", None)
    if callable(register_runtime_event):
        register_runtime_event(
            _dep_constants.PLUGIN_NAME,
            "public_groupchat_message",
            message_handler,
        )
    bot.bot_plugins.register_event(
        _dep_constants.PLUGIN_NAME,
        "groupchat_presence",
        partial(on_muc_presence, bot),
    )
    _dep_config.log.info("[IDLERPG] Plugin loaded")


async def on_unload(bot):
    active_rooms = list(_dep_config.ROOM_TASKS)
    for room_jid in active_rooms:
        await _checkpoint_room_clock(bot, room_jid)
        await _cancel_room_task(room_jid)
    if active_rooms:
        await _flush_idlerpg_store(bot)
    _dep_config.log.info("[IDLERPG] Plugin unloaded")

# Explicit module dependencies; module-qualified access keeps cyclic domain
# relationships visible without copying names into sibling namespaces.
from . import config as _dep_config  # noqa: E402
from . import constants as _dep_constants  # noqa: E402
from . import events as _dep_events  # noqa: E402
from . import export as _dep_export  # noqa: E402
from . import formatting as _dep_formatting  # noqa: E402
from . import items as _dep_items  # noqa: E402
from . import leveling as _dep_leveling  # noqa: E402
from . import map as _dep_map  # noqa: E402
from . import quests as _dep_quests  # noqa: E402
from . import seasons as _dep_seasons  # noqa: E402
from . import state as _dep_state  # noqa: E402
