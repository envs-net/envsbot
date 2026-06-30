"""Shared API for room-scoped plugin feature toggles."""

from __future__ import annotations

import asyncio
import threading
import types
import weakref
from dataclasses import dataclass
from functools import cache
from typing import Any, Mapping, Protocol, TypedDict

from utils.formatting import bool_label


class PluginStore(Protocol):
    async def get_global(self, key: str, default: object = None) -> object:
        pass

    async def set_global(self, key: str, value: object) -> None:
        pass


class PluginUsers(Protocol):
    def plugin(self, name: str) -> PluginStore:
        pass


class RoomFeatureDatabase(Protocol):
    users: PluginUsers


class BotProtocol(Protocol):
    db: RoomFeatureDatabase


_FEATURE_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)
_FEATURE_LOCKS_GUARD = threading.Lock()


def _feature_lock(plugin: str, key: str) -> asyncio.Lock:
    """Return the shared lock for one plugin storage key.

    Room feature updates use read-modify-write storage. A lock per
    ``plugin:key`` pair prevents concurrent writers from losing room-specific
    updates while still allowing unrelated plugin stores to update in parallel.
    Existing locks are returned without acquiring the registry guard; the guard
    is only needed when a lock might have to be created.
    """
    lock_id = f"{plugin}:{key}"
    lock = _FEATURE_LOCKS.get(lock_id)
    if lock is not None:
        return lock

    with _FEATURE_LOCKS_GUARD:
        lock = _FEATURE_LOCKS.get(lock_id)
        if lock is None:
            lock = asyncio.Lock()
            _FEATURE_LOCKS[lock_id] = lock
        return lock


class RoomFeatureConfig(TypedDict):
    type: str
    key: str


@dataclass(frozen=True)
class RoomFeatureState:
    name: str
    enabled: bool
    default: bool
    modified: bool


@cache
def _rooms_module() -> types.ModuleType:
    """Lazily import and cache the rooms module.

    Importing ``core_plugins.rooms`` only when room feature metadata is needed
    avoids circular imports during plugin discovery. The cache ensures all
    later lookups reuse the same module object.
    """
    from core_plugins import rooms

    return rooms


def _normalize_plugin_name(name: str) -> str:
    """Return the canonical feature name for user or config input.

    Names are lowercased, stripped, and mapped through known aliases so callers
    can use legacy names such as ``info`` or ``roominfo`` interchangeably with
    the canonical plugin name.
    """
    value = str(name).strip().lower()
    aliases = {
        "info": "information",
        "infos": "information",
        "roominfo": "information",
    }
    return aliases.get(value, value)


def _coerce_feature_flag(value: object, fallback: bool = False) -> bool:
    """Coerce a stored feature flag value to ``bool``.

    ``fallback`` is returned only when ``value`` is ``None``. Accepted inputs
    are booleans, numeric values, numeric strings, empty strings, and common
    truthy/falsy string literals such as ``yes/no`` or ``enabled/disabled``.

    Raises:
        TypeError: If ``value`` cannot be interpreted as a supported feature
            flag value.
    """
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
        try:
            return bool(float(normalized))
        except ValueError:
            pass
    raise TypeError(
        f"Unsupported feature flag value: {value!r} "
        f"(type: {type(value).__name__}). "
        "Expected bool, int, float, numeric string, or one of: "
        "true/false, yes/no, on/off, enabled/disabled, 1/0."
    )


def _raw_plugin_store_config() -> dict[str, Any] | None:
    """Return raw room plugin storage config from the rooms module.

    ``None`` is returned when the rooms module does not expose a dictionary
    named ``PLUGIN_STORE_CONFIG`` so validation can treat missing or malformed
    configuration as an empty feature list.
    """
    raw_config = getattr(_rooms_module(), "PLUGIN_STORE_CONFIG", None)
    if not isinstance(raw_config, dict):
        return None
    return raw_config


def _plugin_store_config() -> dict[str, RoomFeatureConfig]:
    """Validate and normalize the raw plugin store configuration.

    Invalid entries are ignored. Valid entries must use a string plugin name, a
    mapping config, a non-empty string ``key``, and a string ``type``. The
    returned mapping is keyed by canonical plugin names.
    """
    config = _raw_plugin_store_config()
    if config is None:
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
        available = sorted(config)
        options = ", ".join(available) if available else "<none configured>"
        raise KeyError(
            f"Unknown plugin feature: {plugin}. "
            f"Available features: {options}. "
            "Use available_features() to inspect configured options."
        )

    conf = config[plugin]
    typ = conf["type"]
    if typ != "dict":
        raise ValueError(
            f"Unsupported room feature storage type: {typ}. "
            "Only 'dict' is currently supported."
        )
    return conf


@cache
def _cached_plugin_defaults() -> dict[str, bool]:
    """Return validated room plugin defaults from the rooms module.

    ``get_room_plugin_defaults()`` is preferred because it can merge
    config.py overrides with built-in defaults. ``PLUGIN_DEFAULTS`` remains
    supported for older room modules. Values are normalized to booleans and
    malformed entries are skipped instead of invalidating the whole mapping.
    """
    rooms = _rooms_module()
    defaults_fn = getattr(rooms, "get_room_plugin_defaults", None)
    if callable(defaults_fn):
        raw_defaults = defaults_fn()
        defaults = raw_defaults if isinstance(raw_defaults, dict) else None
    else:
        defaults = getattr(rooms, "PLUGIN_DEFAULTS", None)
    if not isinstance(defaults, dict):
        return {}

    validated: dict[str, bool] = {}
    for name, value in defaults.items():
        normalized_name = _normalize_plugin_name(str(name))
        if not normalized_name:
            continue
        try:
            validated[normalized_name] = _coerce_feature_flag(value)
        except TypeError:
            continue
    return validated


def _plugin_defaults() -> dict[str, bool]:
    # Return a copy so callers cannot mutate cached defaults.
    return dict(_cached_plugin_defaults())


def clear_room_feature_caches() -> None:
    """Clear cached room feature module/default lookups."""
    _rooms_module.cache_clear()
    _cached_plugin_defaults.cache_clear()


def available_features() -> list[str]:
    return sorted(_plugin_store_config())


def is_known_feature(plugin: str) -> bool:
    return _normalize_plugin_name(plugin) in _plugin_store_config()


def _is_supported_feature_value(value: object) -> bool:
    try:
        _coerce_feature_flag(value)
    except TypeError:
        return False
    return True


def _safe_room_feature_state(
    state: Mapping[object, object],
) -> dict[str, object]:
    """Return a sanitized room-feature state mapping.

    Plugin stores may contain arbitrary keys or values from older versions,
    manual edits, or corrupted data. Keep only string room IDs with scalar
    feature-flag values accepted by ``_coerce_feature_flag`` and ignore
    everything else.
    """
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
    """Fetch and sanitize the stored room-feature map for a plugin.

    The configured store key is expected to contain a dictionary mapping
    room JIDs to raw feature-flag values. Missing, non-dictionary, or
    malformed state is treated as empty so callers can safely fall back to
    configured defaults.
    """
    store = bot.db.users.plugin(plugin)
    state = await store.get_global(conf["key"], default={})
    if not isinstance(state, dict):
        return {}
    return _safe_room_feature_state(state)


async def _state_for(
    bot: BotProtocol,
    room_jid: str,
    plugin: str,
    defaults: dict[str, bool],
) -> RoomFeatureState:
    """Compute the effective feature state for one plugin in one room.

    ``defaults`` contains the already-resolved plugin defaults for this
    request. The returned state combines the stored room-specific override
    with that default and marks whether the effective value differs from the
    default.
    """
    plugin = _normalize_plugin_name(plugin)
    conf = _feature_config(plugin)
    state = await _room_feature_map(bot, plugin, conf)
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
    defaults = _plugin_defaults()
    return await _state_for(bot, room_jid, plugin, defaults=defaults)


async def set_room_feature(
    bot: BotProtocol, room_jid: str, plugin: str, enabled: bool
) -> RoomFeatureState:
    plugin = _normalize_plugin_name(plugin)
    conf = _feature_config(plugin)

    async with _feature_lock(plugin, conf["key"]):
        stored_state = await _room_feature_map(bot, plugin, conf)
        # Work on an explicit copy so future store implementations can safely
        # return cached/shared mappings without caller-side mutation.
        current_state = dict(stored_state)
        current_state[room_jid] = bool(enabled)

        store = bot.db.users.plugin(plugin)
        await store.set_global(conf["key"], current_state)

    defaults = _plugin_defaults()
    return await _state_for(bot, room_jid, plugin, defaults=defaults)


async def list_room_features(
    bot: BotProtocol,
    room_jid: str,
) -> list[RoomFeatureState]:
    names = available_features()
    defaults = _plugin_defaults()
    coroutines = [
        _state_for(bot, room_jid, name, defaults=defaults)
        for name in names
    ]
    return list(await asyncio.gather(*coroutines))


def format_room_feature_line(state: RoomFeatureState) -> str:
    default = "on" if state.default else "off"
    modified = " (modified)" if state.modified else ""
    return (
        f"• {state.name}: {bool_label(state.enabled)} "
        f"| default: {default}{modified}"
    )
