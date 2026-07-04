"""
IdleRPG plugin for XMPP MUCs.

This is inspired by the classic IRC IdleRPG idea: players level up by staying
online and idle. Talking in the game room adds time to the player's timer.

Commands:
    {prefix}idlerpg on|off|enabled
    {prefix}idlerpg register <character> <class>
    {prefix}idlerpg login|logout
    {prefix}idlerpg status [character]
    {prefix}idlerpg whoami
    {prefix}idlerpg top [page|last|all]
    {prefix}idlerpg players [page|last|all]
    {prefix}idlerpg items [character]
    {prefix}idlerpg profile [character]
    {prefix}idlerpg achievements [character]
    {prefix}idlerpg title <achievement|none>
    {prefix}idlerpg map
    {prefix}idlerpg hof
    {prefix}idlerpg season [status|end|reset|hof]
    {prefix}idlerpg align <good|neutral|evil>
    {prefix}idlerpg quest
    {prefix}idlerpg remove-me

Admin commands:
    {prefix}idlerpg push <character> <duration>
    {prefix}idlerpg setlevel <character> <level>
    {prefix}idlerpg reset <character>
    {prefix}idlerpg delete <character>
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from pathlib import Path
from functools import partial
from typing import Any

from utils.audit import audit_event
from utils.command import Role, command
from utils.config import BASE_DIR, config
from utils.formatting import format_page, parse_page_args
from utils.task_supervisor import create_plugin_task
from core_plugins import _core
from core_plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "idlerpg",
    "version": "1.0.0",
    "description": "IdleRPG game for MUCs, inspired by the classic IRC game",
    "category": "fun",
    "requires": ["rooms", "_core"],
}

IDLERPG_ENABLED_KEY = "IDLERPG"
IDLERPG_DATA_KEY = "IDLERPG_DATA"
PLUGIN_NAME = "idlerpg"

_cfg = config.get("idlerpg", {}) if isinstance(config.get("idlerpg", {}), dict) else {}

TICK_SECONDS = int(_cfg.get("tick_seconds", config.get("idlerpg_tick_seconds", 60)) or 60)
RP_BASE = int(_cfg.get("rp_base", config.get("idlerpg_rp_base", 600)) or 600)
RP_STEP = float(_cfg.get("rp_step", config.get("idlerpg_rp_step", 1.16)) or 1.16)
PENALTY_STEP = float(
    _cfg.get("penalty_step", config.get("idlerpg_penalty_step", 1.14)) or 1.14
)
MESSAGE_PENALTY = int(
    _cfg.get("message_penalty", config.get("idlerpg_message_penalty", 1)) or 1
)
LOGOUT_PENALTY = int(
    _cfg.get("logout_penalty", config.get("idlerpg_logout_penalty", 20)) or 20
)
MAX_PENALTY = int(_cfg.get("max_penalty", config.get("idlerpg_max_penalty", 604800)) or 0)
PAGE_SIZE = int(_cfg.get("page_size", config.get("idlerpg_page_size", 10)) or 10)
MAP_X = int(_cfg.get("map_x", config.get("idlerpg_map_x", 500)) or 500)
MAP_Y = int(_cfg.get("map_y", config.get("idlerpg_map_y", 500)) or 500)
QUEST_MIN_LEVEL = int(
    _cfg.get("quest_min_level", config.get("idlerpg_quest_min_level", 40)) or 40
)
QUEST_INTERVAL = int(
    _cfg.get("quest_interval", config.get("idlerpg_quest_interval", 21600)) or 21600
)
QUEST_MIN_DURATION = int(
    _cfg.get("quest_min_duration", config.get("idlerpg_quest_min_duration", 43200)) or 43200
)
QUEST_MAX_DURATION = int(
    _cfg.get("quest_max_duration", config.get("idlerpg_quest_max_duration", 86400)) or 86400
)
EVENT_CHANCE = float(
    _cfg.get("event_chance", config.get("idlerpg_event_chance", 0.01)) or 0.01
)
ITEM_CHANCE = float(
    _cfg.get("item_chance", config.get("idlerpg_item_chance", 0.20)) or 0.20
)
BATTLE_EVENT_WEIGHT = float(
    _cfg.get("battle_event_weight", config.get("idlerpg_battle_event_weight", 0.55)) or 0.55
)
ITEM_EVENT_WEIGHT = float(
    _cfg.get("item_event_weight", config.get("idlerpg_item_event_weight", 0.15)) or 0.15
)
ALIGNMENT_EVENT_WEIGHT = float(
    _cfg.get("alignment_event_weight", config.get("idlerpg_alignment_event_weight", 0.10)) or 0.10
)
CRITICAL_STRIKE_CHANCE = float(
    _cfg.get("critical_strike_chance", config.get("idlerpg_critical_strike_chance", 0.10)) or 0.10
)
ITEM_DROP_CHANCE = float(
    _cfg.get("item_drop_chance", config.get("idlerpg_item_drop_chance", 0.12)) or 0.12
)
EXPORT_ENABLED = bool(_cfg.get("export_enabled", config.get("idlerpg_export_enabled", True)))
EXPORT_PATH = str(_cfg.get("export_path", config.get("idlerpg_export_path", "data/idlerpg")) or "data/idlerpg")
EXPORT_PUBLIC_BASE_URL = str(_cfg.get("export_public_base_url", config.get("idlerpg_export_public_base_url", "")) or "").rstrip("/")
EXPORT_TOP_LIMIT = int(_cfg.get("export_top_limit", config.get("idlerpg_export_top_limit", 50)) or 50)
SEASON_ENABLED = bool(_cfg.get("season_enabled", config.get("idlerpg_season_enabled", False)))
SEASON_DURATION_DAYS = int(_cfg.get("season_duration_days", config.get("idlerpg_season_duration_days", 90)) or 0)
SEASON_RESET_ON_ROLLOVER = bool(_cfg.get("season_reset_on_rollover", config.get("idlerpg_season_reset_on_rollover", False)))
SEASON_HOF_SIZE = int(_cfg.get("season_hof_size", config.get("idlerpg_season_hof_size", 10)) or 10)
MAP_STEP_PER_TICK = int(_cfg.get("map_step_per_tick", config.get("idlerpg_map_step_per_tick", 5)) or 0)
COUNT_COMMAND_MESSAGES = bool(
    _cfg.get("count_command_messages", config.get("idlerpg_count_command_messages", False))
)

ROOM_TASKS: dict[str, asyncio.Task] = {}

ACHIEVEMENTS = {
    "founder": ("Founder", "registered an IdleRPG character"),
    "level_10": ("Novice Idler", "reached level 10"),
    "level_25": ("Seasoned Idler", "reached level 25"),
    "level_50": ("Ancient Idler", "reached level 50"),
    "battle_winner": ("Duelist", "won a random battle"),
    "critical_striker": ("Critical Striker", "landed a critical strike"),
    "quester": ("Quest Chosen", "was chosen for a quest"),
    "quest_hero": ("Quest Hero", "completed a quest"),
    "lucky": ("Blessed", "received a godsend"),
    "unlucky": ("Cursed", "suffered a calamity"),
    "collector": ("Collector", "collected at least 100 total item levels"),
}

ITEMS = (
    "ring",
    "amulet",
    "charm",
    "weapon",
    "helm",
    "tunic",
    "pair of gloves",
    "shield",
    "set of leggings",
    "pair of boots",
)

CALAMITIES = (
    "was bitten by a rabid cow",
    "fell into a hole",
    "ate a poisonous fruit",
    "was struck by lightning",
    "got lost in the woods",
    "walked face-first into a tree",
    "was caught in a terrible snowstorm",
)

GODSENDS = (
    "found a one-time-use spell of quickness",
    "discovered a secret underground passage",
    "was taught to run quickly by a secret tribe",
    "tamed a wild horse",
    "drank from a magic stream",
    "found a faster pair of boots",
    "caught a unicorn",
)

QUEST_TEXTS = (
    "locate the ancient tomes of the forgotten prophet",
    "guard the secret passage until the full moon has passed",
    "rescue the beautiful princess from a terrible beast",
    "destroy the bandits terrorizing the mountain roads",
    "map the dark lands beyond the eastern hills",
    "return the stolen relics to the city temple",
)

_ALIGNMENT_NAMES = {"g": "good", "n": "neutral", "e": "evil"}


def _command_prefix(bot=None) -> str:
    return str(getattr(bot, "prefix", None) or config.get("prefix", ",") or ",")


async def get_idlerpg_store(bot):
    return bot.db.users.plugin(PLUGIN_NAME)


def _reply(bot, msg, text: str):
    bot.reply(msg, text, mention=False, thread=True)


def _system_room_message(room_jid: str) -> dict[str, Any]:
    return {
        "from": type("From", (), {"bare": room_jid, "resource": None})(),
        "type": "groupchat",
    }


def _system_reply(bot, room_jid: str, text: str):
    bot.reply(
        _system_room_message(room_jid),
        text,
        mention=False,
        thread=True,
        rate_limit=False,
        ephemeral=False,
    )


def _now() -> int:
    return int(time.time())


def _duration(seconds: int | float | None) -> str:
    seconds = max(0, int(seconds or 0))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _duration_clock(seconds: int | float | None) -> str:
    seconds = max(0, int(seconds or 0))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{days} days, {hours:02d}:{minutes:02d}:{secs:02d}"


def _possessive(name: str) -> str:
    return f"{name}'" if str(name).endswith("s") else f"{name}'s"


def _next_level_line(player: dict[str, Any]) -> str:
    return f"{_display_player(player)} reaches next level in {_duration_clock(player.get('next', 0))}."


def _add_time(player: dict[str, Any], amount: int | float) -> int:
    amount = max(0, int(amount or 0))
    player["next"] = max(0, int(player.get("next", 0) or 0)) + amount
    return amount


def _remove_time(player: dict[str, Any], amount: int | float) -> int:
    amount = max(0, int(amount or 0))
    current = max(0, int(player.get("next", 0) or 0))
    removed = min(current, amount)
    player["next"] = current - removed
    return removed


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "", str(value or "").strip())[:30]


def _safe_class(value: str) -> str:
    clean = re.sub(r"[\x00-\x1f\x7f]", "", str(value or "").strip())
    clean = re.sub(r"\s+", " ", clean)
    return clean[:40]


def _ttl_for_level(level: int) -> int:
    return max(1, int(RP_BASE * (RP_STEP ** max(0, int(level)))))


def _penalty_for(level: int, base: int) -> int:
    value = max(0, int(base * (PENALTY_STEP ** max(0, int(level)))))
    if MAX_PENALTY and value > MAX_PENALTY:
        return MAX_PENALTY
    return value


def _display_player(player: dict[str, Any]) -> str:
    return str(player.get("name") or "unknown")


def _alignment_name(value: str | None) -> str:
    return _ALIGNMENT_NAMES.get(str(value or "n")[:1].lower(), "neutral")


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-._")
    return slug[:80] or "idlerpg"


def _room_slug(room_jid: str) -> str:
    return _slug(room_jid.replace("@", "_at_"))


def _export_root() -> Path:
    path = Path(EXPORT_PATH)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _season_id(ts: int | None = None) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(int(ts or _now())))


def _season_duration_seconds() -> int:
    return max(0, int(SEASON_DURATION_DAYS) * 86400)


def _award(player: dict[str, Any], achievement: str) -> bool:
    if achievement not in ACHIEVEMENTS:
        return False
    current = player.setdefault("achievements", [])
    if not isinstance(current, list):
        current = []
        player["achievements"] = current
    if achievement in current:
        return False
    current.append(achievement)
    current.sort()
    return True


def _achievement_title(achievement: str) -> str:
    return ACHIEVEMENTS.get(achievement, (achievement, ""))[0]


def _achievement_description(achievement: str) -> str:
    return ACHIEVEMENTS.get(achievement, (achievement, ""))[1]


def _display_title(player: dict[str, Any]) -> str:
    title = str(player.get("title") or "").strip()
    achievements = player.get("achievements")
    if title and isinstance(achievements, list) and title in achievements:
        return _achievement_title(title)
    return ""


def _display_character(player: dict[str, Any]) -> str:
    title = _display_title(player)
    name = _display_player(player)
    return f"{name}, {title}" if title else name


def _check_level_achievements(player: dict[str, Any]) -> None:
    level = int(player.get("level", 0) or 0)
    if level >= 10:
        _award(player, "level_10")
    if level >= 25:
        _award(player, "level_25")
    if level >= 50:
        _award(player, "level_50")
    if _item_sum(player) >= 100:
        _award(player, "collector")


def _move_player(player: dict[str, Any], steps: int = 1) -> None:
    if MAP_STEP_PER_TICK <= 0:
        return
    steps = max(1, min(24, int(steps or 1)))
    for _ in range(steps):
        player["x"] = (int(player.get("x", 0) or 0) + random.randint(-MAP_STEP_PER_TICK, MAP_STEP_PER_TICK)) % max(1, MAP_X + 1)
        player["y"] = (int(player.get("y", 0) or 0) + random.randint(-MAP_STEP_PER_TICK, MAP_STEP_PER_TICK)) % max(1, MAP_Y + 1)


def _blank_season(now: int | None = None) -> dict[str, Any]:
    now = int(now or _now())
    duration = _season_duration_seconds()
    return {
        "id": _season_id(now),
        "started_at": now,
        "ends_at": now + duration if duration else 0,
    }


def _blank_room() -> dict[str, Any]:
    now = _now()
    return {
        "players": {},
        "name_index": {},
        "quest": {"active": False, "next_at": now + QUEST_INTERVAL},
        "season": _blank_season(now),
        "hall_of_fame": [],
        "last_tick": now,
        "created_at": now,
    }


async def _get_data(bot) -> dict[str, Any]:
    store = await get_idlerpg_store(bot)
    data = await store.get_global(IDLERPG_DATA_KEY, default={})
    return data if isinstance(data, dict) else {}


async def _set_data(bot, data: dict[str, Any]) -> None:
    store = await get_idlerpg_store(bot)
    await store.set_global(IDLERPG_DATA_KEY, data)
    _export_public_state(data)


def _room_bucket(data: dict[str, Any], room_jid: str) -> dict[str, Any]:
    rooms = data.setdefault("rooms", {})
    if not isinstance(rooms, dict):
        rooms = {}
        data["rooms"] = rooms
    room = rooms.setdefault(room_jid, _blank_room())
    if not isinstance(room, dict):
        room = _blank_room()
        rooms[room_jid] = room
    room.setdefault("players", {})
    room.setdefault("name_index", {})
    room.setdefault("quest", {"active": False, "next_at": _now() + QUEST_INTERVAL})
    room.setdefault("season", _blank_season(_now()))
    room.setdefault("hall_of_fame", [])
    room.setdefault("last_tick", _now())
    return room


def _normalize_player(jid: str, player: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    items = player.get("items")
    if not isinstance(items, dict):
        items = {}
    for item in ITEMS:
        try:
            items[item] = int(items.get(item, 0) or 0)
        except (TypeError, ValueError):
            items[item] = 0

    penalties = player.get("penalties")
    if not isinstance(penalties, dict):
        penalties = {}

    try:
        level = int(player.get("level", 0) or 0)
    except (TypeError, ValueError):
        level = 0

    try:
        ttl = int(player.get("next", _ttl_for_level(level)) or 0)
    except (TypeError, ValueError):
        ttl = _ttl_for_level(level)

    achievements = player.get("achievements")
    if not isinstance(achievements, list):
        achievements = []
    achievements = sorted({str(value) for value in achievements if str(value) in ACHIEVEMENTS})
    title = str(player.get("title") or "")
    if title not in achievements:
        title = ""

    player.update({
        "jid": str(player.get("jid") or jid),
        "name": _safe_name(str(player.get("name") or jid.split("@", 1)[0])) or "player",
        "class": _safe_class(str(player.get("class") or "idler")) or "idler",
        "level": max(0, level),
        "next": max(0, ttl),
        "idled": int(player.get("idled", 0) or 0),
        "created_at": int(player.get("created_at", now) or now),
        "last_login": int(player.get("last_login", now) or now),
        "last_seen": int(player.get("last_seen", now) or now),
        "alignment": str(player.get("alignment") or "n")[:1].lower(),
        "items": items,
        "penalties": penalties,
        "achievements": achievements,
        "title": title,
        "x": int(player.get("x", random.randint(0, MAP_X)) or 0),
        "y": int(player.get("y", random.randint(0, MAP_Y)) or 0),
        "logged_out": bool(player.get("logged_out", False)),
    })
    _check_level_achievements(player)
    if player["alignment"] not in {"g", "n", "e"}:
        player["alignment"] = "n"
    player["x"] %= max(1, MAP_X + 1)
    player["y"] %= max(1, MAP_Y + 1)
    return player


def _rebuild_name_index(room: dict[str, Any]) -> dict[str, str]:
    players = room.get("players", {})
    index: dict[str, str] = {}
    for jid, player in players.items():
        if isinstance(player, dict):
            name = str(player.get("name") or "").lower()
            if name:
                index[name] = str(jid)
    room["name_index"] = index
    return index


def _find_player(room: dict[str, Any], name_or_jid: str | None) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    if not name_or_jid:
        return None, None
    players = room.get("players", {})
    value = str(name_or_jid).strip()
    if value in players and isinstance(players[value], dict):
        return value, players[value]
    index = room.get("name_index")
    if not isinstance(index, dict):
        index = _rebuild_name_index(room)
    jid = index.get(value.lower())
    if jid and isinstance(players.get(jid), dict):
        return jid, players[jid]
    return None, None


def _online_jids(room_jid: str) -> set[str]:
    room = JOINED_ROOMS.get(room_jid, {})
    nicks = room.get("nicks", {}) if isinstance(room, dict) else {}
    result: set[str] = set()
    if not isinstance(nicks, dict):
        return result
    for info in nicks.values():
        if isinstance(info, dict) and info.get("jid"):
            result.add(str(info["jid"]).split("/", 1)[0])
    return result


def _is_player_online(room_jid: str, jid: str, player: dict[str, Any]) -> bool:
    return not bool(player.get("logged_out")) and str(jid) in _online_jids(room_jid)


def _format_player_status(room_jid: str, jid: str, player: dict[str, Any]) -> str:
    online = "online" if _is_player_online(room_jid, jid, player) else "offline"
    title = _display_title(player)
    title_part = f" [{title}]" if title else ""
    return (
        f"{_display_player(player)}{title_part}, the level {player.get('level', 0)} "
        f"{player.get('class', 'idler')} ({_alignment_name(player.get('alignment'))}); "
        f"Status: {online}; TTL: {_duration(player.get('next', 0))}; "
        f"Idled: {_duration(player.get('idled', 0))}; "
        f"Map: [{player.get('x', 0)},{player.get('y', 0)}]; "
        f"Achievements: {len(player.get('achievements', []) if isinstance(player.get('achievements'), list) else [])}; "
        f"Item sum: {sum(int(v or 0) for v in player.get('items', {}).values())}"
    )


def _item_sum(player: dict[str, Any]) -> int:
    items = player.get("items", {})
    if not isinstance(items, dict):
        return 0
    total = 0
    for value in items.values():
        try:
            total += max(0, int(value or 0))
        except (TypeError, ValueError):
            continue
    return total


def _battle_power(player: dict[str, Any]) -> int:
    level = max(0, int(player.get("level", 0) or 0))
    return max(1, level * 10 + _item_sum(player) + 1)


def _ranked_players(room: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    players = [
        (str(jid), _normalize_player(str(jid), player))
        for jid, player in room.get("players", {}).items()
        if isinstance(player, dict)
    ]
    players.sort(
        key=lambda item: (
            -int(item[1].get("level", 0) or 0),
            int(item[1].get("next", 0) or 0),
            str(item[1].get("name", "")).lower(),
        )
    )
    return players


def _player_public_record(room_jid: str, jid: str, player: dict[str, Any], rank: int | None = None) -> dict[str, Any]:
    title_key = str(player.get("title") or "")
    return {
        "rank": rank,
        "jid_hash": hashlib.sha256(str(jid).encode("utf-8")).hexdigest()[:16],
        "name": _display_player(player),
        "character": _display_player(player),
        "class": str(player.get("class") or "idler"),
        "title": _achievement_title(title_key) if title_key else "",
        "title_key": title_key,
        "level": int(player.get("level", 0) or 0),
        "ttl": int(player.get("next", 0) or 0),
        "time_to_level": int(player.get("next", 0) or 0),
        "alignment": _alignment_name(player.get("alignment")),
        "idled": int(player.get("idled", 0) or 0),
        "item_sum": _item_sum(player),
        "items": dict(player.get("items", {}) if isinstance(player.get("items"), dict) else {}),
        "achievements": [
            {"key": key, "title": _achievement_title(key), "description": _achievement_description(key)}
            for key in player.get("achievements", [])
            if key in ACHIEVEMENTS
        ],
        "x": int(player.get("x", 0) or 0),
        "y": int(player.get("y", 0) or 0),
        "online": _is_player_online(room_jid, str(jid), player),
        "logged_out": bool(player.get("logged_out", False)),
        "created_at": int(player.get("created_at", 0) or 0),
        "last_seen": int(player.get("last_seen", 0) or 0),
    }


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _public_url(*parts: str) -> str:
    if not EXPORT_PUBLIC_BASE_URL:
        return ""
    return "/".join([EXPORT_PUBLIC_BASE_URL, *[part.strip("/") for part in parts if part]])


def _profile_url(room_jid: str, player: dict[str, Any]) -> str:
    return _public_url(_room_slug(room_jid), "profiles", f"{_slug(_display_player(player))}.json")


def _export_room_state(root: Path, room_jid: str, room: dict[str, Any], generated_at: int) -> dict[str, Any]:
    slug = _room_slug(room_jid)
    room_dir = root / slug
    ranked = _ranked_players(room)
    leaderboard = [
        _player_public_record(room_jid, jid, player, rank=rank)
        for rank, (jid, player) in enumerate(ranked[:EXPORT_TOP_LIMIT], start=1)
    ]
    all_profiles = [
        _player_public_record(room_jid, jid, player, rank=rank)
        for rank, (jid, player) in enumerate(ranked, start=1)
    ]
    quest = room.get("quest", {}) if isinstance(room.get("quest"), dict) else {}
    active_quest = None
    if quest.get("active"):
        active_quest = {
            "text": quest.get("text", "adventure"),
            "started_at": int(quest.get("started_at", 0) or 0),
            "complete_at": int(quest.get("complete_at", 0) or 0),
            "route": quest.get("route", []),
            "questers": [
                _display_player(room.get("players", {}).get(jid, {"name": jid}))
                for jid in quest.get("questers", [])
            ],
        }
    season = room.get("season", {}) if isinstance(room.get("season"), dict) else {}
    hall_of_fame = room.get("hall_of_fame", []) if isinstance(room.get("hall_of_fame"), list) else []
    room_payload = {
        "generated_at": generated_at,
        "room": room_jid,
        "slug": slug,
        "map": {"width": MAP_X, "height": MAP_Y},
        "season": season,
        "players_total": len(all_profiles),
        "players_online": sum(1 for player in all_profiles if player["online"]),
        "leaderboard": leaderboard,
        "players": all_profiles,
        "quest": active_quest,
        "hall_of_fame": hall_of_fame[-SEASON_HOF_SIZE:],
    }
    _atomic_write_json(room_dir / "room.json", room_payload)
    _atomic_write_json(room_dir / "leaderboard.json", {"generated_at": generated_at, "room": room_jid, "players": leaderboard})
    _atomic_write_json(room_dir / "players.json", {"generated_at": generated_at, "room": room_jid, "players": all_profiles})
    _atomic_write_json(room_dir / "map.json", {
        "generated_at": generated_at,
        "room": room_jid,
        "width": MAP_X,
        "height": MAP_Y,
        "players": all_profiles,
        "quest": active_quest,
    })
    _atomic_write_json(room_dir / "hall_of_fame.json", {"generated_at": generated_at, "room": room_jid, "seasons": hall_of_fame[-SEASON_HOF_SIZE:]})
    profiles_dir = room_dir / "profiles"
    for profile in all_profiles:
        _atomic_write_json(profiles_dir / f"{_slug(profile['name'])}.json", profile)
    return {
        "room": room_jid,
        "slug": slug,
        "players_total": len(all_profiles),
        "players_online": room_payload["players_online"],
        "leaderboard_url": _public_url(slug, "leaderboard.json"),
        "map_url": _public_url(slug, "map.json"),
    }


def _export_public_state(data: dict[str, Any]) -> None:
    if not EXPORT_ENABLED:
        return
    try:
        root = _export_root()
        generated_at = _now()
        rooms = data.get("rooms", {}) if isinstance(data, dict) else {}
        if not isinstance(rooms, dict):
            rooms = {}
        summaries: list[dict[str, Any]] = []
        default_room_payload = None
        for room_jid, room in sorted(rooms.items()):
            if not isinstance(room, dict):
                continue
            summary = _export_room_state(root, str(room_jid), room, generated_at)
            summaries.append(summary)
            if default_room_payload is None:
                room_json = root / summary["slug"] / "room.json"
                try:
                    default_room_payload = json.loads(room_json.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    default_room_payload = None
        _atomic_write_json(root / "index.json", {"generated_at": generated_at, "rooms": summaries})
        if default_room_payload:
            _atomic_write_json(root / "leaderboard.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "players": default_room_payload["leaderboard"],
            })
            _atomic_write_json(root / "map.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "width": MAP_X,
                "height": MAP_Y,
                "players": default_room_payload["players"],
                "quest": default_room_payload["quest"],
            })
            _atomic_write_json(root / "players.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "players": default_room_payload["players"],
            })
            _atomic_write_json(root / "hall_of_fame.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "seasons": default_room_payload["hall_of_fame"],
            })
    except Exception:
        log.debug("[IDLERPG] Failed to export public state", exc_info=True)


def _season_snapshot(room_jid: str, room: dict[str, Any], ended_at: int | None = None) -> dict[str, Any]:
    ended_at = int(ended_at or _now())
    season = room.get("season", {}) if isinstance(room.get("season"), dict) else _blank_season(ended_at)
    ranked = _ranked_players(room)[:SEASON_HOF_SIZE]
    return {
        "id": season.get("id") or _season_id(ended_at),
        "room": room_jid,
        "started_at": int(season.get("started_at", 0) or 0),
        "ended_at": ended_at,
        "champion": _display_player(ranked[0][1]) if ranked else "",
        "top": [
            _player_public_record(room_jid, jid, player, rank=rank)
            for rank, (jid, player) in enumerate(ranked, start=1)
        ],
    }


def _reset_player_for_new_season(player: dict[str, Any]) -> None:
    player["level"] = 0
    player["next"] = _ttl_for_level(0)
    player["idled"] = 0
    player["items"] = {item: 0 for item in ITEMS}
    player["penalties"] = {}
    player["achievements"] = []
    player["title"] = ""


def _end_season(room_jid: str, room: dict[str, Any], *, reset_players: bool | None = None) -> dict[str, Any]:
    now = _now()
    snapshot = _season_snapshot(room_jid, room, now)
    hof = room.setdefault("hall_of_fame", [])
    if not isinstance(hof, list):
        hof = []
        room["hall_of_fame"] = hof
    hof.append(snapshot)
    del hof[:-max(1, SEASON_HOF_SIZE * 5)]
    should_reset = reset_players if reset_players is not None else SEASON_RESET_ON_ROLLOVER
    if should_reset:
        for jid, player in room.get("players", {}).items():
            if isinstance(player, dict):
                _reset_player_for_new_season(_normalize_player(str(jid), player))
    room["season"] = _blank_season(now)
    return snapshot


def _maybe_rollover_season(room_jid: str, room: dict[str, Any], messages: list[str]) -> None:
    if not SEASON_ENABLED or _season_duration_seconds() <= 0:
        return
    season = room.get("season")
    if not isinstance(season, dict):
        room["season"] = _blank_season(_now())
        return
    ends_at = int(season.get("ends_at", 0) or 0)
    if ends_at <= 0 or _now() < ends_at:
        return
    snapshot = _end_season(room_jid, room)
    champion = snapshot.get("champion") or "no champion"
    messages.append(
        f"🏁 IdleRPG season {snapshot.get('id')} has ended. Champion: {champion}. "
        f"New season {room['season']['id']} has begun."
    )


def _alignment_battle_factor(player: dict[str, Any], outcome: str) -> float:
    alignment = str(player.get("alignment") or "n")[:1].lower()
    if alignment == "e" and outcome == "win":
        return 1.10
    if alignment == "g" and outcome == "loss":
        return 0.90
    if alignment == "n":
        return 0.97
    return 1.0


def _battle_amount(player: dict[str, Any], base: int, outcome: str) -> int:
    amount = _penalty_for(int(player.get("level", 0)), base)
    return max(1, int(amount * _alignment_battle_factor(player, outcome)))


def _choose_two_players(players: list[tuple[str, dict[str, Any]]]) -> tuple[tuple[str, dict[str, Any]], tuple[str, dict[str, Any]]] | None:
    if len(players) < 2:
        return None
    first = random.choice(players)
    remaining = [item for item in players if item[0] != first[0]]
    if not remaining:
        return None
    return first, random.choice(remaining)


def _room_from_context(msg, is_room: bool) -> str | None:
    if is_room and msg.get("type") == "groupchat":
        return str(msg["from"].bare)
    if msg.get("type") in ("chat", "normal"):
        room = str(getattr(msg["from"], "bare", ""))
        if room in JOINED_ROOMS and getattr(msg["from"], "resource", None):
            return room
    return None


async def _sender_can_manage_room(bot, sender_jid: str | None, room_jid: str | None) -> bool:
    if not sender_jid:
        return False
    get_role = getattr(bot, "get_user_role", None)
    if not callable(get_role):
        return False
    try:
        if room_jid:
            role = await get_role(str(sender_jid), room_jid)
        else:
            role = await get_role(str(sender_jid))
        return role <= Role.MODERATOR
    except Exception:
        log.debug("[IDLERPG] Could not resolve sender role", exc_info=True)
        return False


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
            pass


async def _enabled_rooms(bot) -> dict[str, bool]:
    store = await get_idlerpg_store(bot)
    state = await store.get_global(IDLERPG_ENABLED_KEY, default={})
    return state if isinstance(state, dict) else {}


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
        if player.get("logged_out") or str(jid) not in online_jids:
            continue
        player["next"] = max(0, int(player.get("next", 0)) - delta)
        player["idled"] = int(player.get("idled", 0)) + delta
        player["last_seen"] = now
        _move_player(player, movement_steps)
        leveled = False
        while int(player.get("next", 0)) <= 0:
            player["level"] = int(player.get("level", 0)) + 1
            player["next"] = int(player.get("next", 0)) + _ttl_for_level(player["level"])
            leveled = True
        if leveled:
            _check_level_achievements(player)
            messages.append(
                f"🏆 {_display_character(player)} has reached level {player['level']}! "
                f"Next level in {_duration_clock(player['next'])}."
            )
            if random.random() < ITEM_CHANCE:
                item = random.choice(ITEMS)
                gain = max(1, player["level"] + random.randint(0, 3))
                player["items"][item] = max(int(player["items"].get(item, 0)), gain)
                messages.append(f"✨ {_display_player(player)} found {item} level {gain}.")
    await _maybe_run_random_event(room, room_jid, messages)
    await _maybe_run_quest(room, room_jid, messages)
    await _set_data(bot, data)
    if announce:
        for text in messages[:8]:
            _system_reply(bot, room_jid, text)


async def _maybe_run_random_event(room: dict[str, Any], room_jid: str, messages: list[str]) -> None:
    players = [
        (str(jid), _normalize_player(str(jid), player))
        for jid, player in room.get("players", {}).items()
        if isinstance(player, dict) and _is_player_online(room_jid, str(jid), player)
    ]
    if not players or random.random() >= EVENT_CHANCE:
        return

    event_roll = random.random()
    if len(players) >= 2 and event_roll < BATTLE_EVENT_WEIGHT:
        _run_pvp_battle(players, messages)
        return

    event_roll -= BATTLE_EVENT_WEIGHT
    if event_roll < ITEM_EVENT_WEIGHT:
        _run_item_blessing(players, messages)
        return

    event_roll -= ITEM_EVENT_WEIGHT
    if len(players) >= 2 and event_roll < ALIGNMENT_EVENT_WEIGHT:
        if _run_alignment_bonus(players, messages):
            return

    _run_godsend_or_calamity(players, messages)


def _run_pvp_battle(players: list[tuple[str, dict[str, Any]]], messages: list[str]) -> None:
    pair = _choose_two_players(players)
    if pair is None:
        return
    (_attacker_jid, attacker), (_defender_jid, defender) = pair
    attacker_power = _battle_power(attacker)
    defender_power = _battle_power(defender)
    attacker_roll = random.randint(0, attacker_power)
    defender_roll = random.randint(0, defender_power)
    attacker_won = attacker_roll >= defender_roll
    attacker_name = _display_player(attacker)
    defender_name = _display_player(defender)
    base = random.randint(45, 150)

    if attacker_won:
        amount = _battle_amount(attacker, base, "win")
        changed = _remove_time(attacker, amount)
        messages.append(
            f"⚔️ {attacker_name} [{attacker_roll}/{attacker_power}] has challenged "
            f"{defender_name} [{defender_roll}/{defender_power}] in combat and won! "
            f"{_duration_clock(changed)} is removed from {_possessive(attacker_name)} clock."
        )
        messages.append(_next_level_line(attacker))
        winner, loser = attacker, defender
        _award(winner, "battle_winner")
    else:
        amount = _battle_amount(attacker, base, "loss")
        changed = _add_time(attacker, amount)
        messages.append(
            f"⚔️ {attacker_name} [{attacker_roll}/{attacker_power}] has challenged "
            f"{defender_name} [{defender_roll}/{defender_power}] in combat and lost! "
            f"{_duration_clock(changed)} is added to {_possessive(attacker_name)} clock."
        )
        messages.append(_next_level_line(attacker))
        winner, loser = defender, attacker
        _award(winner, "battle_winner")

    _maybe_critical_strike(winner, loser, messages)
    _maybe_battle_item_drop(winner, loser, messages)


def _maybe_critical_strike(winner: dict[str, Any], loser: dict[str, Any], messages: list[str]) -> None:
    if random.random() >= CRITICAL_STRIKE_CHANCE:
        return
    _award(winner, "critical_striker")
    winner_name = _display_player(winner)
    loser_name = _display_player(loser)
    base = random.randint(10, 75)
    amount = _battle_amount(winner, base, "win")
    changed = _add_time(loser, amount)
    loser.setdefault("penalties", {})["critical"] = (
        int(loser.get("penalties", {}).get("critical", 0) or 0) + changed
    )
    messages.append(
        f"💢 {winner_name} has dealt {loser_name} a Critical Strike! "
        f"{_duration_clock(changed)} is added to {_possessive(loser_name)} clock."
    )
    messages.append(_next_level_line(loser))


def _maybe_battle_item_drop(winner: dict[str, Any], loser: dict[str, Any], messages: list[str]) -> None:
    if random.random() >= ITEM_DROP_CHANCE:
        return
    winner_items = winner.setdefault("items", {})
    loser_items = loser.setdefault("items", {})
    candidates: list[tuple[str, int, int]] = []
    for item in ITEMS:
        try:
            winner_level = int(winner_items.get(item, 0) or 0)
            loser_level = int(loser_items.get(item, 0) or 0)
        except (TypeError, ValueError):
            continue
        if loser_level > winner_level:
            candidates.append((item, loser_level, winner_level))
    if not candidates:
        return
    item, loser_level, winner_level = random.choice(candidates)
    winner_items[item] = loser_level
    loser_items[item] = winner_level
    winner_name = _display_player(winner)
    loser_name = _display_player(loser)
    messages.append(
        f"🎒 In the fierce battle, {loser_name} dropped their level {loser_level} {item}! "
        f"{winner_name} picks it up, tossing their old level {winner_level} {item} to {loser_name}."
    )


def _run_item_blessing(players: list[tuple[str, dict[str, Any]]], messages: list[str]) -> None:
    _jid, player = random.choice(players)
    item = random.choice(ITEMS)
    items = player.setdefault("items", {})
    try:
        old_level = int(items.get(item, 0) or 0)
    except (TypeError, ValueError):
        old_level = 0
    level = max(0, int(player.get("level", 0) or 0))
    gain = max(1, old_level // 10, level // 10)
    items[item] = old_level + gain
    name = _display_player(player)
    _check_level_achievements(player)
    messages.append(
        f"✨ {name}'s {item} has been blessed by a wandering enchanter! "
        f"{_possessive(name)} {item} gains {gain} level{'s' if gain != 1 else ''}."
    )


def _run_alignment_bonus(players: list[tuple[str, dict[str, Any]]], messages: list[str]) -> bool:
    groups: dict[str, list[dict[str, Any]]] = {"g": [], "n": [], "e": []}
    for _jid, player in players:
        alignment = str(player.get("alignment") or "n")[:1].lower()
        groups.setdefault(alignment if alignment in groups else "n", []).append(player)
    candidates = [group for group in groups.values() if len(group) >= 2]
    if not candidates:
        return False
    chosen = random.choice(candidates)
    selected = random.sample(chosen, 2)
    names = [_display_player(player) for player in selected]
    alignment = _alignment_name(selected[0].get("alignment"))
    messages.append(
        f"⚖️ {names[0]} and {names[1]} feel the power of their {alignment} alignment. "
        "7% of their time is removed from their clocks."
    )
    for player in selected:
        amount = max(1, int(int(player.get("next", 0) or 0) * 0.07))
        _remove_time(player, amount)
        messages.append(_next_level_line(player))
    return True


def _run_godsend_or_calamity(players: list[tuple[str, dict[str, Any]]], messages: list[str]) -> None:
    _jid, player = random.choice(players)
    name = _display_player(player)
    level = int(player.get("level", 0) or 0)
    if random.random() < 0.5:
        amount = _penalty_for(level, random.randint(20, 80))
        changed = _add_time(player, amount)
        player.setdefault("penalties", {})["calamity"] = (
            int(player.get("penalties", {}).get("calamity", 0) or 0) + changed
        )
        _award(player, "unlucky")
        messages.append(
            f"💥 {name} {random.choice(CALAMITIES)}. This terrible calamity has slowed them "
            f"{_duration_clock(changed)} from level {level + 1}."
        )
        messages.append(_next_level_line(player))
    else:
        amount = _penalty_for(level, random.randint(20, 80))
        changed = _remove_time(player, amount)
        _award(player, "lucky")
        messages.append(
            f"🌟 {name} {random.choice(GODSENDS)}. This wondrous godsend has accelerated them "
            f"{_duration_clock(changed)} towards level {level + 1}."
        )
        messages.append(_next_level_line(player))


async def _maybe_run_quest(room: dict[str, Any], room_jid: str, messages: list[str]) -> None:
    quest = room.setdefault("quest", {"active": False, "next_at": _now() + QUEST_INTERVAL})
    now = _now()
    if not isinstance(quest, dict):
        quest = {"active": False, "next_at": now + QUEST_INTERVAL}
        room["quest"] = quest

    if quest.get("active"):
        if now < int(quest.get("complete_at", 0) or 0):
            return
        players = room.get("players", {})
        questers = [str(jid) for jid in quest.get("questers", [])]
        completed_players: list[dict[str, Any]] = []
        names: list[str] = []
        for jid in questers:
            player = players.get(jid)
            if isinstance(player, dict):
                player["next"] = int(int(player.get("next", 0)) * 0.75)
                _award(player, "quest_hero")
                names.append(_display_player(player))
                completed_players.append(player)
        if names:
            messages.append(
                f"🧭 {', '.join(names)} completed their quest! "
                "25% of their burden is removed."
            )
            for player in completed_players:
                messages.append(_next_level_line(player))
        room["quest"] = {"active": False, "next_at": now + QUEST_INTERVAL}
        return

    if now < int(quest.get("next_at", now + QUEST_INTERVAL) or 0):
        return

    candidates = [
        str(jid)
        for jid, player in room.get("players", {}).items()
        if isinstance(player, dict)
        and _is_player_online(room_jid, str(jid), player)
        and int(player.get("level", 0) or 0) >= QUEST_MIN_LEVEL
    ]
    if len(candidates) < 4:
        quest["next_at"] = now + QUEST_INTERVAL
        return
    random.shuffle(candidates)
    questers = candidates[:4]
    duration = random.randint(max(1, QUEST_MIN_DURATION), max(QUEST_MIN_DURATION, QUEST_MAX_DURATION))
    quest_text = random.choice(QUEST_TEXTS)
    route = [
        [random.randint(0, MAP_X), random.randint(0, MAP_Y)],
        [random.randint(0, MAP_X), random.randint(0, MAP_Y)],
    ]
    room["quest"] = {
        "active": True,
        "questers": questers,
        "text": quest_text,
        "started_at": now,
        "complete_at": now + duration,
        "route": route,
    }
    names = []
    for jid in questers:
        player = room["players"].get(jid)
        if isinstance(player, dict):
            _award(player, "quester")
            names.append(player.get("name", jid))
    messages.append(
        f"🧭 {', '.join(names)} have been chosen to {quest_text}. "
        f"Participants must first reach [{route[0][0]},{route[0][1]}], then [{route[1][0]},{route[1][1]}]. "
        f"Quest completes in {_duration_clock(duration)}."
    )


async def _penalize_player(
    bot,
    room_jid: str,
    jid: str,
    reason: str,
    amount: int,
    *,
    announce: bool = False,
) -> int:
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    _player_jid, player = _find_player(room, jid)
    if not player:
        return 0
    player = _normalize_player(jid, player)
    penalty = _penalty_for(int(player.get("level", 0)), amount)
    changed = _add_time(player, penalty)
    penalties = player.setdefault("penalties", {})
    penalties[reason] = int(penalties.get(reason, 0) or 0) + changed
    await _set_data(bot, data)
    if announce and changed:
        _system_reply(
            bot,
            room_jid,
            f"⏳ {_display_player(player)} is penalized {_duration_clock(changed)} for {reason}. "
            + _next_level_line(player),
        )
    return changed


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
        "penalties": {},
        "achievements": ["founder"],
        "title": "",
        "x": random.randint(0, MAP_X),
        "y": random.randint(0, MAP_Y),
        "logged_out": False,
    })
    players[sender_jid] = player
    _rebuild_name_index(room)
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
    player["logged_out"] = False
    player["last_login"] = _now()
    await _set_data(bot, data)
    await _ensure_game_task(bot, room_jid)
    _reply(bot, msg, f"✅ {_display_player(player)} is now online for IdleRPG.")


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
    player["logged_out"] = True
    penalty = _penalty_for(int(player.get("level", 0)), LOGOUT_PENALTY)
    changed = _add_time(player, penalty)
    player.setdefault("penalties", {})["logout"] = int(player.get("penalties", {}).get("logout", 0)) + changed
    await _set_data(bot, data)
    _reply(
        bot,
        msg,
        f"👋 {_display_player(player)} logged out. {_duration_clock(changed)} is added to "
        f"{_possessive(_display_player(player))} clock. "
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
    lines = [f"{name}: {level}" for name, level in sorted(player["items"].items())]
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
        f"Map: [{player.get('x', 0)},{player.get('y', 0)}]",
        f"Achievements: {len(achievements)}",
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
        lines = ["No achievements yet."]
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
        _reply(bot, msg, "❌ You have not unlocked that achievement title. Use `,idlerpg title list`.")
        return
    player["title"] = requested
    await _set_data(bot, data)
    _reply(bot, msg, f"✅ {_display_player(player)} now uses title: {_achievement_title(requested)}.")


async def _handle_map(bot, msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Map is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
    players = _ranked_players(room)
    lines = [
        f"🗺️ IdleRPG map for {room_jid}: {MAP_X}x{MAP_Y}",
    ]
    for _jid, player in players[:10]:
        lines.append(f"• {_display_player(player)} [{player.get('x', 0)},{player.get('y', 0)}] lv.{player.get('level', 0)}")
    quest = room.get("quest", {})
    if isinstance(quest, dict) and quest.get("active") and quest.get("route"):
        route = quest.get("route", [])
        lines.append(f"Quest route: {route}")
    url = _public_url(_room_slug(room_jid), "map.json")
    if url:
        lines.append(f"Map JSON: {url}")
    _reply(bot, msg, "\n".join(lines))


async def _handle_hof(bot, args: list[str], msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    if not room_jid:
        _reply(bot, msg, "ℹ️ Hall of fame is room-scoped. Use it from a game room or MUC PM.")
        return
    data = await _get_data(bot)
    room = _room_bucket(data, room_jid)
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
            _reply(bot, msg, "⛔ Only room moderators/admins can end IdleRPG seasons.")
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
    if subcmd in {"hof", "hall", "hall-of-fame"}:
        await _handle_hof(bot, args[1:], msg, is_room)
        return
    season = room.get("season", {}) if isinstance(room.get("season"), dict) else _blank_season(_now())
    ends_at = int(season.get("ends_at", 0) or 0)
    remaining = _duration(ends_at - _now()) if ends_at else "manual"
    _reply(
        bot,
        msg,
        f"🏁 Current season: {season.get('id', 'unknown')} — ends in {remaining}. "
        f"Hall of fame entries: {len(room.get('hall_of_fame', []) if isinstance(room.get('hall_of_fame'), list) else [])}.",
    )


async def _handle_export(bot, msg, is_room: bool) -> None:
    room_jid = _room_from_context(msg, is_room)
    data = await _get_data(bot)
    _export_public_state(data)
    root = _export_root()
    if room_jid:
        _reply(bot, msg, f"📤 IdleRPG export refreshed for {room_jid}: {root / _room_slug(room_jid)}")
    else:
        _reply(bot, msg, f"📤 IdleRPG export refreshed: {root}")


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
        _reply(bot, msg, "⛔ Only room moderators/admins can use this IdleRPG admin command.")
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


def _usage(bot) -> str:
    prefix = _command_prefix(bot)
    return (
        "🎲 IdleRPG usage:\n"
        f"{prefix}idlerpg on|off|enabled\n"
        f"{prefix}idlerpg register <character> <class>\n"
        f"{prefix}idlerpg status [character]\n"
        f"{prefix}idlerpg top [page|last|all]\n"
        f"{prefix}idlerpg players [page|last|all]\n"
        f"{prefix}idlerpg items [character]\n"
        f"{prefix}idlerpg profile [character]\n"
        f"{prefix}idlerpg achievements [character]\n"
        f"{prefix}idlerpg title <achievement|none>\n"
        f"{prefix}idlerpg map|hof|season\n"
        f"{prefix}idlerpg align <good|neutral|evil>\n"
        f"{prefix}idlerpg quest\n"
        f"{prefix}idlerpg login|logout|remove-me"
    )


@command(
    "idlerpg",
    role=Role.USER,
    aliases=["irpg", "idle"],
    short="Play IdleRPG in a MUC",
    usage="{prefix}idlerpg <on|off|enabled|register|status|top|players|profile|map|season|...>",
    examples=[
        "{prefix}idlerpg register Sven sysadmin",
        "{prefix}idlerpg enabled",
        "{prefix}idlerpg status",
        "{prefix}idlerpg top",
        "{prefix}idlerpg quest",
        "{prefix}idlerpg map",
        "{prefix}idlerpg profile Sven",
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
    elif subcmd == "title":
        await _handle_title(bot, sender, args, msg, is_room)
    elif subcmd == "map":
        await _handle_map(bot, msg, is_room)
    elif subcmd in {"hof", "hall", "hall-of-fame"}:
        await _handle_hof(bot, args, msg, is_room)
    elif subcmd == "season":
        await _handle_season(bot, sender, args, msg, is_room)
    elif subcmd == "export":
        await _handle_export(bot, msg, is_room)
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
