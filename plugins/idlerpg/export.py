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

import hashlib
import json
import re
import shutil
import stat
from contextlib import suppress
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

from utils.config.defaults import BASE_DIR


def _export_root() -> Path:
    path = Path(_dep_config.EXPORT_PATH)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _export_tree_stats(root: Path) -> dict[str, int]:
    """Return generated JSON file count and bytes for diagnostics."""
    files = 0
    total_bytes = 0
    if root.is_dir():
        for path in root.rglob("*.json"):
            try:
                if path.is_file():
                    files += 1
                    total_bytes += max(0, int(path.stat().st_size))
            except OSError:
                continue
    return {"files": files, "bytes": total_bytes}


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
            "bonus_percent": int(cast(Any, item.get("bonus_percent", 0)) or 0),
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


def _json_export_bytes(payload: Any) -> bytes:
    """Return the exact bytes used for one public JSON export file."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")


def _content_digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_content_digest(path: Path) -> str | None:
    try:
        return _content_digest_bytes(path.read_bytes())
    except OSError:
        return None


def _atomic_write_json(path: Path, payload: Any) -> str:
    """Atomically publish JSON and return the SHA-256 of the exact bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_public_access(path.parent, _PUBLIC_DIRECTORY_ACCESS)
    encoded = _json_export_bytes(payload)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(encoded)
    # Set access on the temporary inode before replace(), so the final path is
    # atomically published with web-readable permissions even under umask 0077.
    _ensure_public_access(tmp, _PUBLIC_FILE_ACCESS)
    tmp.replace(path)
    return _content_digest_bytes(encoded)


_DELTA_MANIFEST_NAME = ".envsbot-export-manifest"
_DELTA_MANIFEST_VERSION = 2
_GENERATION_MANIFEST_NAME = "generation.json"
_GENERATION_FORMAT = "envsbot-generation-v1"


def _stable_export_digest(payload: Any) -> str:
    """Hash public content while ignoring the volatile generation timestamp."""
    stable = payload
    if isinstance(payload, dict) and "generated_at" in payload:
        stable = dict(payload)
        stable.pop("generated_at", None)
    encoded = json.dumps(
        stable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _generation_id(files: dict[str, str]) -> str:
    encoded = json.dumps(
        dict(sorted(files.items())),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _DeltaExportWriter:
    """Publish changed JSON and commit coherent public generations last.

    Individual JSON files are still atomically replaced, but readers can now
    use ``generation.json`` as a commit record.  Its exact per-file hashes are
    published only after every file belonging to that generation is in place.
    A reader that sees a hash mismatch simply retries against the next
    generation instead of combining old and new export data.
    """

    def __init__(self, root: Path):
        self.root = root
        self.previous = self._load_manifest()
        self.current: dict[str, dict[str, str]] = {}
        self.changed = 0
        self.skipped = 0
        self.deleted = 0
        self._bootstrap_existing_generations()

    @staticmethod
    def _has_valid_generation(directory: Path) -> bool:
        path = directory / _GENERATION_MANIFEST_NAME
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        return bool(
            isinstance(payload, dict)
            and payload.get("format") == _GENERATION_FORMAT
            and isinstance(payload.get("generation_id"), str)
            and isinstance(payload.get("files"), dict)
        )

    def _existing_json_files(self) -> dict[str, str]:
        """Hash the currently published legacy tree before the first update."""
        if not self.root.is_dir():
            return {}
        files: dict[str, str] = {}
        for path in sorted(self.root.rglob("*.json")):
            if path.name == _GENERATION_MANIFEST_NAME or not path.is_file():
                continue
            digest = _file_content_digest(path)
            if digest is not None:
                files[self._relative(path)] = digest
        return files

    def _bootstrap_existing_generations(self) -> None:
        """Commit the pre-update tree before introducing generation manifests.

        Without this bootstrap, the first export after upgrading an existing
        installation has a short interval where no generation marker exists and
        readers could fall back to the legacy, non-snapshot read path while files
        are already being replaced.  Publishing hashes of the untouched tree
        first closes that one-time upgrade race.
        """
        existing = self._existing_json_files()
        if not existing:
            return

        room_prefixes = sorted(
            {
                name.rsplit("/room.json", 1)[0]
                for name in existing
                if name.endswith("/room.json") and "/" in name
            }
        )
        for prefix in room_prefixes:
            directory = self.root / prefix
            if self._has_valid_generation(directory):
                continue
            normalized = prefix.rstrip("/") + "/"
            room_files = {
                name[len(normalized):]: digest
                for name, digest in existing.items()
                if name.startswith(normalized)
            }
            self._publish_generation(directory, room_files)

        if not self._has_valid_generation(self.root):
            self._publish_generation(self.root, existing)

    def _load_manifest(self) -> dict[str, dict[str, str]]:
        path = self.root / _DELTA_MANIFEST_NAME
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        files = payload.get("files")
        if not isinstance(files, dict):
            return {}

        version = payload.get("version")
        if version == _DELTA_MANIFEST_VERSION:
            result: dict[str, dict[str, str]] = {}
            for name, entry in files.items():
                if not isinstance(name, str) or not isinstance(entry, dict):
                    continue
                semantic = entry.get("semantic")
                content = entry.get("content")
                if isinstance(semantic, str) and isinstance(content, str):
                    result[name] = {"semantic": semantic, "content": content}
            return result

        # Seamless upgrade from the v1 semantic-only delta manifest.
        if version == 1:
            result = {}
            for name, semantic in files.items():
                if not isinstance(name, str) or not isinstance(semantic, str):
                    continue
                content = _file_content_digest(self.root / name)
                if content:
                    result[name] = {"semantic": semantic, "content": content}
            return result
        return {}

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def write(self, path: Path, payload: Any) -> bool:
        relative = self._relative(path)
        semantic = _stable_export_digest(payload)
        previous = self.previous.get(relative)
        if path.is_file() and previous and previous.get("semantic") == semantic:
            content = _file_content_digest(path)
            if content and content == previous.get("content"):
                self.current[relative] = {"semantic": semantic, "content": content}
                self.skipped += 1
                return False

        content = _atomic_write_json(path, payload)
        self.current[relative] = {"semantic": semantic, "content": content}
        self.changed += 1
        return True

    def preserve(self, path: Path) -> None:
        """Carry an unchanged file forward while retaining its exact hash."""
        relative = self._relative(path)
        previous = self.previous.get(relative)
        if not path.is_file():
            return
        content = _file_content_digest(path)
        if content is None:
            return
        semantic = (previous.get("semantic") if previous else None) or content
        self.current[relative] = {"semantic": semantic, "content": content}
        self.skipped += 1

    def remove(self, path: Path) -> bool:
        existed = path.exists() or path.is_symlink()
        _remove_export_path_safely(path)
        relative = self._relative(path)
        prefix = relative.rstrip("/") + "/"
        for name in tuple(self.current):
            if name == relative or name.startswith(prefix):
                self.current.pop(name, None)
        if existed:
            self.deleted += 1
        return existed

    def prune_json_directory(self, directory: Path, expected_names: set[str]) -> None:
        if not directory.is_dir():
            return
        for path in directory.glob("*.json"):
            if path.name == _GENERATION_MANIFEST_NAME:
                continue
            if path.name not in expected_names:
                self.remove(path)

    def _generation_files(self, prefix: str = "") -> dict[str, str]:
        if not prefix:
            return {
                name: entry["content"]
                for name, entry in sorted(self.current.items())
            }
        normalized = prefix.rstrip("/") + "/"
        return {
            name[len(normalized):]: entry["content"]
            for name, entry in sorted(self.current.items())
            if name.startswith(normalized)
        }

    def _publish_generation(self, directory: Path, files: dict[str, str]) -> None:
        if not files:
            _remove_export_path_safely(directory / _GENERATION_MANIFEST_NAME)
            return
        generation_id = _generation_id(files)
        generation_path = directory / _GENERATION_MANIFEST_NAME
        try:
            previous = json.loads(generation_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            previous = {}
        if (
            isinstance(previous, dict)
            and previous.get("format") == _GENERATION_FORMAT
            and previous.get("generation_id") == generation_id
        ):
            return
        _atomic_write_json(
            generation_path,
            {
                "format": _GENERATION_FORMAT,
                "generation_id": generation_id,
                "generated_at": _dep_formatting._now(),
                "files": dict(sorted(files.items())),
            },
        )

    def finish(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        files = {
            name: dict(entry)
            for name, entry in sorted(self.current.items())
        }
        manifest = {
            "version": _DELTA_MANIFEST_VERSION,
            "files": files,
        }
        previous_sorted = {
            name: dict(entry)
            for name, entry in sorted(self.previous.items())
        }
        if files != previous_sorted:
            # Internal state is safe to publish before the public commit marker.
            # If the process dies here, the next export can reconstruct and
            # republish generation.json without exposing a mixed snapshot.
            _atomic_write_json(self.root / _DELTA_MANIFEST_NAME, manifest)

        room_prefixes = sorted(
            {
                name.rsplit("/room.json", 1)[0]
                for name in self.current
                if name.endswith("/room.json") and "/" in name
            }
        )
        for prefix in room_prefixes:
            self._publish_generation(
                self.root / prefix,
                self._generation_files(prefix),
            )

        # Root generation is the final public commit marker and includes every
        # file so compatibility manifests can safely reference room chunks.
        self._publish_generation(self.root, self._generation_files())


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
            cleaned_items: list[Any] = []
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
    """Return legacy in-memory season history without creating a cache.

    Normalized persistence keeps complete season history in SQLite.  This
    helper remains for legacy stores and direct export callers only.
    """
    if not isinstance(room, dict):
        return []
    started_at = _season_started_at(room)
    existing = room.get("season_events")
    if isinstance(existing, list):
        try:
            stored_started_at = max(
                0, int(room.get("season_events_started_at", started_at) or 0)
            )
        except (TypeError, ValueError):
            stored_started_at = 0
        if stored_started_at == started_at:
            return [event for event in existing if isinstance(event, dict)]

    source = room.get("events", [])
    if not isinstance(source, list):
        return []
    result: list[dict[str, Any]] = []
    for event in source:
        if not isinstance(event, dict):
            continue
        try:
            event_ts = int(event.get("ts", 0) or 0)
        except (TypeError, ValueError):
            continue
        if started_at > 0 and event_ts < started_at:
            continue
        result.append(event)
    return result


def _reset_season_events(room: dict[str, Any]) -> None:
    """Remove legacy full-season caches after a season boundary."""
    room.pop("season_events", None)
    room.pop("season_events_started_at", None)


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
    _prune_events(room)
    events = room["events"]
    entry: dict[str, Any] = {
        "ts": _dep_formatting._now(),
        "kind": _safe_event_kind(kind),
        "text": _sanitize_public_text(text)[:500],
        "_season_started_at": _season_started_at(room),
    }
    player_names = [_public_player_name(player) for player in (players or [])]
    player_names = [player for player in player_names if player]
    if player_names:
        entry["players"] = player_names[:8]
    clean_data = _clean_event_data(data or {})
    if clean_data:
        entry["data"] = clean_data
    events.append(entry)
    pending = room.setdefault("_pending_events", [])
    if not isinstance(pending, list):
        pending = []
        room["_pending_events"] = pending
    pending.append(dict(entry))
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
        "export_season_event_chunk_size": _dep_config.EXPORT_SEASON_EVENT_CHUNK_SIZE,
        "export_interval_seconds": _dep_config.EXPORT_INTERVAL_SECONDS,
        "export_top_limit": _dep_config.EXPORT_TOP_LIMIT,
    }


_SEASON_EVENT_FORMAT = "chunked-v1"
_SEASON_EVENT_CHUNK_DIR = "season-events"


def _season_event_rowid(event: dict[str, Any]) -> int:
    try:
        return max(0, int(event.get("_storage_rowid", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _season_event_public_record(event: dict[str, Any]) -> dict[str, Any]:
    payload = _event_public_record(event)
    rowid = _season_event_rowid(event)
    if rowid > 0:
        payload["seq"] = rowid
    return payload


def _season_event_chunk_name(index: int) -> str:
    return f"{max(1, int(index)):06d}.json"


def _season_event_chunk_path(room_dir: Path, index: int) -> Path:
    return room_dir / _SEASON_EVENT_CHUNK_DIR / _season_event_chunk_name(index)


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _season_manifest_chunks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = payload.get("chunks")
    if not isinstance(chunks, list):
        return []
    result: list[dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            return []
        filename = str(chunk.get("file") or "")
        if not re.fullmatch(r"season-events/[0-9]{6}\.json", filename):
            return []
        result.append(dict(chunk))
    return result


def _season_manifest_for_root(
    manifest: dict[str, Any],
    *,
    slug: str,
    generated_at: int,
) -> dict[str, Any]:
    root_manifest = dict(manifest)
    root_manifest["generated_at"] = generated_at
    chunks = []
    for chunk in _season_manifest_chunks(manifest):
        item = dict(chunk)
        item["file"] = f"{slug}/{item['file']}"
        chunks.append(item)
    root_manifest["chunks"] = chunks
    return root_manifest


def _prune_season_event_chunks(
    room_dir: Path,
    expected_names: set[str],
    *,
    writer: _DeltaExportWriter | None,
) -> None:
    directory = room_dir / _SEASON_EVENT_CHUNK_DIR
    if writer is not None:
        writer.prune_json_directory(directory, expected_names)
        return
    if not directory.is_dir():
        return
    for path in directory.glob("*.json"):
        if path.name not in expected_names:
            _remove_export_path_safely(path)
    with suppress(OSError):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


def _remove_season_event_export(
    room_dir: Path,
    *,
    writer: _DeltaExportWriter | None,
) -> None:
    manifest_path = room_dir / "season_events.json"
    chunk_dir = room_dir / _SEASON_EVENT_CHUNK_DIR
    if writer is not None:
        writer.remove(manifest_path)
        writer.remove(chunk_dir)
    else:
        _remove_export_path_safely(manifest_path)
        _remove_export_path_safely(chunk_dir)


def _preserve_season_event_export(
    room_dir: Path,
    *,
    writer: _DeltaExportWriter | None,
) -> dict[str, Any]:
    manifest_path = room_dir / "season_events.json"
    manifest = _read_json_dict(manifest_path)
    if (
        manifest is None
        or manifest.get("format") != _SEASON_EVENT_FORMAT
        or not _season_manifest_chunks(manifest)
        and int(manifest.get("events_total", 0) or 0) > 0
    ):
        raise ValueError("existing season event export is missing or incompatible")
    if writer is not None:
        writer.preserve(manifest_path)
        for chunk in _season_manifest_chunks(manifest):
            writer.preserve(room_dir / str(chunk["file"]))
    return manifest


def _write_season_event_export(
    room_dir: Path,
    *,
    room_jid: str,
    season: dict[str, Any],
    generated_at: int,
    events: list[dict[str, Any]],
    events_total: int,
    append: bool,
    writer: _DeltaExportWriter | None,
) -> dict[str, Any]:
    """Write append-friendly full-season history and return its manifest."""
    _write = writer.write if writer is not None else _atomic_write_json
    chunk_size = max(1, int(_dep_config.EXPORT_SEASON_EVENT_CHUNK_SIZE))
    season_payload = {
        "id": str(season.get("id") or ""),
        "started_at": int(season.get("started_at", 0) or 0),
        "ends_at": int(season.get("ends_at", 0) or 0),
    }
    public_events = [_season_event_public_record(event) for event in events]
    public_events.sort(
        key=lambda event: (
            int(event.get("ts", 0) or 0),
            int(event.get("seq", 0) or 0),
        )
    )

    existing_chunks: list[dict[str, Any]] = []
    existing_total = 0
    last_rowid = 0
    if append:
        manifest = _read_json_dict(room_dir / "season_events.json")
        if manifest is None or manifest.get("format") != _SEASON_EVENT_FORMAT:
            raise ValueError("append requested without a chunked season manifest")
        existing_season = manifest.get("season")
        if not isinstance(existing_season, dict) or int(existing_season.get("started_at", 0) or 0) != season_payload["started_at"]:
            raise ValueError("season event append crosses a season boundary")
        if int(manifest.get("chunk_size", 0) or 0) != chunk_size:
            raise ValueError("season event chunk size changed; full rebuild required")
        existing_chunks = _season_manifest_chunks(manifest)
        existing_total = max(0, int(manifest.get("events_total", 0) or 0))
        last_rowid = max(0, int(manifest.get("last_rowid", 0) or 0))
        expected_previous_total = max(0, int(events_total) - len(public_events))
        if existing_total != expected_previous_total:
            raise ValueError("season event append base does not match exported history")
        public_events = [event for event in public_events if int(event.get("seq", 0) or 0) > last_rowid]
        if existing_total + len(public_events) != max(0, int(events_total)):
            raise ValueError("season event delta is incomplete")
        if writer is not None:
            for chunk in existing_chunks:
                writer.preserve(room_dir / str(chunk["file"]))

    chunks: list[dict[str, Any]] = [dict(chunk) for chunk in existing_chunks]
    pending = list(public_events)
    if append and chunks and pending:
        final_meta = chunks[-1]
        final_path = room_dir / str(final_meta["file"])
        final_payload = _read_json_dict(final_path)
        final_events = final_payload.get("events") if isinstance(final_payload, dict) else None
        if not isinstance(final_events, list):
            raise ValueError("last season event chunk is unreadable")
        if len(final_events) < chunk_size:
            take = min(chunk_size - len(final_events), len(pending))
            final_events = [event for event in final_events if isinstance(event, dict)] + pending[:take]
            pending = pending[take:]
            _write(final_path, {
                "generated_at": generated_at,
                "room": room_jid,
                "season_started_at": season_payload["started_at"],
                "chunk": len(chunks),
                "events": final_events,
            })
            seqs = [int(event.get("seq", 0) or 0) for event in final_events if isinstance(event, dict)]
            final_meta.update({
                "events": len(final_events),
                "first_rowid": min((seq for seq in seqs if seq > 0), default=0),
                "last_rowid": max(seqs, default=0),
            })

    if not append:
        chunks = []
        pending = list(public_events)

    while pending:
        index = len(chunks) + 1
        chunk_events = pending[:chunk_size]
        pending = pending[chunk_size:]
        path = _season_event_chunk_path(room_dir, index)
        _write(path, {
            "generated_at": generated_at,
            "room": room_jid,
            "season_started_at": season_payload["started_at"],
            "chunk": index,
            "events": chunk_events,
        })
        seqs = [int(event.get("seq", 0) or 0) for event in chunk_events]
        chunks.append({
            "file": f"{_SEASON_EVENT_CHUNK_DIR}/{path.name}",
            "events": len(chunk_events),
            "first_rowid": min((seq for seq in seqs if seq > 0), default=0),
            "last_rowid": max(seqs, default=0),
        })

    if not append and max(0, int(events_total)) != len(public_events):
        raise ValueError("full season event export does not match database revision")

    expected_names = {Path(str(chunk["file"])).name for chunk in chunks}
    _prune_season_event_chunks(room_dir, expected_names, writer=writer)
    last_rowid = max(
        [int(chunk.get("last_rowid", 0) or 0) for chunk in chunks] + [last_rowid]
    )
    manifest = {
        "generated_at": generated_at,
        "room": room_jid,
        "format": _SEASON_EVENT_FORMAT,
        "season": season_payload,
        "events_total": max(0, int(events_total)),
        "chunk_size": chunk_size,
        "last_rowid": last_rowid,
        "chunks": chunks,
    }
    _write(room_dir / "season_events.json", manifest)
    return manifest

def _export_room_state(
    root: Path,
    room_jid: str,
    room: dict[str, Any],
    generated_at: int,
    season_events: list[dict[str, Any]] | None = None,
    *,
    season_events_count: int | None = None,
    preserve_season_events: bool = False,
    append_season_events: bool = False,
    writer: _DeltaExportWriter | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    slug = _dep_formatting._room_slug(room_jid)
    room_dir = root / slug
    _write = writer.write if writer is not None else _atomic_write_json
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
    season_events_source = (
        season_events if season_events is not None else _ensure_season_events(room)
    )
    season_events_payload = (
        [event for event in season_events_source if isinstance(event, dict)]
        if _dep_config.EXPORT_FULL_SEASON_EVENTS and not preserve_season_events
        else []
    )
    season_events_total = (
        max(0, int(season_events_count))
        if season_events_count is not None
        else len(season_events_payload)
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
        "season_events_total": season_events_total,
        "hall_of_fame": hall_of_fame[-_dep_config.SEASON_HOF_SIZE:],
        "achievement_catalog": _dep_leveling._achievement_catalog(),
        "equipment_slots": list(_dep_constants.ITEMS),
        "artifact_catalog": _public_artifact_catalog(),
        "rules": _public_rules(),
    }
    _write(room_dir / "room.json", room_payload)
    _write(room_dir / "leaderboard.json", {"generated_at": generated_at, "room": room_jid, "players": leaderboard})
    _write(room_dir / "players.json", {"generated_at": generated_at, "room": room_jid, "players": all_profiles})
    _write(room_dir / "map.json", {
        "generated_at": generated_at,
        "room": room_jid,
        "width": _dep_config.MAP_X,
        "height": _dep_config.MAP_Y,
        "players": all_profiles,
        "quest": active_quest,
    })
    _write(room_dir / "hall_of_fame.json", {"generated_at": generated_at, "room": room_jid, "seasons": hall_of_fame[-_dep_config.SEASON_HOF_SIZE:]})
    _write(room_dir / "events.json", {"generated_at": generated_at, "room": room_jid, "events": events})
    season_events_manifest: dict[str, Any] | None = None
    if _dep_config.EXPORT_FULL_SEASON_EVENTS and preserve_season_events:
        season_events_manifest = _preserve_season_event_export(
            room_dir, writer=writer
        )
    elif _dep_config.EXPORT_FULL_SEASON_EVENTS:
        season_events_manifest = _write_season_event_export(
            room_dir,
            room_jid=room_jid,
            season=season,
            generated_at=generated_at,
            events=season_events_payload,
            events_total=season_events_total,
            append=append_season_events,
            writer=writer,
        )
    else:
        _remove_season_event_export(room_dir, writer=writer)
    _write(room_dir / "achievements.json", {"generated_at": generated_at, "room": room_jid, "achievements": _dep_leveling._achievement_catalog()})
    _write(room_dir / "artifacts.json", {
        "generated_at": generated_at,
        "room": room_jid,
        "equipment_slots": room_payload["equipment_slots"],
        "artifacts": room_payload["artifact_catalog"],
    })
    profiles_dir = room_dir / "profiles"
    profile_names: set[str] = set()
    for profile in all_profiles:
        filename = f"{_dep_formatting._slug(profile['name'])}.json"
        profile_names.add(filename)
        _write(profiles_dir / filename, profile)
    if writer is not None:
        writer.prune_json_directory(profiles_dir, profile_names)
    if season_events_manifest is not None:
        room_payload["_season_events_manifest"] = season_events_manifest

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
    season_events_by_room: dict[str, list[dict[str, Any]] | None] | None = None,
    season_event_counts_by_room: dict[str, int] | None = None,
    season_events_append_by_room: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Write a complete public export and return compact diagnostics.

    This function is synchronous by design.  Async callers must run it in a
    worker thread so filesystem and JSON work cannot block XMPP processing.
    """
    if not _dep_config.EXPORT_ENABLED:
        return {"ok": True, "rooms": 0, "players": 0, "events": 0, "files": 0, "bytes": 0}
    try:
        root = _export_root()
        writer = _DeltaExportWriter(root)
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
        default_room_season_manifest: dict[str, Any] | None = None
        exported_events = 0
        exported_players = 0
        for room_jid, room in sorted(rooms.items()):
            room_jid = str(room_jid)
            if room_jid not in enabled or not isinstance(room, dict):
                continue
            if isinstance(season_events_by_room, dict):
                has_season_entry = room_jid in season_events_by_room
                room_season_events = season_events_by_room.get(room_jid)
            else:
                has_season_entry = False
                room_season_events = None
            preserve_season_events = has_season_entry and room_season_events is None
            room_season_count = (
                season_event_counts_by_room.get(room_jid)
                if isinstance(season_event_counts_by_room, dict)
                else None
            )
            append_season_events = bool(
                season_events_append_by_room.get(room_jid, False)
                if isinstance(season_events_append_by_room, dict)
                else False
            )
            summary, room_payload = _export_room_state(
                root,
                room_jid,
                room,
                generated_at,
                room_season_events,
                season_events_count=room_season_count,
                preserve_season_events=preserve_season_events,
                append_season_events=append_season_events,
                writer=writer,
            )
            summaries.append(summary)
            current_slugs.add(str(summary["slug"]))
            exported_players += int(room_payload.get("players_total", 0) or 0)
            exported_events += len(room_payload.get("events", []))
            if _dep_config.EXPORT_FULL_SEASON_EVENTS:
                exported_events += int(room_payload.get("season_events_total", 0) or 0)
            if default_room_payload is None:
                default_room_payload = room_payload
                manifest = room_payload.get("_season_events_manifest")
                if isinstance(manifest, dict):
                    default_room_season_manifest = manifest

        stale_slugs = previous_slugs - current_slugs
        stale_slugs.update(
            slug
            for room_jid, slug in known_slugs.items()
            if room_jid not in enabled
        )
        writer.write(root / "index.json", {"generated_at": generated_at, "rooms": summaries})
        for slug in sorted(stale_slugs):
            safe_slug = _safe_export_slug(slug)
            if safe_slug:
                writer.remove(root / safe_slug)

        if default_room_payload:
            writer.write(root / "leaderboard.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "players": default_room_payload["leaderboard"],
            })
            writer.write(root / "map.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "width": _dep_config.MAP_X,
                "height": _dep_config.MAP_Y,
                "players": default_room_payload["players"],
                "quest": default_room_payload["quest"],
            })
            writer.write(root / "players.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "players": default_room_payload["players"],
            })
            writer.write(root / "hall_of_fame.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "seasons": default_room_payload["hall_of_fame"],
            })
            writer.write(root / "events.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "events": default_room_payload.get("events", []),
            })
            if _dep_config.EXPORT_FULL_SEASON_EVENTS and default_room_season_manifest is not None:
                writer.write(
                    root / "season_events.json",
                    _season_manifest_for_root(
                        default_room_season_manifest,
                        slug=_dep_formatting._room_slug(str(default_room_payload["room"])),
                        generated_at=generated_at,
                    ),
                )
            elif not _dep_config.EXPORT_FULL_SEASON_EVENTS:
                writer.remove(root / "season_events.json")
                writer.remove(root / _SEASON_EVENT_CHUNK_DIR)
            writer.write(root / "achievements.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "achievements": default_room_payload.get("achievement_catalog", _dep_leveling._achievement_catalog()),
            })
            writer.write(root / "artifacts.json", {
                "generated_at": generated_at,
                "room": default_room_payload["room"],
                "equipment_slots": default_room_payload["equipment_slots"],
                "artifacts": default_room_payload["artifact_catalog"],
            })
        else:
            for filename in _ROOT_COMPATIBILITY_EXPORTS:
                writer.remove(root / filename)

        writer.finish()
        tree = _export_tree_stats(root)
        return {
            "ok": True,
            "generated_at": generated_at,
            "rooms": len(summaries),
            "players": exported_players,
            "events": exported_events,
            "files_changed": writer.changed,
            "files_skipped": writer.skipped,
            "files_deleted": writer.deleted,
            **tree,
        }
    except Exception as exc:
        _dep_config.log.debug("[IDLERPG] Failed to export public state", exc_info=True)
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "rooms": 0,
            "players": 0,
            "events": 0,
            "files": 0,
            "bytes": 0,
        }


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
