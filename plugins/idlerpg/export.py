"""Split module for plugins/idlerpg.py: export."""

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any
from utils.config import BASE_DIR


def _export_root() -> Path:
    path = Path(EXPORT_PATH)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _player_public_record(room_jid: str, jid: str, player: dict[str, Any], rank: int | None = None) -> dict[str, Any]:
    title_key = str(player.get("title") or "")
    return {
        "rank": rank,
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
        "unique_items": dict(player.get("unique_items", {}) if isinstance(player.get("unique_items"), dict) else {}),
        "unique_item_bonuses": _unique_bonuses(player),
        "stats": dict(_stats(player)),
        "achievements": [
            {"key": key, "title": _achievement_title(key), "description": _achievement_description(key)}
            for key in player.get("achievements", [])
            if key in ACHIEVEMENTS
        ],
        "x": int(player.get("x", 0) or 0),
        "y": int(player.get("y", 0) or 0),
        "region": _player_region(player),
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


def _safe_event_kind(kind: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_.-]", "_", str(kind or "event").lower())
    return cleaned[:40] or "event"


def _clean_event_data(data: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in data.items():
        key = _safe_event_kind(str(key))
        if key in {"jid", "sender", "actor_jid", "target_jid"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, list):
            clean[key] = [item for item in value if isinstance(item, (str, int, float, bool))][:12]
    return clean


def _prune_events(room: dict[str, Any]) -> None:
    events = room.get("events")
    if not isinstance(events, list):
        room["events"] = []
        return
    cutoff = _now() - max(0, EVENT_RETENTION_DAYS) * 86400 if EVENT_RETENTION_DAYS > 0 else 0
    pruned = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if cutoff and int(event.get("ts", 0) or 0) < cutoff:
            continue
        pruned.append(event)
    room["events"] = pruned[-max(1, EVENT_LOG_LIMIT):]


def _record_event(
    room: dict[str, Any],
    kind: str,
    text: str,
    *,
    players: list[str] | tuple[str, ...] | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    events = room.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        room["events"] = events
    _prune_events(room)
    events = room.setdefault("events", [])
    entry: dict[str, Any] = {"ts": _now(), "kind": _safe_event_kind(kind), "text": str(text or "")[:500]}
    player_names = [str(player)[:80] for player in (players or []) if str(player).strip()]
    if player_names:
        entry["players"] = player_names[:8]
    clean_data = _clean_event_data(data or {})
    if clean_data:
        entry["data"] = clean_data
    events.append(entry)
    _prune_events(room)


def _event_public_record(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {"ts": _now(), "kind": "event", "text": ""}
    payload = {
        "ts": int(event.get("ts", 0) or 0),
        "kind": _safe_event_kind(str(event.get("kind") or "event")),
        "text": str(event.get("text") or "")[:500],
    }
    players = event.get("players")
    if isinstance(players, list):
        payload["players"] = [str(player)[:80] for player in players if str(player).strip()][:8]
    data = event.get("data")
    if isinstance(data, dict):
        payload["data"] = _clean_event_data(data)
    return payload


def _room_events(room: dict[str, Any], *, limit: int | None = None) -> list[dict[str, Any]]:
    if isinstance(room, dict):
        _prune_events(room)
    events = room.get("events", []) if isinstance(room, dict) else []
    if not isinstance(events, list):
        return []
    public = [_event_public_record(event) for event in events if isinstance(event, dict)]
    public.sort(key=lambda event: int(event.get("ts", 0) or 0))
    if limit is not None and limit >= 0:
        public = public[-limit:]
    return public


def _profile_url(room_jid: str, player: dict[str, Any]) -> str:
    return _public_url(_room_slug(room_jid), "profiles", f"{_slug(_display_player(player))}.json")


def _public_rules() -> dict[str, Any]:
    return {
        "tick_seconds": TICK_SECONDS,
        "rp_base": RP_BASE,
        "rp_step": RP_STEP,
        "penalty_step": PENALTY_STEP,
        "message_penalty": MESSAGE_PENALTY,
        "logout_penalty": LOGOUT_PENALTY,
        "logout_grace_seconds": LOGOUT_GRACE_SECONDS,
        "max_penalty": MAX_PENALTY,
        "map_x": MAP_X,
        "map_y": MAP_Y,
        "map_step_per_tick": MAP_STEP_PER_TICK,
        "event_chance": EVENT_CHANCE,
        "item_chance": ITEM_CHANCE,
        "battle_event_weight": BATTLE_EVENT_WEIGHT,
        "team_battle_event_weight": TEAM_BATTLE_EVENT_WEIGHT,
        "item_event_weight": ITEM_EVENT_WEIGHT,
        "item_damage_event_weight": ITEM_DAMAGE_EVENT_WEIGHT,
        "item_steal_event_weight": ITEM_STEAL_EVENT_WEIGHT,
        "alignment_event_weight": ALIGNMENT_EVENT_WEIGHT,
        "critical_strike_chance": CRITICAL_STRIKE_CHANCE,
        "item_drop_chance": ITEM_DROP_CHANCE,
        "announce_login": ANNOUNCE_LOGIN,
        "announce_top_interval": ANNOUNCE_TOP_INTERVAL,
        "announce_top_limit": ANNOUNCE_TOP_LIMIT,
        "update_room_topic": UPDATE_ROOM_TOPIC,
        "topic_update_interval": TOPIC_UPDATE_INTERVAL,
        "topic_custom_text": TOPIC_CUSTOM_TEXT,
        "unique_items_enabled": UNIQUE_ITEMS_ENABLED,
        "unique_item_min_level": UNIQUE_ITEM_MIN_LEVEL,
        "unique_item_chance": UNIQUE_ITEM_CHANCE,
        "level_reward_min_level": LEVEL_REWARD_MIN_LEVEL,
        "quest_min_level": QUEST_MIN_LEVEL,
        "quest_interval": QUEST_INTERVAL,
        "quest_min_duration": QUEST_MIN_DURATION,
        "quest_max_duration": QUEST_MAX_DURATION,
        "season_enabled": SEASON_ENABLED,
        "season_duration_days": SEASON_DURATION_DAYS,
        "season_reset_on_rollover": SEASON_RESET_ON_ROLLOVER,
        "season_hof_size": SEASON_HOF_SIZE,
        "season_achievement_gates_enabled": SEASON_ACHIEVEMENT_GATES_ENABLED,
        "event_log_limit": EVENT_LOG_LIMIT,
        "event_retention_days": EVENT_RETENTION_DAYS,
        "export_event_limit": EXPORT_EVENT_LIMIT,
        "export_top_limit": EXPORT_TOP_LIMIT,
    }


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
    events = _room_events(room, limit=EXPORT_EVENT_LIMIT)
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
        "events": events,
        "hall_of_fame": hall_of_fame[-SEASON_HOF_SIZE:],
        "achievement_catalog": _achievement_catalog(),
        "rules": _public_rules(),
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
    _atomic_write_json(room_dir / "events.json", {"generated_at": generated_at, "room": room_jid, "events": events})
    _atomic_write_json(room_dir / "achievements.json", {"generated_at": generated_at, "room": room_jid, "achievements": _achievement_catalog()})
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
            _atomic_write_json(root / "events.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "events": default_room_payload.get("events", []),
            })
            _atomic_write_json(root / "achievements.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "achievements": default_room_payload.get("achievement_catalog", _achievement_catalog()),
            })
    except Exception:
        log.debug("[IDLERPG] Failed to export public state", exc_info=True)
