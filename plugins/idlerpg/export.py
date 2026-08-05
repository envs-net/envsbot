"""Export helpers for the IdleRPG plugin public-state writer.

This split module is imported by ``plugins.idlerpg`` and executed with the
shared IdleRPG namespace populated by the package facade.  The host module
must provide the configuration constants (for example ``EXPORT_PATH`` and
``EXPORT_PUBLIC_BASE_URL``), logging helper ``log``, game state helpers
(``_ranked_players``, ``_is_player_online``, ``_display_player`` and related
formatters), achievement helpers, rule constants and clock helper ``_now``.
The functions in this module write only public JSON export data and must not
expose private player JIDs.
"""

from __future__ import annotations
import json
import re
import shutil
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from utils.config import BASE_DIR


def _export_root() -> Path:
    path = Path(_dep_config.EXPORT_PATH)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _player_public_record(room_jid: str, jid: str, player: dict[str, Any], rank: int | None = None) -> dict[str, Any]:
    title_key = str(player.get("title") or "")
    display_name = _dep_formatting._display_player(player)
    return {
        "rank": rank,
        "name": display_name,
        "character": display_name,
        "class": str(player.get("class") or "idler"),
        "title": _dep_leveling._achievement_title(title_key) if title_key else "",
        "title_key": title_key,
        "level": int(player.get("level", 0) or 0),
        "ttl": int(player.get("next", 0) or 0),
        "time_to_level": int(player.get("next", 0) or 0),
        "alignment": _dep_formatting._alignment_name(player.get("alignment")),
        "idled": int(player.get("idled", 0) or 0),
        "played_for": max(0, _dep_formatting._now() - _dep_formatting._created_at(player)) if _dep_formatting._created_at(player) > 0 else 0,
        "item_sum": _dep_items._item_sum(player),
        "items": dict(player.get("items", {}) if isinstance(player.get("items"), dict) else {}),
        "unique_items": dict(player.get("unique_items", {}) if isinstance(player.get("unique_items"), dict) else {}),
        "unique_item_bonuses": _dep_items._unique_bonuses(player),
        "stats": dict(_dep_leveling._stats(player)),
        "achievements": [
            {"key": key, "title": _dep_leveling._achievement_title(key), "description": _dep_leveling._achievement_description(key)}
            for key in player.get("achievements", [])
            if key in _dep_constants.ACHIEVEMENTS
        ],
        "x": int(player.get("x", 0) or 0),
        "y": int(player.get("y", 0) or 0),
        "region": _dep_map._player_region(player),
        "online": _dep_state._is_player_online(room_jid, str(jid), player),
        "logged_out": bool(player.get("logged_out", False)),
        "created_at": int(player.get("created_at", 0) or 0),
        "last_seen": int(player.get("last_seen", 0) or 0),
    }


def _public_artifact_catalog() -> list[dict[str, Any]]:
    """Return the complete public artifact catalog in game-defined order."""
    catalog: list[dict[str, Any]] = []
    for raw_item in _dep_constants.UNIQUE_ITEMS:
        item = dict(raw_item)
        slot = str(item.get("slot") or "")
        tier = _dep_items._unique_item_tier(item)
        catalog_min_level = _dep_items._unique_item_level(item.get("min_level"))
        catalog.append({
            "name": str(item.get("name") or ""),
            "slot": slot,
            "tier": tier,
            "min_level": catalog_min_level,
            "effective_min_level": max(
                _dep_items._unique_item_level(_dep_config.UNIQUE_ITEM_MIN_LEVEL),
                catalog_min_level,
            ),
            "min_item_level": _dep_items._unique_item_level(item.get("min_item_level")),
            "max_item_level": _dep_items._unique_item_level(item.get("max_item_level")),
            "next_upgrade_level": _dep_items._next_unique_upgrade_level(slot, tier),
            "bonus": str(item.get("bonus") or ""),
            "bonus_percent": int(item.get("bonus_percent", 0) or 0),
        })
    return catalog


_PUBLIC_DIRECTORY_ACCESS = 0o055
_PUBLIC_FILE_ACCESS = 0o044


def _ensure_public_access(path: Path, required_bits: int) -> None:
    """Add public read/traverse bits without removing existing permissions.

    The bundled systemd unit intentionally runs the bot with ``UMask=0077``.
    Public IdleRPG exports are the narrow exception: website workers must be
    able to traverse generated directories and read the JSON files.
    """
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        wanted = current | required_bits
        if wanted != current:
            path.chmod(wanted)
    except OSError:
        _dep_config.log.warning(
            "[IDLERPG] Could not make public export path web-readable: %s",
            path,
            exc_info=True,
        )


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_public_access(path.parent, _PUBLIC_DIRECTORY_ACCESS)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    # Set access on the temporary inode before replace(), so the final path is
    # atomically published with web-readable permissions even under umask 0077.
    _ensure_public_access(tmp, _PUBLIC_FILE_ACCESS)
    tmp.replace(path)


_ROOT_COMPATIBILITY_EXPORTS = (
    "leaderboard.json",
    "map.json",
    "players.json",
    "hall_of_fame.json",
    "events.json",
    "season_events.json",
    "achievements.json",
    "artifacts.json",
)


def _safe_export_slug(value: Any) -> str:
    slug = str(value or "").strip()
    if not slug or len(slug) > 80:
        return ""
    return slug if re.fullmatch(r"[A-Za-z0-9_.-]+", slug) else ""


def _remove_export_path(path: Path) -> None:
    """Remove one generated export path without following directory symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _remove_export_path_safely(path: Path) -> None:
    try:
        _remove_export_path(path)
    except OSError:
        _dep_config.log.warning(
            "[IDLERPG] Could not remove stale public export %s",
            path,
            exc_info=True,
        )


def _previous_export_slugs(root: Path) -> set[str]:
    index_path = root / "index.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    rooms = payload.get("rooms", []) if isinstance(payload, dict) else []
    if not isinstance(rooms, list):
        return set()
    slugs: set[str] = set()
    for entry in rooms:
        if not isinstance(entry, dict):
            continue
        room_jid = str(entry.get("room") or "").strip()
        slug = _safe_export_slug(entry.get("slug"))
        if room_jid and slug == _dep_formatting._room_slug(room_jid):
            slugs.add(slug)
    return slugs


def _remove_root_compatibility_exports(root: Path) -> None:
    for filename in _ROOT_COMPATIBILITY_EXPORTS:
        _remove_export_path_safely(root / filename)


def _public_url(*parts: str) -> str:
    if not _dep_config.EXPORT_PUBLIC_BASE_URL:
        return ""
    return "/".join([_dep_config.EXPORT_PUBLIC_BASE_URL, *[part.strip("/") for part in parts if part]])


def _website_url(view: str = "", **params: str) -> str:
    """Return a public IdleRPG website URL instead of a raw JSON endpoint."""
    base = str(_dep_config.WEBSITE_PUBLIC_BASE_URL or "").rstrip("/")
    if not base:
        return ""
    query = {"view": str(view)} if view else {}
    query.update({key: str(value) for key, value in params.items() if value not in (None, "")})
    suffix = f"?{urlencode(query)}" if query else ""
    return f"{base}/{suffix}"


def _safe_event_kind(kind: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_.-]", "_", str(kind or "event").lower())
    return cleaned[:40] or "event"


_PRIVATE_JID_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)(?![\w.-])"
)


def _sanitize_public_text(text: Any) -> str:
    """Remove private bare JIDs from public IdleRPG event text."""
    return _PRIVATE_JID_RE.sub("[redacted-jid]", str(text or ""))


def _public_player_name(value: Any) -> str:
    name = str(value or "").strip()[:80]
    if not name or _PRIVATE_JID_RE.search(name):
        return ""
    return name


def _clean_event_data(data: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for raw_key, value in data.items():
        key = _safe_event_kind(str(raw_key))
        if "jid" in key or key in {"sender", "actor", "target"}:
            continue
        if isinstance(value, str):
            clean[key] = _sanitize_public_text(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, list):
            cleaned_items = []
            for item in value:
                if isinstance(item, str):
                    cleaned_items.append(_sanitize_public_text(item))
                elif isinstance(item, (int, float, bool)) or item is None:
                    cleaned_items.append(item)
            clean[key] = cleaned_items[:12]
    return clean


def _prune_events(room: dict[str, Any]) -> None:
    events = room.get("events")
    if not isinstance(events, list):
        room["events"] = []
        return
    cutoff = _dep_formatting._now() - max(0, _dep_config.EVENT_RETENTION_DAYS) * 86400 if _dep_config.EVENT_RETENTION_DAYS > 0 else 0
    pruned = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if cutoff and int(event.get("ts", 0) or 0) < cutoff:
            continue
        pruned.append(event)
    room["events"] = pruned[-max(1, _dep_config.EVENT_LOG_LIMIT):]


def _season_started_at(room: dict[str, Any]) -> int:
    if not isinstance(room, dict):
        return 0
    season = room.get("season")
    if not isinstance(season, dict):
        return 0
    try:
        return max(0, int(season.get("started_at", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _ensure_season_events(room: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the complete event store for the active season.

    Older persisted rooms do not have ``season_events`` yet.  Seed that store
    from the retained regular event log so upgrades preserve as much of the
    current season history as is still available.  Once present, this list is
    intentionally not capped by ``EVENT_LOG_LIMIT`` because the public
    ``season_events.json`` export must contain every event from the active
    season.
    """
    if not isinstance(room, dict):
        return []

    started_at = _season_started_at(room)
    existing = room.get("season_events")
    try:
        stored_started_at = max(0, int(room.get("season_events_started_at", 0) or 0))
    except (TypeError, ValueError):
        stored_started_at = 0
    if isinstance(existing, list) and stored_started_at == started_at:
        return existing

    source = existing if isinstance(existing, list) else room.get("events", [])
    if not isinstance(source, list):
        source = []

    season_events: list[dict[str, Any]] = []
    for event in source:
        if not isinstance(event, dict):
            continue
        try:
            event_ts = int(event.get("ts", 0) or 0)
        except (TypeError, ValueError):
            continue
        if started_at > 0 and event_ts < started_at:
            continue
        season_events.append(event)

    room["season_events"] = season_events
    room["season_events_started_at"] = started_at
    return season_events


def _reset_season_events(room: dict[str, Any]) -> None:
    room["season_events"] = []
    room["season_events_started_at"] = _season_started_at(room)


def _current_season_events(room: dict[str, Any]) -> list[dict[str, Any]]:
    events = _ensure_season_events(room)
    public = [_event_public_record(event) for event in events if isinstance(event, dict)]
    public.sort(key=lambda event: int(event.get("ts", 0) or 0))
    return public


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
    season_events = _ensure_season_events(room)
    _prune_events(room)
    events = room["events"]
    entry: dict[str, Any] = {"ts": _dep_formatting._now(), "kind": _safe_event_kind(kind), "text": _sanitize_public_text(text)[:500]}
    player_names = [_public_player_name(player) for player in (players or [])]
    player_names = [player for player in player_names if player]
    if player_names:
        entry["players"] = player_names[:8]
    clean_data = _clean_event_data(data or {})
    if clean_data:
        entry["data"] = clean_data
    events.append(entry)
    season_events.append(dict(entry))
    _prune_events(room)


def _event_public_record(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {"ts": _dep_formatting._now(), "kind": "event", "text": ""}
    payload = {
        "ts": int(event.get("ts", 0) or 0),
        "kind": _safe_event_kind(str(event.get("kind") or "event")),
        "text": _sanitize_public_text(event.get("text"))[:500],
    }
    players = event.get("players")
    if isinstance(players, list):
        payload["players"] = [player for player in (_public_player_name(value) for value in players) if player][:8]
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
    del room_jid  # The website selects its configured room export itself.
    return _website_url(
        "players",
        character=_dep_formatting._display_player(player),
    )


def _public_rules() -> dict[str, Any]:
    return {
        "tick_seconds": _dep_config.TICK_SECONDS,
        "rp_base": _dep_config.RP_BASE,
        "rp_step": _dep_config.RP_STEP,
        "penalty_step": _dep_config.PENALTY_STEP,
        "message_penalty": _dep_config.MESSAGE_PENALTY,
        "logout_penalty": _dep_config.LOGOUT_PENALTY,
        "logout_grace_seconds": _dep_config.LOGOUT_GRACE_SECONDS,
        "max_penalty": _dep_config.MAX_PENALTY,
        "count_command_messages": _dep_config.COUNT_COMMAND_MESSAGES,
        "map_x": _dep_config.MAP_X,
        "map_y": _dep_config.MAP_Y,
        "map_step_per_second": _dep_config.MAP_STEP_PER_SECOND,
        "map_step_per_tick": _dep_config.MAP_STEP_PER_TICK,
        "grid_battle_enabled": _dep_config.GRID_BATTLE_ENABLED,
        "quest_grid_step_seconds": _dep_config.QUEST_GRID_STEP_SECONDS,
        "quest_grid_min_points": _dep_config.QUEST_GRID_MIN_POINTS,
        "quest_grid_max_points": _dep_config.QUEST_GRID_MAX_POINTS,
        "quest_max_per_day": _dep_config.QUEST_MAX_PER_DAY,
        "quest_time_enabled": _dep_config.QUEST_TIME_ENABLED,
        "quest_grid_enabled": _dep_config.QUEST_GRID_ENABLED,
        "quest_time_weight": _dep_config.QUEST_TIME_WEIGHT,
        "quest_grid_weight": _dep_config.QUEST_GRID_WEIGHT,
        "quest_time_min_duration": _dep_config.QUEST_TIME_MIN_DURATION,
        "quest_time_max_duration": _dep_config.QUEST_TIME_MAX_DURATION,
        "event_chance": _dep_config.EVENT_CHANCE,
        "item_chance": _dep_config.ITEM_CHANCE,
        "battle_event_weight": _dep_config.BATTLE_EVENT_WEIGHT,
        "team_battle_event_weight": _dep_config.TEAM_BATTLE_EVENT_WEIGHT,
        "boss_event_weight": _dep_config.BOSS_EVENT_WEIGHT,
        "item_event_weight": _dep_config.ITEM_EVENT_WEIGHT,
        "item_damage_event_weight": _dep_config.ITEM_DAMAGE_EVENT_WEIGHT,
        "item_steal_event_weight": _dep_config.ITEM_STEAL_EVENT_WEIGHT,
        "alignment_event_weight": _dep_config.ALIGNMENT_EVENT_WEIGHT,
        "critical_strike_chance": _dep_config.CRITICAL_STRIKE_CHANCE,
        "critical_strike_chance_good": _dep_config.CRITICAL_STRIKE_CHANCE_GOOD,
        "critical_strike_chance_evil": _dep_config.CRITICAL_STRIKE_CHANCE_EVIL,
        "item_drop_chance": _dep_config.ITEM_DROP_CHANCE,
        "level_battle_chance_below_25": _dep_config.LEVEL_BATTLE_CHANCE_BELOW_25,
        "level_battle_chance_at_25": _dep_config.LEVEL_BATTLE_CHANCE_AT_25,
        "boss_min_players": _dep_config.BOSS_MIN_PLAYERS,
        "boss_max_players": _dep_config.BOSS_MAX_PLAYERS,
        "boss_min_level": _dep_config.BOSS_MIN_LEVEL,
        "boss_reward_percent": _dep_config.BOSS_REWARD_PERCENT,
        "boss_loss_percent": _dep_config.BOSS_LOSS_PERCENT,
        "boss_power_min_factor": _dep_config.BOSS_POWER_MIN_FACTOR,
        "boss_power_max_factor": _dep_config.BOSS_POWER_MAX_FACTOR,
        "manual_duel_max_distance": _dep_config.MANUAL_DUEL_MAX_DISTANCE,
        "manual_duel_cooldown_seconds": _dep_config.MANUAL_DUEL_COOLDOWN_SECONDS,
        "battle_win_min_percent": _dep_config.BATTLE_WIN_MIN_PERCENT,
        "battle_loss_min_percent": _dep_config.BATTLE_LOSS_MIN_PERCENT,
        "critical_min_percent": _dep_config.CRITICAL_MIN_PERCENT,
        "critical_max_percent": _dep_config.CRITICAL_MAX_PERCENT,
        "godsend_min_percent": _dep_config.GODSEND_MIN_PERCENT,
        "godsend_max_percent": _dep_config.GODSEND_MAX_PERCENT,
        "calamity_min_percent": _dep_config.CALAMITY_MIN_PERCENT,
        "calamity_max_percent": _dep_config.CALAMITY_MAX_PERCENT,
        "alignment_bonus_percent": _dep_config.ALIGNMENT_BONUS_PERCENT,
        "quest_reward_percent": _dep_config.QUEST_REWARD_PERCENT,
        "team_battle_percent": _dep_config.TEAM_BATTLE_PERCENT,
        "announce_login": _dep_config.ANNOUNCE_LOGIN,
        "announce_top_interval": _dep_config.ANNOUNCE_TOP_INTERVAL,
        "announce_top_limit": _dep_config.ANNOUNCE_TOP_LIMIT,
        "update_room_topic": _dep_config.UPDATE_ROOM_TOPIC,
        "topic_update_interval": _dep_config.TOPIC_UPDATE_INTERVAL,
        "topic_custom_text": _dep_config.TOPIC_CUSTOM_TEXT,
        "unique_items_enabled": _dep_config.UNIQUE_ITEMS_ENABLED,
        "unique_item_min_level": _dep_config.UNIQUE_ITEM_MIN_LEVEL,
        "unique_item_chance": _dep_config.UNIQUE_ITEM_CHANCE,
        "unique_bonus_cap_percent": _dep_constants.UNIQUE_BONUS_CAP_PERCENT,
        "alignment_item_power_factors": dict(_dep_constants.ALIGNMENT_ITEM_POWER_FACTORS),
        "level_reward_min_level": _dep_config.LEVEL_REWARD_MIN_LEVEL,
        "quest_min_level": _dep_config.QUEST_MIN_LEVEL,
        "quest_min_online_seconds": _dep_config.QUEST_MIN_ONLINE_SECONDS,
        "quest_interval": _dep_config.QUEST_INTERVAL,
        "quest_min_duration": _dep_config.QUEST_MIN_DURATION,
        "quest_max_duration": _dep_config.QUEST_MAX_DURATION,
        "season_enabled": _dep_config.SEASON_ENABLED,
        "season_duration_days": _dep_config.SEASON_DURATION_DAYS,
        "season_reset_on_rollover": _dep_config.SEASON_RESET_ON_ROLLOVER,
        "season_hof_size": _dep_config.SEASON_HOF_SIZE,
        "season_achievement_gates_enabled": _dep_config.SEASON_ACHIEVEMENT_GATES_ENABLED,
        "event_log_limit": _dep_config.EVENT_LOG_LIMIT,
        "event_retention_days": _dep_config.EVENT_RETENTION_DAYS,
        "export_event_limit": _dep_config.EXPORT_EVENT_LIMIT,
        "export_full_season_events": _dep_config.EXPORT_FULL_SEASON_EVENTS,
        "export_interval_seconds": _dep_config.EXPORT_INTERVAL_SECONDS,
        "export_top_limit": _dep_config.EXPORT_TOP_LIMIT,
    }


def _export_room_state(
    root: Path,
    room_jid: str,
    room: dict[str, Any],
    generated_at: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    slug = _dep_formatting._room_slug(room_jid)
    room_dir = root / slug
    ranked = _dep_state._ranked_players(room)
    leaderboard = [
        _player_public_record(room_jid, jid, player, rank=rank)
        for rank, (jid, player) in enumerate(ranked[:_dep_config.EXPORT_TOP_LIMIT], start=1)
    ]
    all_profiles = [
        _player_public_record(room_jid, jid, player, rank=rank)
        for rank, (jid, player) in enumerate(ranked, start=1)
    ]
    quest = room.get("quest", {}) if isinstance(room.get("quest"), dict) else {}
    active_quest = None
    if quest.get("active"):
        current_target = _dep_map._active_quest_target(quest)
        time_target = _dep_map._quest_time_target(quest)
        active_quest = {
            "type": _dep_quests._quest_type(quest),
            "text": quest.get("text", "adventure"),
            "started_at": int(quest.get("started_at", 0) or 0),
            "complete_at": int(quest.get("complete_at", 0) or 0),
            "route": quest.get("route", []),
            "route_index": int(quest.get("route_index", 0) or 0),
            "current_target": list(current_target) if current_target is not None else None,
            "target": list(time_target) if time_target is not None else None,
            "questers": [
                _dep_formatting._display_player(player)
                for jid in quest.get("questers", [])
                if isinstance((player := room.get("players", {}).get(jid)), dict)
            ],
        }
    season = room.get("season", {}) if isinstance(room.get("season"), dict) else {}
    events = _room_events(room, limit=_dep_config.EXPORT_EVENT_LIMIT)
    season_events = (
        _current_season_events(room)
        if _dep_config.EXPORT_FULL_SEASON_EVENTS
        else []
    )
    hall_of_fame = room.get("hall_of_fame", []) if isinstance(room.get("hall_of_fame"), list) else []
    room_payload = {
        "generated_at": generated_at,
        "room": room_jid,
        "slug": slug,
        "map": {"width": _dep_config.MAP_X, "height": _dep_config.MAP_Y},
        "season": season,
        "players_total": len(all_profiles),
        "players_online": sum(1 for player in all_profiles if player["online"]),
        "leaderboard": leaderboard,
        "players": all_profiles,
        "quest": active_quest,
        "events": events,
        "season_events_total": len(season_events),
        "hall_of_fame": hall_of_fame[-_dep_config.SEASON_HOF_SIZE:],
        "achievement_catalog": _dep_leveling._achievement_catalog(),
        "equipment_slots": list(_dep_constants.ITEMS),
        "artifact_catalog": _public_artifact_catalog(),
        "rules": _public_rules(),
    }
    _atomic_write_json(room_dir / "room.json", room_payload)
    _atomic_write_json(room_dir / "leaderboard.json", {"generated_at": generated_at, "room": room_jid, "players": leaderboard})
    _atomic_write_json(room_dir / "players.json", {"generated_at": generated_at, "room": room_jid, "players": all_profiles})
    _atomic_write_json(room_dir / "map.json", {
        "generated_at": generated_at,
        "room": room_jid,
        "width": _dep_config.MAP_X,
        "height": _dep_config.MAP_Y,
        "players": all_profiles,
        "quest": active_quest,
    })
    _atomic_write_json(room_dir / "hall_of_fame.json", {"generated_at": generated_at, "room": room_jid, "seasons": hall_of_fame[-_dep_config.SEASON_HOF_SIZE:]})
    _atomic_write_json(room_dir / "events.json", {"generated_at": generated_at, "room": room_jid, "events": events})
    if _dep_config.EXPORT_FULL_SEASON_EVENTS:
        _atomic_write_json(room_dir / "season_events.json", {
            "generated_at": generated_at,
            "room": room_jid,
            "season": {
                "id": str(season.get("id") or ""),
                "started_at": int(season.get("started_at", 0) or 0),
                "ends_at": int(season.get("ends_at", 0) or 0),
            },
            "events_total": len(season_events),
            "events": season_events,
        })
    else:
        _remove_export_path_safely(room_dir / "season_events.json")
    _atomic_write_json(room_dir / "achievements.json", {"generated_at": generated_at, "room": room_jid, "achievements": _dep_leveling._achievement_catalog()})
    _atomic_write_json(room_dir / "artifacts.json", {
        "generated_at": generated_at,
        "room": room_jid,
        "equipment_slots": room_payload["equipment_slots"],
        "artifacts": room_payload["artifact_catalog"],
    })
    profiles_dir = room_dir / "profiles"
    for profile in all_profiles:
        _atomic_write_json(profiles_dir / f"{_dep_formatting._slug(profile['name'])}.json", profile)
    summary = {
        "room": room_jid,
        "slug": slug,
        "players_total": len(all_profiles),
        "players_online": room_payload["players_online"],
        "leaderboard_url": _public_url(slug, "leaderboard.json"),
        "map_url": _public_url(slug, "map.json"),
        "artifacts_url": _public_url(slug, "artifacts.json"),
    }
    if _dep_config.EXPORT_FULL_SEASON_EVENTS:
        summary["season_events_url"] = _public_url(slug, "season_events.json")
    return summary, room_payload


def _export_public_state(
    data: dict[str, Any],
    enabled_rooms: dict[str, bool] | None = None,
) -> None:
    """Write public data only for rooms where IdleRPG is effectively enabled.

    ``enabled_rooms`` is supplied by the async room-feature layer.  ``None``
    preserves the historical all-room behavior for direct/internal callers
    that do not have a bot instance available.
    """
    if not _dep_config.EXPORT_ENABLED:
        return
    try:
        root = _export_root()
        generated_at = _dep_formatting._now()
        rooms = data.get("rooms", {}) if isinstance(data, dict) else {}
        if not isinstance(rooms, dict):
            rooms = {}

        enabled = (
            {str(room_jid) for room_jid, value in enabled_rooms.items() if value}
            if isinstance(enabled_rooms, dict)
            else {str(room_jid) for room_jid in rooms}
        )
        previous_slugs = _previous_export_slugs(root)
        known_slugs = {
            str(room_jid): _dep_formatting._room_slug(str(room_jid))
            for room_jid in rooms
        }

        summaries: list[dict[str, Any]] = []
        current_slugs: set[str] = set()
        default_room_payload = None
        default_room_season_events: list[dict[str, Any]] = []
        for room_jid, room in sorted(rooms.items()):
            room_jid = str(room_jid)
            if room_jid not in enabled or not isinstance(room, dict):
                continue
            summary, room_payload = _export_room_state(root, room_jid, room, generated_at)
            summaries.append(summary)
            current_slugs.add(str(summary["slug"]))
            if default_room_payload is None:
                default_room_payload = room_payload
                if _dep_config.EXPORT_FULL_SEASON_EVENTS:
                    default_room_season_events = _current_season_events(room)

        stale_slugs = previous_slugs - current_slugs
        stale_slugs.update(
            slug
            for room_jid, slug in known_slugs.items()
            if room_jid not in enabled
        )
        _atomic_write_json(root / "index.json", {"generated_at": generated_at, "rooms": summaries})
        for slug in sorted(stale_slugs):
            safe_slug = _safe_export_slug(slug)
            if safe_slug:
                _remove_export_path_safely(root / safe_slug)

        if default_room_payload:
            _atomic_write_json(root / "leaderboard.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "players": default_room_payload["leaderboard"],
            })
            _atomic_write_json(root / "map.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "width": _dep_config.MAP_X,
                "height": _dep_config.MAP_Y,
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
            if _dep_config.EXPORT_FULL_SEASON_EVENTS:
                season = default_room_payload.get("season", {})
                if not isinstance(season, dict):
                    season = {}
                _atomic_write_json(root / "season_events.json", {
                    "generated_at": generated_at,
                    "room": default_room_payload["room"],
                    "season": {
                        "id": str(season.get("id") or ""),
                        "started_at": int(season.get("started_at", 0) or 0),
                        "ends_at": int(season.get("ends_at", 0) or 0),
                    },
                    "events_total": len(default_room_season_events),
                    "events": default_room_season_events,
                })
            else:
                _remove_export_path_safely(root / "season_events.json")
            _atomic_write_json(root / "achievements.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "achievements": default_room_payload.get("achievement_catalog", _dep_leveling._achievement_catalog()),
            })
            _atomic_write_json(root / "artifacts.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "equipment_slots": default_room_payload["equipment_slots"],
                "artifacts": default_room_payload["artifact_catalog"],
            })
        else:
            _remove_root_compatibility_exports(root)
    except Exception:
        _dep_config.log.debug("[IDLERPG] Failed to export public state", exc_info=True)

# Explicit module dependencies; module-qualified access keeps cyclic domain
# relationships visible without copying names into sibling namespaces.
from . import config as _dep_config  # noqa: E402
from . import constants as _dep_constants  # noqa: E402
from . import formatting as _dep_formatting  # noqa: E402
from . import items as _dep_items  # noqa: E402
from . import leveling as _dep_leveling  # noqa: E402
from . import map as _dep_map  # noqa: E402
from . import quests as _dep_quests  # noqa: E402
from . import state as _dep_state  # noqa: E402
