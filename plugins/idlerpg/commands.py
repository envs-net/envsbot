"""Split module for plugins/idlerpg.py: commands."""

from __future__ import annotations

import random
import time
from typing import Any

from core_plugins import _core
from utils.audit import audit_event
from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand, room_toggle_subcommands
from utils.formatting import format_page, parse_page_args

from .handlers import _message_actor_nick, _remember_player_nick

_PLAYER_HELP_SECTION = "Player commands"
_ADMIN_HELP_SECTION = "Room owner/admin commands"


def _player_help_subcommand(*args, **kwargs):
    """Return one IdleRPG player-command help entry."""
    return help_subcommand(*args, section=_PLAYER_HELP_SECTION, **kwargs)


def _admin_help_subcommand(*args, **kwargs):
    """Return one IdleRPG room-admin help entry."""
    return help_subcommand(*args, section=_ADMIN_HELP_SECTION, **kwargs)


async def _handle_register(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Register from the game room or a MUC private message.")
        return
    if not await _core._is_enabled_for_room(bot, _dep_constants.IDLERPG_ENABLED_KEY, _dep_constants.PLUGIN_NAME, room_jid):
        _dep_formatting._reply(bot, msg, "ℹ️ IdleRPG is not enabled in this room.")
        return
    if len(args) < 3:
        _dep_formatting._reply(bot, msg, f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg register <character> <class>")
        return
    name = _dep_formatting._safe_name(args[1])
    char_class = _dep_formatting._safe_class(" ".join(args[2:]))
    if not name:
        _dep_formatting._reply(bot, msg, "❌ Character names may only contain letters, numbers, dot, underscore and dash.")
        return
    if not char_class:
        _dep_formatting._reply(bot, msg, "❌ Character class may not be empty.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    players = room.setdefault("players", {})
    index = _dep_state._rebuild_name_index(room)
    if sender_jid in players:
        _dep_formatting._reply(bot, msg, "ℹ️ You already have an IdleRPG character in this room.")
        return
    if name.lower() in index:
        _dep_formatting._reply(bot, msg, f"❌ Character name {name} is already taken.")
        return
    now = _dep_formatting._now()
    player = _dep_state._normalize_player(sender_jid, {
        "jid": sender_jid,
        "name": name,
        "class": char_class,
        "level": 0,
        "next": _dep_leveling._ttl_for_level(0),
        "idled": 0,
        "created_at": now,
        "last_login": now,
        "last_seen": now,
        "alignment": "n",
        "items": {item: 0 for item in _dep_constants.ITEMS},
        "unique_items": {},
        "penalties": {},
        "achievements": ["founder"],
        "title": "",
        "last_nick": _message_actor_nick(msg),
        "x": random.randint(0, _dep_config.MAP_X),
        "y": random.randint(0, _dep_config.MAP_Y),
        "logged_out": False,
    })
    players[sender_jid] = player
    _dep_state._rebuild_name_index(room)
    _dep_export._record_event(room, "register", f"Welcome {name}, the {char_class}!", players=[name])
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    await _dep_tasks._ensure_game_task(bot, room_jid)
    await audit_event(bot, "idlerpg_register", actor=sender_jid, target=room_jid, details={"name": name})
    _dep_formatting._reply(
        bot,
        msg,
        f"🎲 Welcome {name}, the {char_class}! Next level in {_dep_formatting._duration(player['next'])}. "
        "The point of the game is to idle: normal room messages add time to your timer.",
    )


async def _handle_login(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Login from the game room or a MUC private message.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    _jid, player = _dep_state._find_player(room, sender_jid)
    if not player:
        _dep_formatting._reply(bot, msg, "❌ You do not have an IdleRPG character here yet.")
        return
    player = _dep_state._normalize_player(sender_jid, player)
    _remember_player_nick(player, msg)
    pending = player.get("pending_logout_penalty") if isinstance(player.get("pending_logout_penalty"), dict) else {}
    if not pending and _dep_state._is_player_online(room_jid, str(_jid or sender_jid), player):
        await _dep_state._set_data(bot, data, room_jid=room_jid)
        _dep_formatting._reply(
            bot,
            msg,
            f"ℹ️ {_dep_formatting._display_player(player)} is already online for IdleRPG. "
            + _dep_formatting._next_level_line(player),
        )
        return
    reply_suffix = ""
    if pending:
        due_at = int(pending.get("due_at", 0) or 0)
        if due_at > _dep_formatting._now():
            player["pending_logout_penalty"] = {}
            reply_suffix = " Logout grace used; no logout penalty was applied."
        else:
            changed = _dep_leveling._apply_logout_penalty(player, room)
            quest_messages: list[str] = []
            if changed:
                _dep_quests._maybe_fail_time_quest_for_penalty(
                    room,
                    room_jid,
                    sender_jid,
                    _dep_formatting._now(),
                    quest_messages,
                    reason="logout",
                )
                for text in quest_messages:
                    _dep_export._record_event(room, "quest", text)
            reply_suffix = f" Logout penalty applied: {_dep_formatting._duration_clock(changed)}. " + _dep_formatting._next_level_line(player)
            for text in quest_messages:
                _dep_formatting._system_reply(bot, room_jid, text)
    player["logged_out"] = False
    player["last_login"] = _dep_formatting._now()
    player["last_seen"] = _dep_formatting._now()
    login_text = (
        f"👤 {_dep_formatting._display_character(player)}, the level {player.get('level', 0)} {player.get('class', 'idler')}, "
        f"is now online from nickname {getattr(msg['from'], 'resource', None) or _dep_formatting._display_player(player)}. "
        f"Next level in {_dep_formatting._duration_clock(player.get('next', 0))}."
    )
    _dep_export._record_event(room, "login", login_text, players=[_dep_formatting._display_player(player)])
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    await _dep_tasks._ensure_game_task(bot, room_jid)
    if _dep_config.ANNOUNCE_LOGIN:
        _dep_formatting._system_reply(bot, room_jid, login_text)
    _dep_formatting._reply(bot, msg, f"✅ {_dep_formatting._display_player(player)} is now online for IdleRPG." + reply_suffix)


async def _handle_logout(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Logout from the game room or a MUC private message.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    _jid, player = _dep_state._find_player(room, sender_jid)
    if not player:
        _dep_formatting._reply(bot, msg, "❌ You do not have an IdleRPG character here yet.")
        return
    player = _dep_state._normalize_player(sender_jid, player)
    player["logged_out"] = True
    player["logged_out_at"] = _dep_formatting._now()
    name = _dep_formatting._display_player(player)
    if _dep_config.LOGOUT_GRACE_SECONDS > 0:
        player["pending_logout_penalty"] = {
            "created_at": _dep_formatting._now(),
            "due_at": _dep_formatting._now() + _dep_config.LOGOUT_GRACE_SECONDS,
        }
        _dep_export._record_event(
            room,
            "logout",
            f"{name} logged out. Logout penalty is pending for {_dep_formatting._duration_clock(_dep_config.LOGOUT_GRACE_SECONDS)}.",
            players=[name],
        )
        await _dep_state._set_data(bot, data, room_jid=room_jid)
        _dep_formatting._reply(
            bot,
            msg,
            f"👋 {name} logged out. Reconnect within {_dep_formatting._duration_clock(_dep_config.LOGOUT_GRACE_SECONDS)} "
            "to avoid the logout penalty.",
        )
        return
    changed = _dep_leveling._apply_logout_penalty(player, room)
    _dep_export._record_event(room, "logout", f"{name} logged out. {_dep_formatting._duration_clock(changed)} was added to their clock.", players=[name])
    quest_messages: list[str] = []
    if changed:
        _dep_quests._maybe_fail_time_quest_for_penalty(
            room,
            room_jid,
            sender_jid,
            _dep_formatting._now(),
            quest_messages,
            reason="logout",
        )
        for text in quest_messages:
            _dep_export._record_event(room, "quest", text)
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    _dep_formatting._reply(
        bot,
        msg,
        f"👋 {name} logged out. {_dep_formatting._duration_clock(changed)} is added to "
        f"{_dep_formatting._possessive(name)} clock. "
        + _dep_formatting._next_level_line(player),
    )
    for text in quest_messages:
        _dep_formatting._system_reply(bot, room_jid, text)


async def _handle_status(bot, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Status is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    target = args[1] if len(args) > 1 else None
    if not target:
        sender_jid, _, _ = await _core.get_real_jid(bot, msg)
        target = sender_jid
    jid, player = _dep_state._find_player(room, target)
    if not player:
        _dep_formatting._reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return
    _dep_formatting._reply(bot, msg, _dep_state._format_player_status(room_jid, str(jid), _dep_state._normalize_player(str(jid), player)))


async def _handle_top(bot, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Top is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    players = [
        (str(jid), _dep_state._normalize_player(str(jid), player))
        for jid, player in room.get("players", {}).items()
        if isinstance(player, dict)
    ]
    players.sort(key=lambda item: (-int(item[1].get("level", 0)), int(item[1].get("next", 0)), item[1].get("name", "")))
    lines = []
    for idx, (jid, p) in enumerate(players, start=1):
        presence = _dep_formatting._player_presence_label(room_jid, jid, p)
        lines.append(
            f"{idx}. {presence} · {p['name']}, level {p['level']} {p['class']} — TTL {_dep_formatting._duration(p['next'])}"
        )
    page_request = parse_page_args(args[1:])
    out = format_page(
        "🏆 IdleRPG Top Players",
        lines,
        page_request=page_request,
        page_size=_dep_config.PAGE_SIZE,
        command_hint=f"{_dep_formatting._command_prefix(bot)}idlerpg top",
    )
    _dep_formatting._reply(bot, msg, "\n".join(out))


async def _handle_players(bot, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Players is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    entries = []
    for jid, player in room.get("players", {}).items():
        if not isinstance(player, dict):
            continue
        player = _dep_state._normalize_player(str(jid), player)
        mark = "🟢" if _dep_state._is_player_online(room_jid, str(jid), player) else "⚫"
        entries.append(f"{mark} {player['name']} — level {player['level']} {player['class']}")
    entries.sort(key=str.lower)
    page_request = parse_page_args(args[1:])
    out = format_page(
        "🎲 IdleRPG Players",
        entries,
        page_request=page_request,
        page_size=_dep_config.PAGE_SIZE,
        command_hint=f"{_dep_formatting._command_prefix(bot)}idlerpg players",
    )
    _dep_formatting._reply(bot, msg, "\n".join(out))


async def _handle_items(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Items are room-scoped. Use this from a game room or MUC PM.")
        return
    target = args[1] if len(args) > 1 else sender_jid
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    jid, player = _dep_state._find_player(room, target)
    if not player:
        _dep_formatting._reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return
    player = _dep_state._normalize_player(str(jid), player)
    unique_items = player.get("unique_items", {}) if isinstance(player.get("unique_items"), dict) else {}
    lines = []
    bonus_map = {item["name"]: item for item in _dep_items._unique_bonuses(player)}
    for name, level in sorted(player["items"].items()):
        unique = unique_items.get(name)
        bonus = bonus_map.get(unique or "")
        suffix = ""
        if unique:
            suffix = f" — {unique}"
            if bonus:
                suffix += f" [tier {int(bonus.get('tier', 1) or 1)}]"
                suffix += f" ({bonus['bonus_percent']}% {str(bonus['bonus']).replace('_', ' ')})"
                if bonus.get("next_upgrade_level"):
                    suffix += f"; next tier from level {int(bonus['next_upgrade_level'])}"
        lines.append(f"{name}: {level}{suffix}")
    _dep_formatting._reply(bot, msg, f"🎒 Items for {player['name']}\n" + "\n".join(lines))


def _clean_duel_target(value: str) -> str:
    # XMPP clients often render mentions as @nick or @~nick.  Character names
    # cannot contain spaces, so keep the first token and strip mention markers.
    token = str(value or "").strip().split(maxsplit=1)[0] if str(value or "").strip() else ""
    return token.strip("@~:,.!?")


def _manual_duel_cooldown_remaining(player: dict[str, Any], now: int) -> int:
    cooldown = max(0, int(_dep_config.MANUAL_DUEL_COOLDOWN_SECONDS or 0))
    if cooldown <= 0:
        return 0
    try:
        last = int(player.get("last_manual_duel_at", 0) or 0)
    except (TypeError, ValueError):
        last = 0
    return max(0, cooldown - max(0, now - last))


async def _handle_duel(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Duels are room-scoped. Use them from a game room or MUC PM.")
        return
    if len(args) < 2:
        _dep_formatting._reply(bot, msg, f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg duel <character>")
        return

    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    attacker_jid, attacker = _dep_state._find_player(room, sender_jid)
    if not attacker or not attacker_jid:
        _dep_formatting._reply(bot, msg, "❌ You do not have an IdleRPG character here yet.")
        return
    target_name = _clean_duel_target(args[1])
    defender_jid, defender = _dep_state._find_player(room, target_name)
    if not defender or not defender_jid:
        _dep_formatting._reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return
    if str(defender_jid) == str(attacker_jid):
        _dep_formatting._reply(bot, msg, "❌ You cannot duel yourself.")
        return

    attacker = _dep_state._normalize_player(str(attacker_jid), attacker)
    defender = _dep_state._normalize_player(str(defender_jid), defender)
    if not _dep_state._is_player_online(room_jid, str(attacker_jid), attacker):
        _dep_formatting._reply(bot, msg, "ℹ️ You need to be online in the game room to duel.")
        return
    if not _dep_state._is_player_online(room_jid, str(defender_jid), defender):
        _dep_formatting._reply(bot, msg, f"ℹ️ {_dep_formatting._display_player(defender)} is not online in the game room.")
        return

    if _dep_events._quest_companions_share_position(
        room,
        str(attacker_jid),
        str(defender_jid),
        attacker,
        defender,
    ):
        _dep_formatting._reply(
            bot,
            msg,
            f"🧭 You and {_dep_formatting._display_player(defender)} are together at the same map point "
            "on the active quest, so quest companions cannot duel each other here.",
        )
        return

    max_distance = max(0, int(_dep_config.MANUAL_DUEL_MAX_DISTANCE or 0))
    distance = _dep_events._duel_distance(attacker, defender)
    if distance > max_distance:
        _dep_formatting._reply(
            bot,
            msg,
            f"🗺️ {_dep_formatting._display_player(defender)} is too far away for a duel "
            f"(distance {distance:.1f}, max {max_distance}). Use `{_dep_formatting._command_prefix(bot)}idlerpg map` to find nearby players.",
        )
        return

    now = _dep_formatting._now()
    attacker_wait = _manual_duel_cooldown_remaining(attacker, now)
    if attacker_wait:
        _dep_formatting._reply(bot, msg, f"⏳ You can duel again in {_dep_formatting._duration_clock(attacker_wait)}.")
        return
    defender_wait = _manual_duel_cooldown_remaining(defender, now)
    if defender_wait:
        _dep_formatting._reply(bot, msg, f"⏳ {_dep_formatting._display_player(defender)} can be dueled again in {_dep_formatting._duration_clock(defender_wait)}.")
        return

    messages: list[str] = []
    achievement_snapshots = {
        str(attacker_jid): _dep_leveling._achievement_keys(attacker),
        str(defender_jid): _dep_leveling._achievement_keys(defender),
    }
    _dep_events._run_manual_duel(attacker, defender, messages, room, distance=distance)
    attacker["last_manual_duel_at"] = now
    defender["last_manual_duel_at"] = now
    _dep_leveling._inc_stat(attacker, "manual_duels_started", 1, room)
    _dep_leveling._inc_stat(defender, "manual_duels_received", 1, room)
    messages.extend(_dep_leveling._achievement_announcements(attacker, achievement_snapshots.get(str(attacker_jid), set())))
    messages.extend(_dep_leveling._achievement_announcements(defender, achievement_snapshots.get(str(defender_jid), set())))
    if messages:
        _dep_export._record_event(
            room,
            "duel",
            messages[0],
            players=[_dep_formatting._display_player(attacker), _dep_formatting._display_player(defender)],
            data={"distance": round(distance, 2)},
        )
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    await audit_event(
        bot,
        "idlerpg_duel",
        actor=sender_jid,
        target=room_jid,
        details={"attacker": _dep_formatting._display_player(attacker), "defender": _dep_formatting._display_player(defender)},
    )
    _dep_formatting._reply(bot, msg, "\n".join(messages))


async def _handle_align(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Alignment is room-scoped. Use it from a game room or MUC PM.")
        return
    if len(args) < 2 or args[1].lower() not in {"good", "neutral", "evil"}:
        _dep_formatting._reply(bot, msg, f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg align <good|neutral|evil>")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    _jid, player = _dep_state._find_player(room, sender_jid)
    if not player:
        _dep_formatting._reply(bot, msg, "❌ You do not have an IdleRPG character here yet.")
        return
    player["alignment"] = args[1].lower()[:1]
    _dep_export._record_event(room, "alignment", f"{player['name']} changed alignment to {args[1].lower()}.", players=[player['name']])
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    _dep_formatting._reply(bot, msg, f"⚖️ {player['name']} is now {args[1].lower()}.")


async def _handle_quest(bot, msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Quest is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    quest = room.get("quest", {})
    if not isinstance(quest, dict) or not quest.get("active"):
        next_at = int((quest or {}).get("next_at", 0) or 0) if isinstance(quest, dict) else 0
        suffix = f" Next quest check in {_dep_formatting._duration(next_at - _dep_formatting._now())}." if next_at else ""
        _dep_formatting._reply(bot, msg, "🧭 There is no active IdleRPG quest." + suffix)
        return
    players = room.get("players", {})
    names = [players[jid].get("name", jid) for jid in quest.get("questers", []) if jid in players]
    quest_kind = _dep_quests._quest_type(quest)
    remaining = _dep_formatting._duration(int(quest.get("complete_at", 0) or 0) - _dep_formatting._now())
    if quest_kind == "time":
        timing_text = f"Completes in {remaining}."
        target = _dep_map._quest_time_target(quest)
        target_text = (
            f"Map objective: [{target[0]},{target[1]}] near "
            f"{_dep_map._map_region_name(target[0], target[1])}. "
            if target
            else ""
        )
        detail = (
            f"{target_text}Every quester must remain online and avoid message or logout penalties "
            "until the timer ends; the map objective is informational and random game events do not fail the quest."
        )
    else:
        timing_text = f"Deadline in {remaining}."
        target = _dep_map._active_quest_target(quest)
        target_text = f"Current target: [{target[0]},{target[1]}]." if target else "No active route target."
        detail = f"{target_text} The quest completes as soon as all participants reach every route point."
    quest_url = _dep_export._website_url("quest")
    _dep_formatting._reply(
        bot,
        msg,
        f"🧭 {', '.join(names)} are on a quest ({quest_kind}-based) to {quest.get('text', 'adventure')}. "
        f"{timing_text} {detail}"
        + (f" See {quest_url} for details." if quest_url else ""),
    )


async def _handle_profile(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Profile is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    target = args[1] if len(args) > 1 else sender_jid
    jid, player = _dep_state._find_player(room, target)
    if not player:
        _dep_formatting._reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return
    player = _dep_state._normalize_player(str(jid), player)
    achievements = player.get("achievements", [])
    title = _dep_formatting._display_title(player) or "none"
    lines = [
        f"🧙 Profile: {_dep_formatting._display_player(player)}",
        f"Class: {player.get('class', 'idler')}",
        f"Title: {title}",
        f"Level: {player.get('level', 0)}",
        f"TTL: {_dep_formatting._duration_clock(player.get('next', 0))}",
        f"Playing since: {_dep_formatting._playing_since(player)}",
        f"Playing for: {_dep_formatting._played_for(player)}",
        f"Idled online: {_dep_formatting._duration_clock(player.get('idled', 0))}",
        f"Alignment: {_dep_formatting._alignment_name(player.get('alignment'))}",
        f"Map: [{player.get('x', 0)},{player.get('y', 0)}] near {_dep_map._player_region(player)}",
        f"Achievements: {len(achievements)}",
        f"Unique items: {len(player.get('unique_items', {}) if isinstance(player.get('unique_items'), dict) else {})}",
    ]
    url = _dep_export._profile_url(room_jid, player)
    if url:
        lines.append(f"Website: {url}")
    _dep_formatting._reply(bot, msg, "\n".join(lines))


async def _handle_achievements(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Achievements are room-scoped. Use this from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    if len(args) > 1 and args[1].lower() in {"list", "all", "catalog"}:
        target = args[2] if len(args) > 2 else sender_jid
        _jid, player = _dep_state._find_player(room, target)
        unlocked = set(player.get("achievements", []) if isinstance(player, dict) else [])
        lines = [
            f"{'✅' if key in unlocked else '▫️'} {key}: {title} — {description}"
            for key, title, description in (
                (item['key'], item['title'], item['description']) for item in _dep_leveling._achievement_catalog()
            )
        ]
        _dep_formatting._reply(bot, msg, "🏅 IdleRPG achievement catalog\n" + "\n".join(lines))
        return
    target = args[1] if len(args) > 1 else sender_jid
    jid, player = _dep_state._find_player(room, target)
    if not player:
        _dep_formatting._reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return
    player = _dep_state._normalize_player(str(jid), player)
    lines = []
    for key in player.get("achievements", []):
        lines.append(f"• {_dep_leveling._achievement_title(key)} — {_dep_leveling._achievement_description(key)}")
    if not lines:
        lines = ["No achievements yet. Use `" + _dep_formatting._command_prefix(bot) + "idlerpg achievements list` to show all available achievements."]
    _dep_formatting._reply(bot, msg, f"🏅 Achievements for {_dep_formatting._display_player(player)}\n" + "\n".join(lines))


async def _handle_title(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Titles are room-scoped. Use this from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    _jid, player = _dep_state._find_player(room, sender_jid)
    if not player:
        _dep_formatting._reply(bot, msg, "❌ You do not have an IdleRPG character here yet.")
        return
    player = _dep_state._normalize_player(sender_jid, player)
    achievements = set(player.get("achievements", []))
    if len(args) < 2 or args[1].lower() in {"list", "show"}:
        lines = [f"{key}: {_dep_leveling._achievement_title(key)}" for key in sorted(achievements)] or ["No unlocked titles yet."]
        _dep_formatting._reply(bot, msg, "🎖️ Available titles\n" + "\n".join(lines))
        return
    requested = args[1].lower()
    if requested in {"none", "clear", "off"}:
        player["title"] = ""
        await _dep_state._set_data(bot, data, room_jid=room_jid)
        _dep_formatting._reply(bot, msg, f"✅ {_dep_formatting._display_player(player)} cleared their title.")
        return
    if requested not in achievements:
        _dep_formatting._reply(bot, msg, f"❌ You have not unlocked that achievement title. Use `{_dep_formatting._command_prefix(bot)}idlerpg title list`.")
        return
    player["title"] = requested
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    _dep_formatting._reply(bot, msg, f"✅ {_dep_formatting._display_player(player)} now uses title: {_dep_leveling._achievement_title(requested)}.")


async def _handle_events(bot, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Events are room-scoped. Use this from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    events = list(reversed(_dep_export._room_events(room)))
    lines = []
    for event in events:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(event.get("ts", 0) or 0)))
        lines.append(f"{when} [{event.get('kind', 'event')}] {event.get('text', '')}")
    if not lines:
        lines = ["No IdleRPG events yet."]
    page_request = parse_page_args(args[1:])
    out = format_page(
        "📰 IdleRPG Recent Events",
        lines,
        page_request=page_request,
        page_size=_dep_config.PAGE_SIZE,
        command_hint=f"{_dep_formatting._command_prefix(bot)}idlerpg events",
    )
    _dep_formatting._reply(bot, msg, "\n".join(out))


async def _handle_stats(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ IdleRPG stats are room-scoped. Use this from a game room or MUC PM.")
        return
    if not await _dep_state._sender_can_manage_room(bot, sender_jid, room_jid):
        _dep_formatting._reply(bot, msg, "⛔ Only room owners/admins can inspect IdleRPG stats.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    ranked = _dep_state._ranked_players(room)
    events = _dep_export._room_events(room)
    day_cutoff = _dep_formatting._now() - 86400
    recent = [event for event in events if int(event.get("ts", 0) or 0) >= day_cutoff]
    kinds: dict[str, int] = {}
    for event in recent:
        kind = str(event.get("kind") or "event")
        kinds[kind] = kinds.get(kind, 0) + 1
    levels = [int(player.get("level", 0) or 0) for _jid, player in ranked]
    ttls = [int(player.get("next", 0) or 0) for _jid, player in ranked]
    unique_count = sum(
        len(player.get("unique_items", {}) if isinstance(player.get("unique_items"), dict) else {})
        for _jid, player in ranked
    )
    avg_level = (sum(levels) / len(levels)) if levels else 0
    avg_ttl = int(sum(ttls) / len(ttls)) if ttls else 0
    kind_line = ", ".join(f"{kind}: {count}" for kind, count in sorted(kinds.items())) or "none"
    season = room.get("season", {}) if isinstance(room.get("season"), dict) else {}
    lines = [
        f"📊 IdleRPG stats for {room_jid}",
        f"Players: {len(ranked)} ({sum(1 for jid, player in ranked if _dep_state._is_player_online(room_jid, jid, player))} online)",
        f"Average level: {avg_level:.1f}",
        f"Average TTL: {_dep_formatting._duration_clock(avg_ttl)}",
        f"Events total/exported: {len(events)}/{min(len(events), _dep_config.EXPORT_EVENT_LIMIT)}",
        f"Events last 24h: {len(recent)} ({kind_line})",
        f"Unique items held: {unique_count}",
        f"Current season: {season.get('id', 'unknown')}",
        f"Event retention: {_dep_config.EVENT_RETENTION_DAYS or 'limit-only'} days, max {_dep_config.EVENT_LOG_LIMIT}",
        f"Logout grace: {_dep_formatting._duration_clock(_dep_config.LOGOUT_GRACE_SECONDS)}",
        f"Login announcements: {'on' if _dep_config.ANNOUNCE_LOGIN else 'off'}",
        f"Top announcements: {_dep_formatting._duration_clock(_dep_config.ANNOUNCE_TOP_INTERVAL) if _dep_config.ANNOUNCE_TOP_INTERVAL > 0 else 'off'}",
        f"Topic updates: {'on' if _dep_config.UPDATE_ROOM_TOPIC else 'off'} ({_dep_config.TOPIC_CUSTOM_TEXT})",
    ]
    _dep_formatting._reply(bot, msg, "\n".join(lines))


async def _handle_map(bot, msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Map is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    players = _dep_state._ranked_players(room)
    quest = room.get("quest", {}) if isinstance(room.get("quest"), dict) else {}
    lines = _dep_map._render_ascii_map(room_jid, players, quest)
    url = _dep_export._website_url("map")
    if url:
        lines.append(f"World map: {url}")
    _dep_formatting._reply(bot, msg, "\n".join(lines))


async def _handle_hof(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Hall of fame is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    subargs = [str(arg).lower() for arg in args[1:]]
    if subargs:
        if subargs == ["clear", "confirm"]:
            if not await _dep_state._sender_can_manage_room(bot, sender_jid, room_jid):
                _dep_formatting._reply(bot, msg, "⛔ Only room owners/admins can clear the IdleRPG Hall of Fame.")
                return
            removed = len(room.get("hall_of_fame", []) if isinstance(room.get("hall_of_fame"), list) else [])
            room["hall_of_fame"] = []
            await _dep_state._set_data(bot, data, room_jid=room_jid)
            await audit_event(bot, "idlerpg_hof_clear", actor=sender_jid, target=room_jid, details={"removed": removed})
            _dep_formatting._reply(bot, msg, f"✅ IdleRPG Hall of Fame cleared for {room_jid}. Removed {removed} entries.")
            return
        _dep_formatting._reply(bot, msg, f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg hof [clear confirm]")
        return
    hof = room.get("hall_of_fame", []) if isinstance(room.get("hall_of_fame"), list) else []
    lines = []
    for entry in reversed(hof[-_dep_config.SEASON_HOF_SIZE:]):
        champion = entry.get("champion") or "no champion"
        lines.append(f"• Season {entry.get('id', '?')}: {champion}")
    if not lines:
        lines = ["No completed seasons yet."]
    _dep_formatting._reply(bot, msg, "🏛️ IdleRPG Hall of Fame\n" + "\n".join(lines))


async def _handle_season(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Seasons are room-scoped. Use this from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    subcmd = args[1].lower() if len(args) > 1 else "status"
    if subcmd == "discard":
        if len(args) != 3 or args[2].lower() != "confirm":
            _dep_formatting._reply(bot, msg, f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg season discard confirm")
            return
        if not await _dep_state._sender_can_manage_room(bot, sender_jid, room_jid):
            _dep_formatting._reply(bot, msg, "⛔ Only room owners/admins can discard IdleRPG seasons.")
            return
        result = _dep_seasons._discard_season(room)
        await _dep_state._set_data(bot, data, room_jid=room_jid, force_export=True)
        await audit_event(bot, "idlerpg_season_discard", actor=sender_jid, target=room_jid, details=result)
        _dep_formatting._reply(
            bot,
            msg,
            f"🗑️ Season {result['id']} discarded without a Hall of Fame entry. "
            f"Reset {result['reset_players']} players and removed {result['removed_events']} current-season events. "
            f"New season: {result['new_season_id']}.",
        )
        return
    if subcmd in {"end", "finish", "reset"}:
        if not await _dep_state._sender_can_manage_room(bot, sender_jid, room_jid):
            _dep_formatting._reply(bot, msg, "⛔ Only room owners/admins can end IdleRPG seasons.")
            return
        reset_players = subcmd == "reset"
        snapshot = _dep_seasons._end_season(room_jid, room, reset_players=reset_players)
        await _dep_state._set_data(bot, data, room_jid=room_jid)
        _dep_formatting._reply(
            bot,
            msg,
            f"🏁 Season {snapshot.get('id')} ended. Champion: {snapshot.get('champion') or 'no champion'}. "
            f"New season: {room['season']['id']}." + (" Players were reset." if reset_players else ""),
        )
        return
    if subcmd in {"extend", "clear-end"}:
        if not await _dep_state._sender_can_manage_room(bot, sender_jid, room_jid):
            _dep_formatting._reply(bot, msg, "⛔ Only room owners/admins can change IdleRPG season timing.")
            return
        season = room.get("season", {}) if isinstance(room.get("season"), dict) else _dep_seasons._blank_season(_dep_formatting._now())
        room["season"] = season
        if subcmd == "clear-end":
            season["ends_at"] = 0
            await _dep_state._set_data(bot, data, room_jid=room_jid)
            await audit_event(bot, "idlerpg_season_clear_end", actor=sender_jid, target=room_jid, details={"season_id": season.get("id")})
            _dep_formatting._reply(bot, msg, f"✅ IdleRPG season {season.get('id', 'unknown')} is now manual/endless.")
            return
        duration_arg = args[2].lower() if len(args) > 2 else ""
        if duration_arg in {"", "config", "default"}:
            amount = _dep_seasons._season_duration_seconds()
            if amount <= 0:
                season["ends_at"] = 0
                await _dep_state._set_data(bot, data, room_jid=room_jid)
                await audit_event(bot, "idlerpg_season_extend", actor=sender_jid, target=room_jid, details={"season_id": season.get("id"), "duration": 0})
                _dep_formatting._reply(bot, msg, f"✅ IdleRPG season {season.get('id', 'unknown')} is now manual/endless.")
                return
        elif duration_arg in {"0", "manual", "endless", "forever", "clear", "none"}:
            amount = 0
        else:
            parsed_amount = _core.parse_duration(duration_arg)
            if parsed_amount is None:
                _dep_formatting._reply(bot, msg, f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg season extend [duration|manual]")
                return
            amount = parsed_amount
        if amount <= 0:
            season["ends_at"] = 0
            action = "manual/endless"
        else:
            base = max(int(season.get("ends_at", 0) or 0), _dep_formatting._now())
            season["ends_at"] = base + int(amount)
            action = f"extended by {_dep_formatting._duration(amount)}"
        await _dep_state._set_data(bot, data, room_jid=room_jid)
        await audit_event(bot, "idlerpg_season_extend", actor=sender_jid, target=room_jid, details={"season_id": season.get("id"), "duration": int(amount)})
        _dep_formatting._reply(bot, msg, f"✅ IdleRPG season {season.get('id', 'unknown')} {action}. Ends in {_dep_seasons._season_end_summary(season)}.")
        return
    if subcmd in {"hof", "hall", "hall-of-fame"}:
        await _handle_hof(bot, sender_jid, ["hof", *args[2:]], msg, is_room)
        return
    season = room.get("season", {}) if isinstance(room.get("season"), dict) else _dep_seasons._blank_season(_dep_formatting._now())
    remaining = _dep_seasons._season_end_summary(season)
    _dep_formatting._reply(
        bot,
        msg,
        f"🏁 Current season: {season.get('id', 'unknown')} — ends in {remaining}. "
        f"Hall of fame entries: {len(room.get('hall_of_fame', []) if isinstance(room.get('hall_of_fame'), list) else [])}.",
    )


async def _handle_announce_top(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Top announcements are room-scoped. Use it from a game room or MUC PM.")
        return
    if not await _dep_state._sender_can_manage_room(bot, sender_jid, room_jid):
        _dep_formatting._reply(bot, msg, "⛔ Only room owners/admins can announce IdleRPG top players.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    _dep_formatting._system_reply(bot, room_jid, "\n".join(_dep_formatting._format_top_lines(room, limit=_dep_config.ANNOUNCE_TOP_LIMIT, room_jid=room_jid)))
    room["next_top_announce_at"] = _dep_formatting._now() + _dep_config.ANNOUNCE_TOP_INTERVAL if _dep_config.ANNOUNCE_TOP_INTERVAL > 0 else 0
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    _dep_formatting._reply(bot, msg, "✅ IdleRPG top players announced.")


async def _handle_topic_update(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Topic updates are room-scoped. Use it from a game room or MUC PM.")
        return
    if not await _dep_state._sender_can_manage_room(bot, sender_jid, room_jid):
        _dep_formatting._reply(bot, msg, "⛔ Only room owners/admins can update the IdleRPG topic.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    custom_text = " ".join(str(part) for part in args[2:]).strip() if len(args) > 2 else None
    _dep_formatting._maybe_set_room_topic(bot, room_jid, room, custom_text=custom_text, force=True)
    room["next_topic_update_at"] = _dep_formatting._now() + _dep_config.TOPIC_UPDATE_INTERVAL if _dep_config.TOPIC_UPDATE_INTERVAL > 0 else 0
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    preview = _dep_formatting._topic_text(room, custom_text=custom_text)[:250]
    _dep_formatting._reply(bot, msg, f"✅ IdleRPG room topic update requested: {preview}")


async def _handle_export(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Export is room-scoped. Use it from a game room or MUC PM.")
        return
    if not await _dep_state._sender_can_manage_room(bot, sender_jid, room_jid):
        _dep_formatting._reply(bot, msg, "⛔ Only room owners/admins can refresh IdleRPG exports.")
        return
    data = await _dep_state._get_data(bot)
    await _dep_state._refresh_public_export(bot, data)
    root = _dep_export._export_root()
    _dep_formatting._reply(bot, msg, f"📤 IdleRPG export refreshed for {room_jid}: {root / _dep_formatting._room_slug(room_jid)}")


async def _handle_remove_me(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ remove-me is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    _jid, player = _dep_state._find_player(room, sender_jid)
    if not player:
        _dep_formatting._reply(bot, msg, "❌ You do not have an IdleRPG character here.")
        return
    name = _dep_formatting._display_player(player)
    room.get("players", {}).pop(sender_jid, None)
    _dep_state._rebuild_name_index(room)
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    await audit_event(bot, "idlerpg_remove_me", actor=sender_jid, target=room_jid, details={"name": name})
    _dep_formatting._reply(bot, msg, f"🗑️ IdleRPG character {name} removed.")


def _player_last_activity(player: dict[str, Any]) -> int:
    """Return the latest trustworthy activity timestamp for stale-player cleanup."""
    values: list[int] = []
    for key in ("last_seen", "last_login", "logged_out_at", "created_at"):
        try:
            value = int(player.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            values.append(value)
    return max(values, default=0)


def _old_offline_players(
    room: dict[str, Any],
    room_jid: str,
    *,
    days: int,
    now: int | None = None,
) -> list[tuple[str, dict[str, Any], int]]:
    """Return offline, non-quest players inactive for at least ``days`` days."""
    now = int(now if now is not None else _dep_formatting._now())
    cutoff_age = max(1, int(days)) * 86400
    quest = room.get("quest", {}) if isinstance(room.get("quest"), dict) else {}
    protected_questers = (
        {str(jid) for jid in quest.get("questers", [])}
        if quest.get("active")
        else set()
    )
    result: list[tuple[str, dict[str, Any], int]] = []
    players = room.get("players", {})
    if not isinstance(players, dict):
        return result
    for jid, raw_player in players.items():
        if not isinstance(raw_player, dict):
            continue
        player = _dep_state._normalize_player(str(jid), raw_player)
        if str(jid) in protected_questers:
            continue
        if _dep_state._is_player_online(room_jid, str(jid), player):
            continue
        last_activity = _player_last_activity(player)
        inactive_for = max(0, now - last_activity) if last_activity > 0 else 0
        if last_activity > 0 and inactive_for >= cutoff_age:
            result.append((str(jid), player, inactive_for))
    result.sort(key=lambda item: (-item[2], _dep_formatting._display_player(item[1]).lower()))
    return result


async def _handle_delold(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ delold is room-scoped. Use it from a game room or MUC PM.")
        return
    if not await _dep_state._sender_can_manage_room(bot, sender_jid, room_jid):
        _dep_formatting._reply(bot, msg, "⛔ Only room owners/admins can remove inactive IdleRPG characters.")
        return
    if len(args) < 2 or not str(args[1]).isdigit() or int(args[1]) < 1:
        _dep_formatting._reply(
            bot,
            msg,
            f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg delold <days> [confirm]",
        )
        return

    days = int(args[1])
    confirmed = len(args) == 3 and str(args[2]).lower() == "confirm"
    if len(args) > 3 or (len(args) == 3 and not confirmed):
        _dep_formatting._reply(
            bot,
            msg,
            f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg delold <days> [confirm]",
        )
        return

    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    candidates = _old_offline_players(room, room_jid, days=days)
    if not candidates:
        _dep_formatting._reply(
            bot,
            msg,
            f"ℹ️ No offline IdleRPG characters have been inactive for at least {days} days.",
        )
        return

    preview = ", ".join(
        f"{_dep_formatting._display_player(player)} ({_dep_formatting._duration(inactive_for)})"
        for _jid, player, inactive_for in candidates[:20]
    )
    if len(candidates) > 20:
        preview += f", … and {len(candidates) - 20} more"

    candidate_noun = "character" if len(candidates) == 1 else "characters"
    if not confirmed:
        _dep_formatting._reply(
            bot,
            msg,
            f"🧹 {len(candidates)} offline IdleRPG {candidate_noun} have been inactive for at least {days} days: "
            f"{preview}\nRun {_dep_formatting._command_prefix(bot)}idlerpg delold {days} confirm to delete them.",
        )
        return

    players = room.get("players", {})
    removed_names: list[str] = []
    for jid, player, _inactive_for in candidates:
        if isinstance(players, dict) and players.pop(jid, None) is not None:
            removed_names.append(_dep_formatting._display_player(player))
    _dep_state._rebuild_name_index(room)
    _dep_export._record_event(
        room,
        "admin",
        f"Removed {len(removed_names)} offline character(s) inactive for at least {days} days.",
        players=removed_names,
    )
    await _dep_state._set_data(bot, data, room_jid=room_jid, force_export=True)
    await audit_event(
        bot,
        "idlerpg_delold",
        actor=sender_jid,
        target=room_jid,
        details={"days": days, "removed": len(removed_names), "characters": removed_names},
    )
    removed_noun = "character" if len(removed_names) == 1 else "characters"
    _dep_formatting._reply(
        bot,
        msg,
        f"🗑️ Removed {len(removed_names)} offline IdleRPG {removed_noun} inactive for at least {days} days: "
        + ", ".join(removed_names),
    )


async def _handle_admin(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> bool:
    subcmd = args[0].lower() if args else ""
    if subcmd not in {"push", "setlevel", "reset", "delete", "remove", "delold"}:
        return False
    if subcmd == "delold":
        await _handle_delold(bot, sender_jid, args, msg, is_room)
        return True
    room_jid = _dep_state._room_from_context(msg, is_room)
    if not room_jid:
        _dep_formatting._reply(bot, msg, "ℹ️ Admin actions are room-scoped. Use them from a game room or MUC PM.")
        return True
    if not await _dep_state._sender_can_manage_room(bot, sender_jid, room_jid):
        _dep_formatting._reply(bot, msg, "⛔ Only room owners/admins can use this IdleRPG admin command.")
        return True
    if len(args) < 2:
        _dep_formatting._reply(bot, msg, f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg {subcmd} <character> [...]")
        return True
    data = await _dep_state._get_data(bot)
    room = _dep_state._room_bucket(data, room_jid)
    jid, player = _dep_state._find_player(room, args[1])
    if not player or not jid:
        _dep_formatting._reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return True
    name = _dep_formatting._display_player(player)
    if subcmd == "push":
        if len(args) < 3:
            _dep_formatting._reply(bot, msg, f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg push <character> <duration>")
            return True
        amount = _core.parse_duration(args[2])
        if amount is None:
            _dep_formatting._reply(bot, msg, "❌ Invalid duration. Example: 10m, 1h30m, 2d")
            return True
        changed = _dep_leveling._remove_time(player, amount)
        text = (
            f"✅ Pushed {name} {_dep_formatting._duration_clock(changed)} toward next level. "
            + _dep_formatting._next_level_line(player)
        )
    elif subcmd == "setlevel":
        if len(args) < 3 or not str(args[2]).isdigit():
            _dep_formatting._reply(bot, msg, f"Usage: {_dep_formatting._command_prefix(bot)}idlerpg setlevel <character> <level>")
            return True
        previous_achievements = _dep_leveling._achievement_keys(player)
        player["level"] = max(0, int(args[2]))
        player["next"] = _dep_leveling._ttl_for_level(player["level"])
        _dep_leveling._check_level_achievements(player, room)
        text = f"✅ Set {name} to level {player['level']}. " + _dep_formatting._next_level_line(player)
        achievement_lines = _dep_leveling._achievement_announcements(player, previous_achievements)
        if achievement_lines:
            text += "\n" + "\n".join(achievement_lines)
    elif subcmd == "reset":
        player["level"] = 0
        player["next"] = _dep_leveling._ttl_for_level(0)
        player["idled"] = 0
        player["items"] = {item: 0 for item in _dep_constants.ITEMS}
        player["penalties"] = {}
        text = f"✅ Reset {name}. " + _dep_formatting._next_level_line(player)
    else:
        room.get("players", {}).pop(str(jid), None)
        _dep_state._rebuild_name_index(room)
        text = f"🗑️ Deleted IdleRPG character {name}."
    await _dep_state._set_data(bot, data, room_jid=room_jid)
    await audit_event(bot, f"idlerpg_{subcmd}", actor=sender_jid, target=room_jid, details={"character": name})
    _dep_formatting._reply(bot, msg, text)
    return True


@command(
    "idlerpg",
    role=Role.USER,
    aliases=["irpg", "idle"],
    short="Play IdleRPG in a MUC",
    usage="{prefix}idlerpg <on|off|enabled|register|status|top|players|profile|duel|events|stats|map|season|...>",
    subcommands=[
        _player_help_subcommand(
            "register",
            "{prefix}idlerpg register <character> <class>",
            "Create a new IdleRPG character in the current game room.",
            examples=[help_example("{prefix}idlerpg register Sven sysadmin", "Register the character Sven with the class 'sysadmin'.")],
        ),
        _player_help_subcommand(
            "login",
            "{prefix}idlerpg login",
            "Mark your registered character as online in the current game room.",
            examples=[help_example("{prefix}idlerpg login", "Log your IdleRPG character into the game.")],
        ),
        _player_help_subcommand(
            "logout",
            "{prefix}idlerpg logout",
            "Mark your character as offline without deleting it.",
            examples=[help_example("{prefix}idlerpg logout", "Log your IdleRPG character out of the game.")],
        ),
        _player_help_subcommand(
            "status",
            "{prefix}idlerpg status [character]",
            "Show progress, level, online state and next-level time.",
            aliases=("me", "whoami"),
            examples=[help_example("{prefix}idlerpg status", "Show your own character status.")],
        ),
        _player_help_subcommand(
            "top",
            "{prefix}idlerpg top [page|last|all]",
            "Show the character leaderboard ordered by level and progress.",
            examples=[help_example("{prefix}idlerpg top", "Show the first leaderboard page.")],
        ),
        _player_help_subcommand(
            "players",
            "{prefix}idlerpg players [page|last|all]",
            "List registered characters and their online state.",
            aliases=("list",),
            examples=[help_example("{prefix}idlerpg players all", "List every registered character in the room.")],
        ),
        _player_help_subcommand(
            "items",
            "{prefix}idlerpg items [character]",
            "Show equipment and item levels for a character.",
            examples=[help_example("{prefix}idlerpg items Sven", "Show Sven's current equipment.")],
        ),
        _player_help_subcommand(
            "profile",
            "{prefix}idlerpg profile [character]",
            "Show a complete character profile and website link.",
            aliases=("char", "character"),
            examples=[help_example("{prefix}idlerpg profile Sven", "Show Sven's full character profile.")],
        ),
        _player_help_subcommand(
            "achievements",
            "{prefix}idlerpg achievements [character|list]",
            "Show earned achievements or list available achievements.",
            aliases=("achievement", "badges"),
            examples=[help_example("{prefix}idlerpg achievements Sven", "Show achievements earned by Sven.")],
        ),
        _player_help_subcommand(
            "title",
            "{prefix}idlerpg title <achievement|none>",
            "Select an earned achievement as your visible character title.",
            examples=[help_example("{prefix}idlerpg title veteran", "Use the earned 'veteran' achievement as your title.")],
        ),
        _player_help_subcommand(
            "events",
            "{prefix}idlerpg events [page|last|all]",
            "Show recent game events and character changes.",
            aliases=("eventlog", "news"),
            examples=[help_example("{prefix}idlerpg events", "Show the latest IdleRPG events.")],
        ),
        _admin_help_subcommand(
            "stats",
            "{prefix}idlerpg stats",
            "Show room-wide game balance and runtime statistics as a room owner/admin.",
            aliases=("balance",),
            examples=[help_example("{prefix}idlerpg stats", "Show statistics for the current IdleRPG room.")],
            context="room or MUC PM; room owner/admin",
        ),
        _player_help_subcommand(
            "duel",
            "{prefix}idlerpg duel <character>",
            "Challenge another online character to a duel.",
            aliases=("challenge",),
            examples=[help_example("{prefix}idlerpg duel Alice", "Challenge Alice to a duel.")],
        ),
        _player_help_subcommand(
            "align",
            "{prefix}idlerpg align <good|neutral|evil>",
            "Set your character alignment.",
            examples=[help_example("{prefix}idlerpg align neutral", "Set your alignment to neutral.")],
        ),
        _player_help_subcommand(
            "quest",
            "{prefix}idlerpg quest",
            "Show the active quest, participants, deadline and website link.",
            examples=[help_example("{prefix}idlerpg quest", "Show the current room quest.")],
        ),
        _player_help_subcommand(
            "map",
            "{prefix}idlerpg map",
            "Show character positions and the public world-map link.",
            examples=[help_example("{prefix}idlerpg map", "Show the current IdleRPG map summary.")],
        ),
        _player_help_subcommand(
            "hof",
            "{prefix}idlerpg hof",
            "Show the room's Hall of Fame.",
            aliases=("hall", "hall-of-fame"),
            examples=[help_example("{prefix}idlerpg hof", "Show the room's Hall of Fame.")],
        ),
        _admin_help_subcommand(
            "hof clear",
            "{prefix}idlerpg hof clear confirm",
            "Clear all Hall of Fame entries as a room owner/admin.",
            examples=[help_example("{prefix}idlerpg hof clear confirm", "Clear the room's Hall of Fame after explicit confirmation.")],
            context="room or MUC PM; room owner/admin",
        ),
        _player_help_subcommand(
            "season",
            "{prefix}idlerpg season [status]",
            "Show the current season, remaining time and Hall of Fame count.",
            examples=[help_example("{prefix}idlerpg season", "Show the current season and remaining time.")],
        ),
        _admin_help_subcommand(
            "season end",
            "{prefix}idlerpg season end",
            "Archive the current ranking and start a new season without resetting players.",
            aliases=("season finish",),
            examples=[help_example("{prefix}idlerpg season end", "End the current season while keeping player progress.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "season reset",
            "{prefix}idlerpg season reset",
            "Archive the current ranking, start a new season and reset player progress.",
            examples=[help_example("{prefix}idlerpg season reset", "Start a fresh season and reset every room character.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "season discard",
            "{prefix}idlerpg season discard confirm",
            "Discard the active season without archiving it and fully reset all players.",
            examples=[help_example("{prefix}idlerpg season discard confirm", "Delete a faulty current season without adding it to the Hall of Fame.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "season extend",
            "{prefix}idlerpg season extend [duration|manual]",
            "Extend the current season, use the configured default, or make it manual/endless.",
            examples=[help_example("{prefix}idlerpg season extend 7d", "Extend the current season by seven days.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "season clear-end",
            "{prefix}idlerpg season clear-end",
            "Remove the automatic season end and make the season manual/endless.",
            examples=[help_example("{prefix}idlerpg season clear-end", "Remove the current season deadline.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "push",
            "{prefix}idlerpg push <character> <duration>",
            "Remove time from a character's next-level clock as a room owner/admin.",
            examples=[help_example("{prefix}idlerpg push Alice 10m", "Move Alice ten minutes closer to the next level.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "setlevel",
            "{prefix}idlerpg setlevel <character> <level>",
            "Set a character's level and recalculate its timer as a room owner/admin.",
            examples=[help_example("{prefix}idlerpg setlevel Alice 25", "Set Alice to level 25.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "reset",
            "{prefix}idlerpg reset <character>",
            "Reset one character's progress, items and penalties as a room owner/admin.",
            examples=[help_example("{prefix}idlerpg reset Alice", "Reset Alice's current character progress.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "delete",
            "{prefix}idlerpg delete <character>",
            "Permanently delete another character as a room owner/admin.",
            aliases=("remove",),
            examples=[help_example("{prefix}idlerpg delete Alice", "Delete Alice's room character.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "delold",
            "{prefix}idlerpg delold <days> [confirm]",
            "Preview or delete offline characters inactive for at least the given number of days.",
            examples=[
                help_example("{prefix}idlerpg delold 90", "Preview characters inactive for at least 90 days."),
                help_example("{prefix}idlerpg delold 90 confirm", "Delete the previewed inactive characters."),
            ],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "export",
            "{prefix}idlerpg export",
            "Refresh the room's public IdleRPG export as a room owner/admin.",
            examples=[help_example("{prefix}idlerpg export", "Regenerate public website data for the room.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "announce top",
            "{prefix}idlerpg announce top",
            "Post the current leaderboard to the room as a room owner/admin.",
            examples=[help_example("{prefix}idlerpg announce top", "Announce the current top characters in the room.")],
            context="room or MUC PM; room owner/admin",
        ),
        _admin_help_subcommand(
            "topic update",
            "{prefix}idlerpg topic update [custom text]",
            "Refresh the room topic from game state as a room owner/admin.",
            examples=[help_example("{prefix}idlerpg topic update IdleRPG", "Set the generated room topic with custom prefix text.")],
            context="room or MUC PM; room owner/admin",
        ),
        _player_help_subcommand(
            "remove-me",
            "{prefix}idlerpg remove-me",
            "Permanently delete your own IdleRPG character.",
            aliases=("removeme",),
            examples=[help_example("{prefix}idlerpg remove-me", "Delete your own character after confirmation handling.")],
        ),
        *room_toggle_subcommands(
            "idlerpg",
            "IdleRPG",
            status_name="enabled",
            context="room or MUC PM; room owner/admin",
            section=_ADMIN_HELP_SECTION,
        ),
    ],
    examples=[
        "{prefix}idlerpg register Sven sysadmin",
        "{prefix}idlerpg enabled",
        "{prefix}idlerpg status",
        "{prefix}idlerpg top",
        "{prefix}idlerpg duel Alice",
        "{prefix}idlerpg quest",
        "{prefix}idlerpg map",
        "{prefix}idlerpg profile Sven",
        "{prefix}idlerpg events",
        "{prefix}idlerpg stats",
        "{prefix}idlerpg announce top",
        "{prefix}idlerpg topic update IdleRPG",
    ],
    category="fun",
    context="groupchat / MUC PM",
)
async def idlerpg_command(bot, sender_jid, nick, args, msg, is_room):
    subcmd = args[0].lower() if args else ""
    # ``status`` is reserved for character status. Use ``enabled`` to inspect
    # the room feature state so players do not get different meanings for the
    # same subcommand in public rooms and MUC PMs.
    if subcmd in {"on", "off", "enabled"}:
        toggle_args = ["status"] + args[1:] if subcmd == "enabled" else args
        handled_toggle = await _core.handle_room_toggle_command(
            bot,
            msg,
            is_room,
            toggle_args,
            store_getter=_dep_formatting.get_idlerpg_store,
            key=_dep_constants.IDLERPG_ENABLED_KEY,
            label="IdleRPG",
            plugin=_dep_constants.PLUGIN_NAME,
            log_prefix="[IDLERPG]",
        )
        if handled_toggle:
            await _dep_tasks._sync_tasks_to_enabled_rooms(bot)
            if subcmd in {"on", "off"}:
                await _dep_state._refresh_public_export(bot)
            return

    if not args:
        _dep_formatting._reply(bot, msg, _dep_formatting._usage(bot))
        return

    resolved_sender, _, _ = await _core.get_real_jid(bot, msg)
    sender = str(resolved_sender or sender_jid or "")
    subcmd = args[0].lower()

    if await _handle_admin(bot, sender, args, msg, is_room):
        return
    if subcmd == "register":
        await _handle_register(bot, sender, args, msg, is_room)
    elif subcmd == "login":
        await _handle_login(bot, sender, msg, is_room)
    elif subcmd == "logout":
        await _handle_logout(bot, sender, msg, is_room)
    elif subcmd in {"status", "me", "whoami"}:
        await _handle_status(bot, args, msg, is_room)
    elif subcmd == "top":
        await _handle_top(bot, args, msg, is_room)
    elif subcmd in {"players", "list"}:
        await _handle_players(bot, args, msg, is_room)
    elif subcmd == "items":
        await _handle_items(bot, sender, args, msg, is_room)
    elif subcmd in {"profile", "char", "character"}:
        await _handle_profile(bot, sender, args, msg, is_room)
    elif subcmd in {"achievements", "achievement", "badges"}:
        await _handle_achievements(bot, sender, args, msg, is_room)
    elif subcmd in {"events", "eventlog", "news"}:
        await _handle_events(bot, args, msg, is_room)
    elif subcmd in {"stats", "balance"}:
        await _handle_stats(bot, sender, msg, is_room)
    elif subcmd in {"duel", "challenge"}:
        await _handle_duel(bot, sender, args, msg, is_room)
    elif subcmd == "title":
        await _handle_title(bot, sender, args, msg, is_room)
    elif subcmd == "map":
        await _handle_map(bot, msg, is_room)
    elif subcmd in {"hof", "hall", "hall-of-fame"}:
        await _handle_hof(bot, sender, args, msg, is_room)
    elif subcmd == "season":
        await _handle_season(bot, sender, args, msg, is_room)
    elif subcmd == "export":
        await _handle_export(bot, sender, msg, is_room)
    elif subcmd == "announce" and len(args) > 1 and args[1].lower() == "top":
        await _handle_announce_top(bot, sender, msg, is_room)
    elif subcmd == "topic" and len(args) > 1 and args[1].lower() == "update":
        await _handle_topic_update(bot, sender, args, msg, is_room)
    elif subcmd == "align":
        await _handle_align(bot, sender, args, msg, is_room)
    elif subcmd == "quest":
        await _handle_quest(bot, msg, is_room)
    elif subcmd in {"remove-me", "removeme"}:
        await _handle_remove_me(bot, sender, msg, is_room)
    elif subcmd in {"help", "usage"}:
        _dep_formatting._reply(bot, msg, _dep_formatting._usage(bot))
    else:
        _dep_formatting._reply(bot, msg, f"❌ Unknown IdleRPG command: {subcmd}\n" + _dep_formatting._usage(bot))

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
from . import tasks as _dep_tasks  # noqa: E402
