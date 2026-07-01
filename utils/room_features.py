"""Shared API for room-scoped plugin feature toggles."""

from __future__ import annotations

import asyncio
import logging
import threading
import types
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Mapping, Protocol, TypeAlias, TypedDict

from utils.formatting import bool_label

log = logging.getLogger(__name__)

FeatureFlagValue: TypeAlias = bool | int | float | str | None
FeatureFlagMap: TypeAlias = Mapping[str, FeatureFlagValue]
FeatureFlagState: TypeAlias = dict[str, bool]
StoreValue: TypeAlias = FeatureFlagMap | FeatureFlagState | None
StoreUpdater: TypeAlias = Callable[[StoreValue], FeatureFlagState]
RawPluginStoreConfig: TypeAlias = Mapping[str, Any]


class PluginStore(Protocol):
    async def get_global(
        self, key: str, default: StoreValue = None
    ) -> StoreValue:
        pass

    async def set_global(self, key: str, value: FeatureFlagState) -> None:
        pass

    async def update_global(
        self,
        key: str,
        updater: StoreUpdater,
        default: StoreValue = None,
    ) -> FeatureFlagState:
        pass


class PluginUsers(Protocol):
    def plugin(self, name: str) -> PluginStore:
        pass


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


_ROOMS_MODULE: types.ModuleType | None = None
_ROOMS_MODULE_LOCK = threading.Lock()
_ROOMS_MODULE_ASYNC_LOCK: asyncio.Lock | None = None


def _rooms_module() -> types.ModuleType:
    """Lazily import and cache the rooms module for synchronous callers.

    Importing ``core_plugins.rooms`` only when room feature metadata is needed
    avoids circular imports during plugin discovery and initialization, where
    the rooms plugin imports room-feature helpers from this module. The
    synchronous lock keeps the cache safe for CLI/docs helpers that call this
    module outside an async task. Async room-feature operations use
    ``_rooms_module_async()`` so concurrent coroutines also wait on an
    ``asyncio.Lock``.

    Call ``clear_room_feature_caches()`` when the rooms module is reloaded or
    its feature metadata changes at runtime, for example during tests, hot
    reloads, or config reloads.
    """
    global _ROOMS_MODULE
    with _ROOMS_MODULE_LOCK:
        if _ROOMS_MODULE is None:
            from core_plugins import rooms

            _ROOMS_MODULE = rooms
        module = _ROOMS_MODULE
    return module


async def _rooms_module_async() -> types.ModuleType:
    """Lazily import and cache the rooms module for async callers.

    Multiple room-feature coroutines may request metadata at the same time.
    This helper uses an ``asyncio.Lock`` in addition to the synchronous cache
    lock so those coroutines do not race while the rooms module is imported or
    the cached reference is initialized. The async lock itself is created
    lazily under the synchronous lock to avoid module-level event-loop state.
    """
    module = _ROOMS_MODULE
    if module is not None:
        return module

    global _ROOMS_MODULE_ASYNC_LOCK
    with _ROOMS_MODULE_LOCK:
        if _ROOMS_MODULE_ASYNC_LOCK is None:
            _ROOMS_MODULE_ASYNC_LOCK = asyncio.Lock()
        async_lock = _ROOMS_MODULE_ASYNC_LOCK

    async with async_lock:
        return _rooms_module()


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


def _coerce_feature_flag(
    value: FeatureFlagValue, fallback: bool = False
) -> bool:
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


def _load_raw_plugin_store_config() -> RawPluginStoreConfig | None:
    """Return raw room plugin storage config from the rooms module.

    ``None`` is returned when the rooms module does not expose a mapping named
    ``PLUGIN_STORE_CONFIG``. The returned value is intentionally still raw;
    validation and normalization are handled by
    ``_validated_plugin_store_config()``.
    """
    raw_config = getattr(_rooms_module(), "PLUGIN_STORE_CONFIG", None)
    if isinstance(raw_config, Mapping):
        return raw_config
    if raw_config is not None:
        log.warning(
            "[ROOM_FEATURES] Ignoring PLUGIN_STORE_CONFIG with invalid type: "
            "%s",
            type(raw_config).__name__,
        )
    return None


async def _load_raw_plugin_store_config_async() -> RawPluginStoreConfig | None:
    """Return raw room plugin storage config for async callers."""
    raw_config = getattr(
        await _rooms_module_async(), "PLUGIN_STORE_CONFIG", None
    )
    if isinstance(raw_config, Mapping):
        return raw_config
    if raw_config is not None:
        log.warning(
            "[ROOM_FEATURES] Ignoring PLUGIN_STORE_CONFIG with invalid type: "
            "%s",
            type(raw_config).__name__,
        )
    return None


def _validate_plugin_store_config(
    config: RawPluginStoreConfig | None,
) -> dict[str, RoomFeatureConfig]:
    """Validate and normalize a raw plugin store config mapping."""
    if config is None:
        return {}

    validated: dict[str, RoomFeatureConfig] = {}
    for raw_name, raw_conf in config.items():
        if not isinstance(raw_name, str):
            log.warning(
                "[ROOM_FEATURES] Ignoring feature config with non-string "
                "plugin name: %r",
                raw_name,
            )
            continue
        if not isinstance(raw_conf, Mapping):
            log.warning(
                "[ROOM_FEATURES] Ignoring feature config for %r because "
                "the config is not a mapping: %r",
                raw_name,
                raw_conf,
            )
            continue
        storage_type = raw_conf.get("type")
        key = raw_conf.get("key")
        if not isinstance(storage_type, str):
            log.warning(
                "[ROOM_FEATURES] Ignoring feature config for %r because "
                "storage type is invalid: %r",
                raw_name,
                storage_type,
            )
            continue
        if not isinstance(key, str) or not key:
            log.warning(
                "[ROOM_FEATURES] Ignoring feature config for %r because "
                "storage key is missing or invalid: %r",
                raw_name,
                key,
            )
            continue
        name = _normalize_plugin_name(raw_name)
        if not name:
            log.warning(
                "[ROOM_FEATURES] Ignoring feature config with empty "
                "normalized plugin name from %r",
                raw_name,
            )
            continue
        validated[name] = {"type": storage_type, "key": key}
    return validated


def _validated_plugin_store_config() -> dict[str, RoomFeatureConfig]:
    """Validate and normalize plugin storage configuration.

    Invalid entries are ignored after logging a warning. Valid entries must use
    a string plugin name, a mapping config, a non-empty string ``key``, and a
    string ``type``. The returned mapping is keyed by canonical plugin names.
    """
    return _validate_plugin_store_config(_load_raw_plugin_store_config())


async def _validated_plugin_store_config_async() -> (
    dict[str, RoomFeatureConfig]
):
    """Validate and normalize plugin storage config for async callers."""
    return _validate_plugin_store_config(
        await _load_raw_plugin_store_config_async()
    )


def _validate_feature_config(
    plugin: str,
    config: Mapping[str, RoomFeatureConfig],
) -> RoomFeatureConfig:
    """Return validated storage config for one normalized plugin."""
    plugin = _normalize_plugin_name(plugin)
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


def _feature_config(plugin: str) -> RoomFeatureConfig:
    """Return validated storage config for one plugin feature."""
    return _validate_feature_config(
        plugin,
        _validated_plugin_store_config(),
    )


async def _feature_config_async(plugin: str) -> RoomFeatureConfig:
    """Return validated storage config for one plugin in async code."""
    return _validate_feature_config(
        plugin,
        await _validated_plugin_store_config_async(),
    )


def _defaults_from_rooms_module(
    rooms: types.ModuleType,
) -> Mapping[str, FeatureFlagValue] | None:
    """Return raw default mapping exposed by a rooms module instance."""
    defaults_provider = getattr(rooms, "get_room_plugin_defaults", None)
    if callable(defaults_provider):
        raw_defaults = defaults_provider()
        if isinstance(raw_defaults, Mapping):
            return raw_defaults
        log.warning(
            "[ROOM_FEATURES] Ignoring get_room_plugin_defaults() result "
            "with invalid type: %s",
            type(raw_defaults).__name__,
        )
        return None

    raw_defaults = getattr(rooms, "PLUGIN_DEFAULTS", None)
    if isinstance(raw_defaults, Mapping):
        return raw_defaults
    if raw_defaults is not None:
        log.warning(
            "[ROOM_FEATURES] Ignoring PLUGIN_DEFAULTS with invalid type: %s",
            type(raw_defaults).__name__,
        )
    return None


def _room_plugin_defaults_source() -> Mapping[str, FeatureFlagValue] | None:
    """Return raw default mapping from the rooms module.

    ``get_room_plugin_defaults()`` is preferred because it can merge
    ``config.py`` overrides with built-in defaults. ``PLUGIN_DEFAULTS`` remains
    supported for older rooms modules. Non-mapping providers are logged and
    treated as missing defaults.
    """
    return _defaults_from_rooms_module(_rooms_module())


async def _room_plugin_defaults_source_async() -> (
    Mapping[str, FeatureFlagValue] | None
):
    """Return raw default mapping from the rooms module in async code."""
    return _defaults_from_rooms_module(await _rooms_module_async())


def _validate_plugin_defaults(
    defaults: Mapping[str, FeatureFlagValue] | None,
) -> FeatureFlagState:
    """Normalize a raw room plugin defaults mapping."""
    if defaults is None:
        return {}

    validated: FeatureFlagState = {}
    for name, value in defaults.items():
        normalized_name = _normalize_plugin_name(str(name))
        if not normalized_name:
            log.warning(
                "[ROOM_FEATURES] Ignoring default for empty plugin name "
                "from %r",
                name,
            )
            continue
        try:
            validated[normalized_name] = _coerce_feature_flag(value)
        except TypeError as exc:
            log.warning(
                "[ROOM_FEATURES] Ignoring invalid default for plugin %r: "
                "%r (%s)",
                normalized_name,
                value,
                exc,
            )
    return validated


def _resolved_plugin_defaults() -> FeatureFlagState:
    """Return validated room plugin defaults from the rooms module.

    Values are normalized to booleans and malformed entries are skipped with a
    warning instead of invalidating the whole mapping. The result is
    intentionally not cached here because the underlying defaults can change at
    runtime after ``config reload``. Callers that need to reuse defaults across
    multiple feature lookups should pass one resolved mapping through the
    current operation.
    """
    return _validate_plugin_defaults(_room_plugin_defaults_source())


async def _resolved_plugin_defaults_async() -> FeatureFlagState:
    """Return validated room plugin defaults in async code."""
    return _validate_plugin_defaults(
        await _room_plugin_defaults_source_async()
    )


def clear_room_feature_caches() -> None:
    """Clear cached room feature module lookups.

    This function is thread-safe: it acquires ``_ROOMS_MODULE_LOCK`` before
    resetting cached module state. Call this when the rooms module or its
    feature metadata may have changed at runtime, for example in tests, bot
    reloads, or config reloads. The async cache lock is also reset so the next
    async lookup creates a lock bound to the currently running event loop.
    """
    global _ROOMS_MODULE, _ROOMS_MODULE_ASYNC_LOCK
    with _ROOMS_MODULE_LOCK:
        _ROOMS_MODULE = None
        _ROOMS_MODULE_ASYNC_LOCK = None


def available_features() -> list[str]:
    """Return all configured room-feature names in sorted order."""
    return sorted(_validated_plugin_store_config())


def is_known_feature(plugin: str) -> bool:
    """Return whether a plugin name or alias is a configured feature."""
    return _normalize_plugin_name(plugin) in _validated_plugin_store_config()


def _coerce_supported_feature_value(
    value: FeatureFlagValue,
) -> bool | None:
    """Return a normalized feature flag, or ``None`` for invalid values."""
    try:
        return _coerce_feature_flag(value)
    except TypeError:
        return None


def _safe_room_feature_state(
    state: FeatureFlagMap,
) -> FeatureFlagState:
    """Return a sanitized room-feature state mapping.

    Plugin stores may contain arbitrary keys or values from older versions,
    manual edits, or corrupted data. Keep only string room IDs with values that
    can be normalized by ``_coerce_feature_flag`` and ignore everything else.
    Accepted values are stored as booleans so downstream callers work with a
    consistent representation. Malformed keys or values are logged with their
    offending key so operators can clean up damaged runtime state.
    """
    safe_state: FeatureFlagState = {}
    for key, value in state.items():
        if not isinstance(key, str):
            log.warning(
                "[ROOM_FEATURES] Ignoring room feature state with "
                "non-string room id: %r",
                key,
            )
            continue
        coerced = _coerce_supported_feature_value(value)
        if coerced is None:
            log.warning(
                "[ROOM_FEATURES] Ignoring invalid room feature state for "
                "room %r: %r",
                key,
                value,
            )
            continue
        safe_state[key] = coerced
    return safe_state


async def _room_feature_map(
    bot: BotProtocol,
    plugin: str,
    conf: RoomFeatureConfig,
) -> FeatureFlagState:
    """Fetch and sanitize the stored room-feature map for a plugin.

    The configured store key is expected to contain a dictionary mapping
    room JIDs to raw feature-flag values. Missing, non-mapping, or malformed
    state is treated as empty so callers can safely fall back to configured
    defaults.
    """
    store = bot.db.users.plugin(plugin)
    state = await store.get_global(conf["key"], default={})
    if not isinstance(state, Mapping):
        if state is not None:
            log.warning(
                "[ROOM_FEATURES] Ignoring non-mapping feature state for "
                "plugin %r key %r: %r",
                plugin,
                conf["key"],
                state,
            )
        return {}
    return _safe_room_feature_state(state)


async def _state_for(
    bot: BotProtocol,
    room_jid: str,
    plugin: str,
    defaults: FeatureFlagState,
) -> RoomFeatureState:
    """Compute the effective feature state for one plugin in one room.

    Args:
        bot: Bot instance providing access to the plugin runtime store.
        room_jid: Room identifier whose stored override should be resolved.
        plugin: Plugin feature name to resolve; aliases are normalized.
        defaults: Pre-resolved per-plugin default flags for the current
            request. Callers pass this mapping in so operations that resolve
            multiple features can compute defaults once and use a consistent
            snapshot across all returned states.

    Returns:
        A ``RoomFeatureState`` combining the stored room override with the
        resolved default, including whether the effective value differs from
        that default.
    """
    plugin = _normalize_plugin_name(plugin)
    conf = await _feature_config_async(plugin)
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
    """Return the effective state for one room-scoped plugin feature.

    The plugin name is normalized, room-specific stored state is loaded from
    the configured plugin runtime store, and the result is combined with the
    current resolved defaults.
    """
    defaults = await _resolved_plugin_defaults_async()
    return await _state_for(bot, room_jid, plugin, defaults=defaults)


def _updated_feature_state(
    current: FeatureFlagMap | None, *, room_jid: str, enabled: bool
) -> FeatureFlagState:
    """Return feature state with one room flag updated.

    ``update_global`` passes the current stored value into this helper. The
    value may be missing or malformed, so it is sanitized before the requested
    room flag is written. ``room_jid`` and ``enabled`` are keyword-only so
    callers can bind them explicitly with ``functools.partial``.
    """
    current_state = (
        _safe_room_feature_state(current)
        if isinstance(current, Mapping)
        else {}
    )
    current_state[room_jid] = bool(enabled)
    return current_state


async def set_room_feature(
    bot: BotProtocol, room_jid: str, plugin: str, enabled: bool
) -> RoomFeatureState:
    """Persist a room-specific plugin feature override.

    Updates are delegated to the plugin runtime store via ``update_global`` so
    the backend can serialize or atomically apply read-modify-write changes.
    The returned state reflects the persisted override combined with the
    current resolved defaults.
    """
    plugin = _normalize_plugin_name(plugin)
    conf = await _feature_config_async(plugin)
    store = bot.db.users.plugin(plugin)
    updater = partial(
        _updated_feature_state,
        room_jid=room_jid,
        enabled=enabled,
    )

    await store.update_global(conf["key"], updater, default={})

    defaults = await _resolved_plugin_defaults_async()
    return await _state_for(bot, room_jid, plugin, defaults=defaults)


async def _state_for_list_entry(
    bot: BotProtocol,
    room_jid: str,
    plugin: str,
    defaults: FeatureFlagState,
) -> RoomFeatureState:
    """Return one listed feature state with contextual error reporting."""
    try:
        return await _state_for(bot, room_jid, plugin, defaults=defaults)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to fetch room feature state for {plugin!r} "
            f"in room {room_jid!r}"
        ) from exc


async def list_room_features(
    bot: BotProtocol,
    room_jid: str,
) -> list[RoomFeatureState]:
    """Return all configured room-feature states for one room.

    Plugin storage configuration and defaults are resolved once for this list
    operation, then each feature state is fetched concurrently. Errors are
    wrapped with the affected plugin and room to make broken feature metadata
    easier to diagnose.
    """
    names = sorted(await _validated_plugin_store_config_async())
    defaults = await _resolved_plugin_defaults_async()
    coroutines = [
        _state_for_list_entry(bot, room_jid, name, defaults=defaults)
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
