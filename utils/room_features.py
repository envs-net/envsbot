"""Shared API for room-scoped plugin feature toggles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from utils.formatting import bool_label


class PluginStore(Protocol):
    async def get_global(self, key: str, default: object = None) -> object:
        raise NotImplementedError

    async def set_global(self, key: str, value: object) -> None:
        raise NotImplementedError


class PluginUsers(Protocol):
    def plugin(self, name: str) -> PluginStore:
        raise NotImplementedError


class RoomFeatureDatabase(Protocol):
    users: PluginUsers


class BotProtocol(Protocol):
    db: RoomFeatureDatabase


RoomFeatureConfig = dict[str, object]


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


def _coerce_feature_flag(value: object, fallback: bool = False) -> bool:
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


def _plugin_store_config() -> dict[str, RoomFeatureConfig]:
    rooms = _rooms_module()
    config = getattr(rooms, "PLUGIN_STORE_CONFIG", None)
    if not isinstance(config, dict):
        return {}
    return cast(dict[str, RoomFeatureConfig], config)


def _plugin_defaults() -> dict[str, bool]:
    rooms = _rooms_module()
    defaults_fn = getattr(rooms, "get_room_plugin_defaults", None)
    if callable(defaults_fn):
        defaults = defaults_fn()
    else:
        defaults = getattr(rooms, "PLUGIN_DEFAULTS", None)
    if not isinstance(defaults, dict):
        return {}
    return cast(dict[str, bool], defaults)


def available_features() -> list[str]:
    return sorted(_plugin_store_config())


def is_known_feature(plugin: str) -> bool:
    return _normalize_plugin_name(plugin) in available_features()


async def _state_for(bot: BotProtocol, room_jid: str, plugin: str) -> RoomFeatureState:
    plugin = _normalize_plugin_name(plugin)
    config = _plugin_store_config()
    if plugin not in config:
        raise KeyError(f"Unknown plugin feature: {plugin}")
    conf = config[plugin]
    typ = conf["type"]
    if typ != "dict":
        raise ValueError(f"Unsupported room feature storage type: {typ}")

    store = bot.db.users.plugin(plugin)
    state = await store.get_global(cast(str, conf["key"]), default={})
    if not isinstance(state, dict):
        state = {}

    default = bool(_plugin_defaults().get(plugin, False))
    enabled = _coerce_feature_flag(state.get(room_jid), fallback=default)
    return RoomFeatureState(
        name=plugin,
        enabled=enabled,
        default=default,
        modified=enabled != default,
    )


async def get_room_feature(bot: BotProtocol, room_jid: str, plugin: str) -> RoomFeatureState:
    plugin = _normalize_plugin_name(plugin)
    if not is_known_feature(plugin):
        raise KeyError(plugin)
    return await _state_for(bot, room_jid, plugin)


async def set_room_feature(bot: BotProtocol, room_jid: str, plugin: str, enabled: bool) -> RoomFeatureState:
    plugin = _normalize_plugin_name(plugin)
    config = _plugin_store_config()
    if plugin not in config:
        raise KeyError(f"Unknown plugin feature: {plugin}")

    conf = config[plugin]
    if conf["type"] != "dict":
        raise ValueError(f"Unsupported room feature storage type: {conf['type']}")

    store = bot.db.users.plugin(plugin)
    state = await store.get_global(cast(str, conf["key"]), default={})
    if not isinstance(state, dict):
        state = {}
    state[room_jid] = bool(enabled)
    await store.set_global(cast(str, conf["key"]), state)
    return await _state_for(bot, room_jid, plugin)


async def list_room_features(bot: BotProtocol, room_jid: str) -> list[RoomFeatureState]:
    return [await _state_for(bot, room_jid, name) for name in available_features()]


def format_room_feature_line(state: RoomFeatureState) -> str:
    default = "on" if state.default else "off"
    modified = " (modified)" if state.modified else ""
    return f"• {state.name}: {bool_label(state.enabled)} | default: {default}{modified}"
