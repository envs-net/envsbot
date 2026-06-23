"""Shared API for room-scoped plugin feature toggles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utils.formatting import bool_label


@dataclass(frozen=True)
class RoomFeatureState:
    name: str
    enabled: bool
    default: bool
    modified: bool


def _rooms_module():
    # Imported lazily to avoid circular imports during plugin discovery.
    from core_plugins import rooms
    return rooms


def _normalize_plugin_name(name: str) -> str:
    value = str(name).strip().lower()
    aliases = {
        "info": "information",
        "infos": "information",
        "roominfo": "information",
    }
    return aliases.get(value, value)


def _coerce_feature_flag(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", ""}:
            return False
    if value is None:
        return fallback
    return bool(value)

def available_features() -> list[str]:
    rooms = _rooms_module()
    return sorted(rooms.PLUGIN_STORE_CONFIG)


def is_known_feature(plugin: str) -> bool:
    return _normalize_plugin_name(plugin) in available_features()


async def _state_for(bot: Any, room_jid: str, plugin: str) -> RoomFeatureState:
    rooms = _rooms_module()
    plugin = _normalize_plugin_name(plugin)
    conf = rooms.PLUGIN_STORE_CONFIG[plugin]
    typ = conf["type"]
    if typ != "dict":
        raise ValueError(f"Unsupported room feature storage type: {typ}")

    store = bot.db.users.plugin(plugin)
    state = await store.get_global(conf["key"], default={})
    if not isinstance(state, dict):
        state = {}

    default = bool(rooms.PLUGIN_DEFAULTS.get(plugin, False))
    enabled = _coerce_feature_flag(state.get(room_jid), fallback=default)
    return RoomFeatureState(
        name=plugin,
        enabled=enabled,
        default=default,
        modified=enabled != default,
    )


async def get_room_feature(bot: Any, room_jid: str, plugin: str) -> RoomFeatureState:
    plugin = _normalize_plugin_name(plugin)
    if not is_known_feature(plugin):
        raise KeyError(plugin)
    return await _state_for(bot, room_jid, plugin)


async def set_room_feature(bot: Any, room_jid: str, plugin: str, enabled: bool) -> RoomFeatureState:
    rooms = _rooms_module()
    plugin = _normalize_plugin_name(plugin)
    if plugin not in rooms.PLUGIN_STORE_CONFIG:
        raise KeyError(plugin)

    conf = rooms.PLUGIN_STORE_CONFIG[plugin]
    if conf["type"] != "dict":
        raise ValueError(f"Unsupported room feature storage type: {conf['type']}")

    store = bot.db.users.plugin(plugin)
    state = await store.get_global(conf["key"], default={})
    if not isinstance(state, dict):
        state = {}
    state[room_jid] = bool(enabled)
    await store.set_global(conf["key"], state)
    return await _state_for(bot, room_jid, plugin)


async def list_room_features(bot: Any, room_jid: str) -> list[RoomFeatureState]:
    return [await _state_for(bot, room_jid, name) for name in available_features()]


def format_room_feature_line(state: RoomFeatureState) -> str:
    default = "on" if state.default else "off"
    modified = " (modified)" if state.modified else ""
    return f"• {state.name}: {bool_label(state.enabled)} | default: {default}{modified}"
