"""Split module for plugins/idlerpg.py: commands."""

from __future__ import annotations
import random
import time
from utils.audit import audit_event
from utils.formatting import format_page, parse_page_args
from core_plugins import _core


async def _handle_register(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Register from the game room or a MUC private message.")
        return
    if not await _core._is_enabled_for_room(bot, IDLERPG_ENABLED_KEY, PLUGIN_NAME, room_jid):
        _reply(bot, msg, "ℹ️ IdleRPG is not enabled in this room.")
        return
    if len(args) < 3:
        _reply(bot, msg, f"Usage: {_command_prefix(bot)}idlerpg register <character> <class>")
        return
    name = _safe_name(args[1])
    char_class = _safe_class(" ".join(args[2:]))
    if not name:
        _reply(bot, msg, "❌ Character names may only contain letters, numbers, dot, underscore and dash.")
        return
    if not char_class:
        _reply(bot, msg, "❌ Character class may not be empty.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    players = room.setdefault("players", {})
    index = _rebuild_name_index(room)
    if sender_jid in players:
        _reply(bot, msg, "ℹ️ You already have an IdleRPG character in this room.")
        return
    if name.lower() in index:
        _reply(bot, msg, f"❌ Character name {name} is already taken.")
        return
    now = _now()
    player = _normalize_player(sender_jid, {
        "jid": sender_jid,
        "name": name,
        "class": char_class,
        "level": 0,
        "next": _ttl_for_level(0),
        "idled": 0,
        "created_at": now,
        "last_login": now,
        "last_seen": now,
        "alignment": "n",
        "items": {item: 0 for item in ITEMS},
        "unique_items": {},
        "penalties": {},
        "achievements": ["founder"],
        "title": "",
        "x": random.randint(0, MAP_X),
        "y": random.randint(0, MAP_Y),
        "logged_out": False,
    })
    players[sender_jid] = player
    _rebuild_name_index(room)
    _record_event(room, "register", f"Welcome {name}, the {char_class}!", players=[name])
    await _set_data(bot, data)
    await _ensure_game_task(bot, room_jid)
    await audit_event(bot, "idlerpg_register", actor=sender_jid, target=room_jid, details={"name": name})
    _reply(
        bot,
        msg,
        f"🎲 Welcome {name}, the {char_class}! Next level in {_duration(player['next'])}. "
        "The point of the game is to idle: normal room messages add time to your timer.",
    )


async def _handle_login(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Login from the game room or a MUC private message.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    _jid, player = _find_player(room, sender_jid)
    if not player:
        _reply(bot, msg, "❌ You do not have an IdleRPG character here yet.")
        return
    player = _normalize_player(sender_jid, player)
    pending = player.get("pending_logout_penalty") if isinstance(player.get("pending_logout_penalty"), dict) else {}
    reply_suffix = ""
    if pending:
        due_at = int(pending.get("due_at", 0) or 0)
        if due_at > _now():
            player["pending_logout_penalty"] = {}
            reply_suffix = " Logout grace used; no logout penalty was applied."
        else:
            changed = _apply_logout_penalty(player)
            reply_suffix = f" Logout penalty applied: {_duration_clock(changed)}. " + _next_level_line(player)
    player["logged_out"] = False
    player["last_login"] = _now()
    player["last_seen"] = _now()
    login_text = (
        f"👤 {_display_character(player)}, the level {player.get('level', 0)} {player.get('class', 'idler')}, "
        f"is now online from nickname {getattr(msg['from'], 'resource', None) or _display_player(player)}. "
        f"Next level in {_duration_clock(player.get('next', 0))}."
    )
    _record_event(room, "login", login_text, players=[_display_player(player)])
    await _set_data(bot, data)
    await _ensure_game_task(bot, room_jid)
    if ANNOUNCE_LOGIN:
        _system_reply(bot, room_jid, login_text)
    _reply(bot, msg, f"✅ {_display_player(player)} is now online for IdleRPG." + reply_suffix)


async def _handle_logout(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Logout from the game room or a MUC private message.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    _jid, player = _find_player(room, sender_jid)
    if not player:
        _reply(bot, msg, "❌ You do not have an IdleRPG character here yet.")
        return
    player = _normalize_player(sender_jid, player)
    player["logged_out"] = True
    player["logged_out_at"] = _now()
    name = _display_player(player)
    if LOGOUT_GRACE_SECONDS > 0:
        player["pending_logout_penalty"] = {
            "created_at": _now(),
            "due_at": _now() + LOGOUT_GRACE_SECONDS,
        }
        _record_event(
            room,
            "logout",
            f"{name} logged out. Logout penalty is pending for {_duration_clock(LOGOUT_GRACE_SECONDS)}.",
            players=[name],
        )
        await _set_data(bot, data)
        _reply(
            bot,
            msg,
            f"👋 {name} logged out. Reconnect within {_duration_clock(LOGOUT_GRACE_SECONDS)} "
            "to avoid the logout penalty.",
        )
        return
    changed = _apply_logout_penalty(player)
    _record_event(room, "logout", f"{name} logged out. {_duration_clock(changed)} was added to their clock.", players=[name])
    await _set_data(bot, data)
    _reply(
        bot,
        msg,
        f"👋 {name} logged out. {_duration_clock(changed)} is added to "
        f"{_possessive(name)} clock. "
        + _next_level_line(player),
    )


async def _handle_status(bot, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Status is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    target = args[1] if len(args) > 1 else None
    if not target:
        sender_jid, _, _ = await _core.get_real_jid(bot, msg)
        target = sender_jid
    jid, player = _find_player(room, target)
    if not player:
        _reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return
    _reply(bot, msg, _format_player_status(room_jid, str(jid), _normalize_player(str(jid), player)))


async def _handle_top(bot, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Top is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    players = [
        (str(jid), _normalize_player(str(jid), player))
        for jid, player in room.get("players", {}).items()
        if isinstance(player, dict)
    ]
    players.sort(key=lambda item: (-int(item[1].get("level", 0)), int(item[1].get("next", 0)), item[1].get("name", "")))
    lines = [
        f"{idx}. {p['name']}, level {p['level']} {p['class']} — TTL {_duration(p['next'])}"
        for idx, (_jid, p) in enumerate(players, start=1)
    ]
    page_request = parse_page_args(args[1:])
    out = format_page(
        "🏆 IdleRPG Top Players",
        lines,
        page_request=page_request,
        page_size=PAGE_SIZE,
        command_hint=f"{_command_prefix(bot)}idlerpg top",
    )
    _reply(bot, msg, "\n".join(out))


async def _handle_players(bot, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Players is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    entries = []
    for jid, player in room.get("players", {}).items():
        if not isinstance(player, dict):
            continue
        player = _normalize_player(str(jid), player)
        mark = "🟢" if _is_player_online(room_jid, str(jid), player) else "⚫"
        entries.append(f"{mark} {player['name']} — level {player['level']} {player['class']}")
    entries.sort(key=str.lower)
    page_request = parse_page_args(args[1:])
    out = format_page(
        "🎲 IdleRPG Players",
        entries,
        page_request=page_request,
        page_size=PAGE_SIZE,
        command_hint=f"{_command_prefix(bot)}idlerpg players",
    )
    _reply(bot, msg, "\n".join(out))


async def _handle_items(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Items are room-scoped. Use this from a game room or MUC PM.")
        return
    target = args[1] if len(args) > 1 else sender_jid
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    jid, player = _find_player(room, target)
    if not player:
        _reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return
    player = _normalize_player(str(jid), player)
    unique_items = player.get("unique_items", {}) if isinstance(player.get("unique_items"), dict) else {}
    lines = []
    bonus_map = {item["name"]: item for item in _unique_bonuses(player)}
    for name, level in sorted(player["items"].items()):
        unique = unique_items.get(name)
        bonus = bonus_map.get(unique or "")
        suffix = ""
        if unique:
            suffix = f" — {unique}"
            if bonus:
                suffix += f" ({bonus['bonus_percent']}% {str(bonus['bonus']).replace('_', ' ')})"
        lines.append(f"{name}: {level}{suffix}")
    _reply(bot, msg, f"🎒 Items for {player['name']}\n" + "\n".join(lines))


async def _handle_align(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Alignment is room-scoped. Use it from a game room or MUC PM.")
        return
    if len(args) < 2 or args[1].lower() not in {"good", "neutral", "evil"}:
        _reply(bot, msg, f"Usage: {_command_prefix(bot)}idlerpg align <good|neutral|evil>")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    _jid, player = _find_player(room, sender_jid)
    if not player:
        _reply(bot, msg, "❌ You do not have an IdleRPG character here yet.")
        return
    player["alignment"] = args[1].lower()[:1]
    _record_event(room, "alignment", f"{player['name']} changed alignment to {args[1].lower()}.", players=[player['name']])
    await _set_data(bot, data)
    _reply(bot, msg, f"⚖️ {player['name']} is now {args[1].lower()}.")


async def _handle_quest(bot, msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Quest is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    quest = room.get("quest", {})
    if not isinstance(quest, dict) or not quest.get("active"):
        next_at = int((quest or {}).get("next_at", 0) or 0) if isinstance(quest, dict) else 0
        suffix = f" Next quest check in {_duration(next_at - _now())}." if next_at else ""
        _reply(bot, msg, "🧭 There is no active IdleRPG quest." + suffix)
        return
    players = room.get("players", {})
    names = [players[jid].get("name", jid) for jid in quest.get("questers", []) if jid in players]
    _reply(
        bot,
        msg,
        f"🧭 {', '.join(names)} are on a quest to {quest.get('text', 'adventure')}. "
        f"Completes in {_duration(int(quest.get('complete_at', 0) or 0) - _now())}.",
    )


async def _handle_profile(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Profile is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    target = args[1] if len(args) > 1 else sender_jid
    jid, player = _find_player(room, target)
    if not player:
        _reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return
    player = _normalize_player(str(jid), player)
    achievements = player.get("achievements", [])
    title = _display_title(player) or "none"
    lines = [
        f"🧙 Profile: {_display_player(player)}",
        f"Class: {player.get('class', 'idler')}",
        f"Title: {title}",
        f"Level: {player.get('level', 0)}",
        f"TTL: {_duration_clock(player.get('next', 0))}",
        f"Alignment: {_alignment_name(player.get('alignment'))}",
        f"Map: [{player.get('x', 0)},{player.get('y', 0)}] near {_player_region(player)}",
        f"Achievements: {len(achievements)}",
        f"Unique items: {len(player.get('unique_items', {}) if isinstance(player.get('unique_items'), dict) else {})}",
    ]
    url = _profile_url(room_jid, player)
    if url:
        lines.append(f"Profile JSON: {url}")
    _reply(bot, msg, "\n".join(lines))


async def _handle_achievements(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Achievements are room-scoped. Use this from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    if len(args) > 1 and args[1].lower() in {"list", "all", "catalog"}:
        target = args[2] if len(args) > 2 else sender_jid
        _jid, player = _find_player(room, target)
        unlocked = set(player.get("achievements", []) if isinstance(player, dict) else [])
        lines = [
            f"{'✅' if key in unlocked else '▫️'} {key}: {title} — {description}"
            for key, title, description in (
                (item['key'], item['title'], item['description']) for item in _achievement_catalog()
            )
        ]
        _reply(bot, msg, "🏅 IdleRPG achievement catalog\n" + "\n".join(lines))
        return
    target = args[1] if len(args) > 1 else sender_jid
    jid, player = _find_player(room, target)
    if not player:
        _reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return
    player = _normalize_player(str(jid), player)
    lines = []
    for key in player.get("achievements", []):
        lines.append(f"• {_achievement_title(key)} — {_achievement_description(key)}")
    if not lines:
        lines = ["No achievements yet. Use `" + _command_prefix(bot) + "idlerpg achievements list` to show all available achievements."]
    _reply(bot, msg, f"🏅 Achievements for {_display_player(player)}\n" + "\n".join(lines))


async def _handle_title(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Titles are room-scoped. Use this from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    _jid, player = _find_player(room, sender_jid)
    if not player:
        _reply(bot, msg, "❌ You do not have an IdleRPG character here yet.")
        return
    player = _normalize_player(sender_jid, player)
    achievements = set(player.get("achievements", []))
    if len(args) < 2 or args[1].lower() in {"list", "show"}:
        lines = [f"{key}: {_achievement_title(key)}" for key in sorted(achievements)] or ["No unlocked titles yet."]
        _reply(bot, msg, "🎖️ Available titles\n" + "\n".join(lines))
        return
    requested = args[1].lower()
    if requested in {"none", "clear", "off"}:
        player["title"] = ""
        await _set_data(bot, data)
        _reply(bot, msg, f"✅ {_display_player(player)} cleared their title.")
        return
    if requested not in achievements:
        _reply(bot, msg, f"❌ You have not unlocked that achievement title. Use `{_command_prefix(bot)}idlerpg title list`.")
        return
    player["title"] = requested
    await _set_data(bot, data)
    _reply(bot, msg, f"✅ {_display_player(player)} now uses title: {_achievement_title(requested)}.")


async def _handle_events(bot, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Events are room-scoped. Use this from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    events = list(reversed(_room_events(room)))
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
        page_size=PAGE_SIZE,
        command_hint=f"{_command_prefix(bot)}idlerpg events",
    )
    _reply(bot, msg, "\n".join(out))


async def _handle_stats(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ IdleRPG stats are room-scoped. Use this from a game room or MUC PM.")
        return
    if not await _sender_can_manage_room(bot, sender_jid, room_jid):
        _reply(bot, msg, "⛔ Only room owners/admins can inspect IdleRPG stats.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    ranked = _ranked_players(room)
    events = _room_events(room)
    day_cutoff = _now() - 86400
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
        f"Players: {len(ranked)} ({sum(1 for jid, player in ranked if _is_player_online(room_jid, jid, player))} online)",
        f"Average level: {avg_level:.1f}",
        f"Average TTL: {_duration_clock(avg_ttl)}",
        f"Events total/exported: {len(events)}/{min(len(events), EXPORT_EVENT_LIMIT)}",
        f"Events last 24h: {len(recent)} ({kind_line})",
        f"Unique items held: {unique_count}",
        f"Current season: {season.get('id', 'unknown')}",
        f"Event retention: {EVENT_RETENTION_DAYS or 'limit-only'} days, max {EVENT_LOG_LIMIT}",
        f"Logout grace: {_duration_clock(LOGOUT_GRACE_SECONDS)}",
        f"Login announcements: {'on' if ANNOUNCE_LOGIN else 'off'}",
        f"Top announcements: {_duration_clock(ANNOUNCE_TOP_INTERVAL) if ANNOUNCE_TOP_INTERVAL > 0 else 'off'}",
        f"Topic updates: {'on' if UPDATE_ROOM_TOPIC else 'off'} ({TOPIC_CUSTOM_TEXT})",
    ]
    _reply(bot, msg, "\n".join(lines))


async def _handle_map(bot, msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Map is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    players = _ranked_players(room)
    quest = room.get("quest", {}) if isinstance(room.get("quest"), dict) else {}
    lines = _render_ascii_map(room_jid, players, quest)
    url = _public_url(_room_slug(room_jid), "map.json")
    if url:
        lines.append(f"Map JSON: {url}")
    _reply(bot, msg, "\n".join(lines))


async def _handle_hof(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Hall of fame is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    subargs = [str(arg).lower() for arg in args[1:]]
    if subargs:
        if subargs == ["clear", "confirm"]:
            if not await _sender_can_manage_room(bot, sender_jid, room_jid):
                _reply(bot, msg, "⛔ Only room owners/admins can clear the IdleRPG Hall of Fame.")
                return
            removed = len(room.get("hall_of_fame", []) if isinstance(room.get("hall_of_fame"), list) else [])
            room["hall_of_fame"] = []
            await _set_data(bot, data)
            await audit_event(bot, "idlerpg_hof_clear", actor=sender_jid, target=room_jid, details={"removed": removed})
            _reply(bot, msg, f"✅ IdleRPG Hall of Fame cleared for {room_jid}. Removed {removed} entries.")
            return
        _reply(bot, msg, f"Usage: {_command_prefix(bot)}idlerpg hof [clear confirm]")
        return
    hof = room.get("hall_of_fame", []) if isinstance(room.get("hall_of_fame"), list) else []
    lines = []
    for entry in reversed(hof[-SEASON_HOF_SIZE:]):
        champion = entry.get("champion") or "no champion"
        lines.append(f"• Season {entry.get('id', '?')}: {champion}")
    if not lines:
        lines = ["No completed seasons yet."]
    _reply(bot, msg, "🏛️ IdleRPG Hall of Fame\n" + "\n".join(lines))


async def _handle_season(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Seasons are room-scoped. Use this from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    subcmd = args[1].lower() if len(args) > 1 else "status"
    if subcmd in {"end", "finish", "reset"}:
        if not await _sender_can_manage_room(bot, sender_jid, room_jid):
            _reply(bot, msg, "⛔ Only room owners/admins can end IdleRPG seasons.")
            return
        reset_players = subcmd == "reset"
        snapshot = _end_season(room_jid, room, reset_players=reset_players)
        await _set_data(bot, data)
        _reply(
            bot,
            msg,
            f"🏁 Season {snapshot.get('id')} ended. Champion: {snapshot.get('champion') or 'no champion'}. "
            f"New season: {room['season']['id']}." + (" Players were reset." if reset_players else ""),
        )
        return
    if subcmd in {"extend", "clear-end"}:
        if not await _sender_can_manage_room(bot, sender_jid, room_jid):
            _reply(bot, msg, "⛔ Only room owners/admins can change IdleRPG season timing.")
            return
        season = room.get("season", {}) if isinstance(room.get("season"), dict) else _blank_season(_now())
        room["season"] = season
        if subcmd == "clear-end":
            season["ends_at"] = 0
            await _set_data(bot, data)
            await audit_event(bot, "idlerpg_season_clear_end", actor=sender_jid, target=room_jid, details={"season_id": season.get("id")})
            _reply(bot, msg, f"✅ IdleRPG season {season.get('id', 'unknown')} is now manual/endless.")
            return
        duration_arg = args[2].lower() if len(args) > 2 else ""
        if duration_arg in {"", "config", "default"}:
            amount = _season_duration_seconds()
            if amount <= 0:
                season["ends_at"] = 0
                await _set_data(bot, data)
                await audit_event(bot, "idlerpg_season_extend", actor=sender_jid, target=room_jid, details={"season_id": season.get("id"), "duration": 0})
                _reply(bot, msg, f"✅ IdleRPG season {season.get('id', 'unknown')} is now manual/endless.")
                return
        elif duration_arg in {"0", "manual", "endless", "forever", "clear", "none"}:
            amount = 0
        else:
            amount = _core.parse_duration(duration_arg)
            if amount is None:
                _reply(bot, msg, f"Usage: {_command_prefix(bot)}idlerpg season extend [duration|manual]")
                return
        if amount <= 0:
            season["ends_at"] = 0
            action = "manual/endless"
        else:
            base = max(int(season.get("ends_at", 0) or 0), _now())
            season["ends_at"] = base + int(amount)
            action = f"extended by {_duration(amount)}"
        await _set_data(bot, data)
        await audit_event(bot, "idlerpg_season_extend", actor=sender_jid, target=room_jid, details={"season_id": season.get("id"), "duration": int(amount)})
        _reply(bot, msg, f"✅ IdleRPG season {season.get('id', 'unknown')} {action}. Ends in {_season_end_summary(season)}.")
        return
    if subcmd in {"hof", "hall", "hall-of-fame"}:
        await _handle_hof(bot, sender_jid, ["hof", *args[2:]], msg, is_room)
        return
    season = room.get("season", {}) if isinstance(room.get("season"), dict) else _blank_season(_now())
    remaining = _season_end_summary(season)
    _reply(
        bot,
        msg,
        f"🏁 Current season: {season.get('id', 'unknown')} — ends in {remaining}. "
        f"Hall of fame entries: {len(room.get('hall_of_fame', []) if isinstance(room.get('hall_of_fame'), list) else [])}.",
    )


async def _handle_announce_top(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Top announcements are room-scoped. Use it from a game room or MUC PM.")
        return
    if not await _sender_can_manage_room(bot, sender_jid, room_jid):
        _reply(bot, msg, "⛔ Only room owners/admins can announce IdleRPG top players.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    for line in _format_top_lines(room, limit=ANNOUNCE_TOP_LIMIT):
        _system_reply(bot, room_jid, line)
    room["next_top_announce_at"] = _now() + ANNOUNCE_TOP_INTERVAL if ANNOUNCE_TOP_INTERVAL > 0 else 0
    await _set_data(bot, data)
    _reply(bot, msg, "✅ IdleRPG top players announced.")


async def _handle_topic_update(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Topic updates are room-scoped. Use it from a game room or MUC PM.")
        return
    if not await _sender_can_manage_room(bot, sender_jid, room_jid):
        _reply(bot, msg, "⛔ Only room owners/admins can update the IdleRPG topic.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    custom_text = " ".join(str(part) for part in args[2:]).strip() if len(args) > 2 else None
    _maybe_set_room_topic(bot, room_jid, room, custom_text=custom_text, force=True)
    room["next_topic_update_at"] = _now() + TOPIC_UPDATE_INTERVAL if TOPIC_UPDATE_INTERVAL > 0 else 0
    await _set_data(bot, data)
    preview = _topic_text(room, custom_text=custom_text)[:250]
    _reply(bot, msg, f"✅ IdleRPG room topic update requested: {preview}")


async def _handle_export(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Export is room-scoped. Use it from a game room or MUC PM.")
        return
    if not await _sender_can_manage_room(bot, sender_jid, room_jid):
        _reply(bot, msg, "⛔ Only room owners/admins can refresh IdleRPG exports.")
        return
    data = await _get_data(bot)
    _export_public_state(data)
    root = _export_root()
    _reply(bot, msg, f"📤 IdleRPG export refreshed for {room_jid}: {root / _room_slug(room_jid)}")


async def _handle_remove_me(bot, sender_jid: str, msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ remove-me is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    _jid, player = _find_player(room, sender_jid)
    if not player:
        _reply(bot, msg, "❌ You do not have an IdleRPG character here.")
        return
    name = _display_player(player)
    room.get("players", {}).pop(sender_jid, None)
    _rebuild_name_index(room)
    await _set_data(bot, data)
    await audit_event(bot, "idlerpg_remove_me", actor=sender_jid, target=room_jid, details={"name": name})
    _reply(bot, msg, f"🗑️ IdleRPG character {name} removed.")


async def _handle_admin(bot, sender_jid: str, args: list[str], msg, is_room: bool) -> bool:
    subcmd = args[0].lower() if args else ""
    if subcmd not in {"push", "setlevel", "reset", "delete", "remove"}:
        return False
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Admin actions are room-scoped. Use them from a game room or MUC PM.")
        return True
    if not await _sender_can_manage_room(bot, sender_jid, room_jid):
        _reply(bot, msg, "⛔ Only room owners/admins can use this IdleRPG admin command.")
        return True
    if len(args) < 2:
        _reply(bot, msg, f"Usage: {_command_prefix(bot)}idlerpg {subcmd} <character> [...]")
        return True
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    jid, player = _find_player(room, args[1])
    if not player or not jid:
        _reply(bot, msg, "❌ No such IdleRPG character in this room.")
        return True
    name = _display_player(player)
    if subcmd == "push":
        if len(args) < 3:
            _reply(bot, msg, f"Usage: {_command_prefix(bot)}idlerpg push <character> <duration>")
            return True
        amount = _core.parse_duration(args[2])
        if amount is None:
            _reply(bot, msg, "❌ Invalid duration. Example: 10m, 1h30m, 2d")
            return True
        changed = _remove_time(player, amount)
        text = (
            f"✅ Pushed {name} {_duration_clock(changed)} toward next level. "
            + _next_level_line(player)
        )
    elif subcmd == "setlevel":
        if len(args) < 3 or not str(args[2]).isdigit():
            _reply(bot, msg, f"Usage: {_command_prefix(bot)}idlerpg setlevel <character> <level>")
            return True
        player["level"] = max(0, int(args[2]))
        player["next"] = _ttl_for_level(player["level"])
        _check_level_achievements(player, room)
        text = f"✅ Set {name} to level {player['level']}. " + _next_level_line(player)
    elif subcmd == "reset":
        player["level"] = 0
        player["next"] = _ttl_for_level(0)
        player["idled"] = 0
        player["items"] = {item: 0 for item in ITEMS}
        player["penalties"] = {}
        text = f"✅ Reset {name}. " + _next_level_line(player)
    else:
        room.get("players", {}).pop(str(jid), None)
        _rebuild_name_index(room)
        text = f"🗑️ Deleted IdleRPG character {name}."
    await _set_data(bot, data)
    await audit_event(bot, f"idlerpg_{subcmd}", actor=sender_jid, target=room_jid, details={"character": name})
    _reply(bot, msg, text)
    return True


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
            store_getter=get_idlerpg_store,
            key=IDLERPG_ENABLED_KEY,
            label="IdleRPG",
            log_prefix="[IDLERPG]",
        )
        if handled_toggle:
            await _sync_tasks_to_enabled_rooms(bot)
            return

    if not args:
        _reply(bot, msg, _usage(bot))
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
        _reply(bot, msg, _usage(bot))
    else:
        _reply(bot, msg, f"❌ Unknown IdleRPG command: {subcmd}\n" + _usage(bot))


async def on_message(bot, msg):
    try:
        body = str(msg.get("body", "") or "").strip()
        if not body or msg.get("type") != "groupchat":
            return
        room_jid = str(msg["from"].bare)
        if not await _core._is_enabled_for_room(bot, IDLERPG_ENABLED_KEY, PLUGIN_NAME, room_jid):
            return
        bot_nick = getattr(getattr(bot, "presence", None), "joined_rooms", {}).get(room_jid)
        actor_nick = msg.get("mucnick") or getattr(msg["from"], "resource", None)
        if bot_nick and actor_nick and str(bot_nick).lower() == str(actor_nick).lower():
            return
        if not COUNT_COMMAND_MESSAGES and body.startswith(_command_prefix(bot)):
            return
        sender_jid, _, _ = await _core.get_real_jid(bot, msg)
        if not sender_jid:
            return
        await _penalize_player(
            bot,
            room_jid,
            str(sender_jid),
            "message",
            max(1, len(body)) * MESSAGE_PENALTY,
            announce=False,
        )
    except Exception:
        log.exception("[IDLERPG] Error in on_message")


async def on_muc_presence(bot, pres):
    try:
        room_jid = str(pres["from"].bare)
        if not await _core._is_enabled_for_room(bot, IDLERPG_ENABLED_KEY, PLUGIN_NAME, room_jid):
            return
        await _ensure_game_task(bot, room_jid)
    except Exception:
        log.debug("[IDLERPG] Presence handling failed", exc_info=True)
