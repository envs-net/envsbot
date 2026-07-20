"""Split module for core_plugins/rooms.py: defaults."""

from utils.config import config
from utils.room_features import configure_room_features

from .state import (
    _WARNED_ROOM_PLUGIN_DEFAULT_KEYS,
    _maybe_await_result,
    log,
)
PLUGIN_META = {
    "name": "rooms",
    "version": "0.3.0",
    "description": "Database-backed room management",
    "category": "core",
}


INTERNAL_PLUGIN_DEFAULTS = {
    "help": False,
    "birthday_notify": False,
    "ducks": False,
    "karma": False,
    "idlerpg": False,
    "pin": True,
    "poll": False,
    "information": True,
    "dice": True,
    "tell": True,
    "tools": True,
    "translate": True,
    "reminder": True,
    "sed": True,
    "presence": True,
    "urlcheck": True,
    "vcard": True,
    "weather": True,
    "xkcd": False,
    "xmpp": True,
}


PLUGIN_DEFAULTS = INTERNAL_PLUGIN_DEFAULTS


PLUGIN_STORE_CONFIG = {
    "help": {"type": "dict", "key": "HELP"},
    "birthday_notify": {"type": "dict", "key": "birthday_notify"},
    "ducks": {"type": "dict", "key": "DUCKS"},
    "karma": {"type": "dict", "key": "KARMA"},
    "idlerpg": {"type": "dict", "key": "IDLERPG"},
    "pin": {"type": "dict", "key": "PIN"},
    "poll": {"type": "dict", "key": "POLL"},
    "information": {"type": "dict", "key": "INFORMATION"},
    "dice": {"type": "dict", "key": "DICE"},
    "tell": {"type": "dict", "key": "TELL"},
    "tools": {"type": "dict", "key": "TOOLS"},
    "translate": {"type": "dict", "key": "TRANSLATE"},
    "reminder": {"type": "dict", "key": "REMINDER"},
    "sed": {"type": "dict", "key": "SED"},
    "presence": {"type": "dict", "key": "PRESENCE"},
    "urlcheck": {"type": "dict", "key": "URLCHECK"},
    "vcard": {"type": "dict", "key": "VCARD"},
    "weather": {"type": "dict", "key": "WEATHER"},
    "xkcd": {"type": "dict", "key": "XKCD"},
    "xmpp": {"type": "dict", "key": "XMPP"},
}


ROOM_TOGGLE_STORES = tuple(
    (plugin_name, spec["key"])
    for plugin_name, spec in PLUGIN_STORE_CONFIG.items()
    if spec.get("type") == "dict"
)


def _normalize_room_plugin_default_name(name: object) -> str:
    """Return the canonical room plugin default name used internally."""
    value = str(name).strip().lower()
    aliases = {
        "info": "information",
        "infos": "information",
        "roominfo": "information",
    }
    return aliases.get(value, value)


def _coerce_room_plugin_default(value: object, fallback: bool) -> bool:
    """Return a boolean room default with a safe fallback for bad values."""
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

    log.warning(
        "[ROOMS] Ignoring invalid ROOM_PLUGIN_DEFAULTS value %r; "
        "using fallback %s",
        value,
        fallback,
    )
    return fallback


def get_room_plugin_defaults() -> dict[str, bool]:
    """Return effective room plugin defaults with config.py overrides merged in.

    INTERNAL_PLUGIN_DEFAULTS keeps the historic behavior. config.py may override
    selected values through ROOM_PLUGIN_DEFAULTS. Missing keys keep their
    internal defaults and unknown keys are ignored with a warning.
    """
    defaults = INTERNAL_PLUGIN_DEFAULTS.copy()
    configured = config.get("room_plugin_defaults", {})
    if configured in (None, ""):
        return defaults
    if not isinstance(configured, dict):
        log.warning(
            "[ROOMS] Ignoring ROOM_PLUGIN_DEFAULTS because it is %s, not dict",
            type(configured).__name__,
        )
        return defaults

    for raw_name, raw_value in configured.items():
        plugin = _normalize_room_plugin_default_name(raw_name)
        if plugin not in defaults:
            warning_key = str(raw_name)
            if warning_key not in _WARNED_ROOM_PLUGIN_DEFAULT_KEYS:
                _WARNED_ROOM_PLUGIN_DEFAULT_KEYS.add(warning_key)
                log.warning(
                    "[ROOMS] Ignoring unknown ROOM_PLUGIN_DEFAULTS entry: %s",
                    raw_name,
                )
            continue
        defaults[plugin] = _coerce_room_plugin_default(raw_value, defaults[plugin])

    return defaults


configure_room_features(PLUGIN_STORE_CONFIG, get_room_plugin_defaults)


async def _cleanup_room_plugin_state(bot, room_jid: str) -> dict:
    """Remove persistent plugin state that targets a deleted room.

    Room toggle state is still owned by the rooms plugin because it is backed
    by the shared ``PLUGIN_STORE_CONFIG`` table.  Plugin-specific state is
    delegated to loaded plugin lifecycle hooks via
    ``PluginManager.cleanup_room_state()``.
    """
    summary = {
        "toggles": 0,
        "plugin_hooks": {},
    }
    try:
        from .settings import _cleanup_room_toggle_state

        summary["toggles"] = await _cleanup_room_toggle_state(bot, room_jid)

        manager = getattr(bot, "bot_plugins", None)
        cleanup = getattr(manager, "cleanup_room_state", None)
        if callable(cleanup):
            plugin_summary = await _maybe_await_result(cleanup(room_jid))
            if isinstance(plugin_summary, dict):
                summary["plugin_hooks"] = plugin_summary
    except Exception:
        log.warning(
            "[ROOMS] Plugin cleanup failed for deleted room %s",
            room_jid,
            exc_info=True,
        )
    return summary


__all__ = [
    'PLUGIN_META',
    'INTERNAL_PLUGIN_DEFAULTS',
    'PLUGIN_DEFAULTS',
    'PLUGIN_STORE_CONFIG',
    'ROOM_TOGGLE_STORES',
    '_normalize_room_plugin_default_name',
    '_coerce_room_plugin_default',
    'get_room_plugin_defaults',
    '_cleanup_room_plugin_state',
]
