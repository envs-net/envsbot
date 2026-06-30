"""Shared API for room-scoped plugin feature toggles."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, TypedDict

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


class RoomFeatureConfig(TypedDict):
    type: str
    key: str


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
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return False
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    raise TypeError(
        "Unsupported feature flag value type: "
        f"{type(value).__name__}"
    )


def _raw_plugin_store_config() -> object:
    return getattr(_rooms_module(), "PLUGIN_STORE_CONFIG", None)


def _plugin_store_config() -> dict[str, RoomFeatureConfig]:
    config = _raw_plugin_store_config()
    if not isinstance(config, dict):
        return {}

    validated: dict[str, RoomFeatureConfig] = {}
    for raw_name, raw_conf in config.items():
        if not isinstance(raw_name, str) or not isinstance(raw_conf, dict):
            continue
        storage_type = raw_conf.get("type")
        key = raw_conf.get("key")
        if (
            not isinstance(storage_type, str)
            or not isinstance(key, str)
            or not key
        ):
            continue
        name = _normalize_plugin_name(raw_name)
        if not name:
            continue
        validated[name] = {"type": storage_type, "key": key}
    return validated


def _feature_config(plugin: str) -> RoomFeatureConfig:
    plugin = _normalize_plugin_name(plugin)
    config = _plugin_store_config()
    if plugin not in config:
        raise KeyError(f"Unknown plugin feature: {plugin}")

    conf = config[plugin]
    typ = conf["type"]
    if typ != "dict":
        raise ValueError(f"Unsupported room feature storage type: {typ}")
    return conf


def _plugin_defaults() -> dict[str, bool]:
    rooms = _rooms_module()
    defaults_fn = getattr(rooms, "get_room_plugin_defaults", None)
    if callable(defaults_fn):
        defaults = defaults_fn()
    else:
        defaults = getattr(rooms, "PLUGIN_DEFAULTS", None)
    if not isinstance(defaults, dict):
        return {}
    return {
        _normalize_plugin_name(str(name)): _coerce_feature_flag(value)
        for name, value in defaults.items()
    }


def available_features() -> list[str]:
    return sorted(_plugin_store_config())


def is_known_feature(plugin: str) -> bool:
    return _normalize_plugin_name(plugin) in available_features()


def _is_supported_feature_value(value: object) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _safe_room_feature_state(state: dict[object, object]) -> dict[str, object]:
    safe_state: dict[str, object] = {}
    for key, value in state.items():
        if not isinstance(key, str):
            continue
        if not _is_supported_feature_value(value):
            continue
        safe_state[key] = value
    return safe_state


async def _room_feature_map(
    bot: BotProtocol,
    plugin: str,
    conf: RoomFeatureConfig,
) -> dict[str, object]:
    store = bot.db.users.plugin(plugin)
    state = await store.get_global(conf["key"], default={})
    if not isinstance(state, dict):
        return {}
    return _safe_room_feature_state(state)


async def _state_for(
    bot: BotProtocol,
    room_jid: str,
    plugin: str,
    defaults: dict[str, bool] | None = None,
) -> RoomFeatureState:
    plugin = _normalize_plugin_name(plugin)
    conf = _feature_config(plugin)
    state = await _room_feature_map(bot, plugin, conf)
    if defaults is None:
        defaults = _plugin_defaults()
    default = defaults.get(plugin, False)
    enabled = _coerce_feature_flag(state.get(room_jid), fallback=default)
    return RoomFeatureState(
        name=plugin,
        enabled=enabled,
        default=default,
        modified=enabled != default,
    )


async def get_room_feature(
    bot: BotProtocol, room_jid: str, plugin: str
) -> RoomFeatureState:
    return await _state_for(bot, room_jid, plugin)


async def set_room_feature(
    bot: BotProtocol, room_jid: str, plugin: str, enabled: bool
) -> RoomFeatureState:
    plugin = _normalize_plugin_name(plugin)
    conf = _feature_config(plugin)
    state = await _room_feature_map(bot, plugin, conf)
    state[room_jid] = bool(enabled)

    store = bot.db.users.plugin(plugin)
    await store.set_global(conf["key"], state)
    return await _state_for(bot, room_jid, plugin)


async def list_room_features(
    bot: BotProtocol,
    room_jid: str,
) -> list[RoomFeatureState]:
    names = available_features()
    defaults = _plugin_defaults()
    coros = [
        _state_for(bot, room_jid, name, defaults=defaults)
        for name in names
    ]
    return list(await asyncio.gather(*coros))


def format_room_feature_line(state: RoomFeatureState) -> str:
    default = "on" if state.default else "off"
    modified = " (modified)" if state.modified else ""
    return (
        f"• {state.name}: {bool_label(state.enabled)} "
        f"| default: {default}{modified}"
    )
