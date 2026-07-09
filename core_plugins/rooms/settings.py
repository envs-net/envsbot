"""Split module for core_plugins/rooms.py: settings."""

from utils.audit import audit_event
from utils.room_features import format_room_feature_line, get_room_feature, set_room_feature

from .defaults import (
    PLUGIN_STORE_CONFIG,
    ROOM_TOGGLE_STORES,
    _normalize_room_plugin_default_name,
    get_room_plugin_defaults,
)
from .presence import _resolve_room_settings_target
from .state import _get_plugin_store, _room_matches, _store_get_global, _store_set_global, log


async def _cleanup_room_toggle_state(bot, room_jid: str) -> int:
    """Remove room-scoped on/off entries from all known plugin stores."""
    removed = 0
    for plugin_name, key in ROOM_TOGGLE_STORES:
        store = _get_plugin_store(bot, plugin_name)
        if store is None:
            continue
        try:
            state = await _store_get_global(store, key, default={})
            if not isinstance(state, dict):
                continue
            matching_key = next(
                (item for item in state if _room_matches(item, room_jid)),
                None,
            )
            if matching_key is None:
                continue
            state.pop(matching_key, None)
            await _store_set_global(store, key, state)
            removed += 1
        except Exception:
            log.warning(
                "[ROOMS] Could not clean %s room state for %s",
                plugin_name,
                room_jid,
                exc_info=True,
            )
    return removed


async def set_room_control_defaults(bot, room_jid, defaults=None):
    """
    Reset all plugin room controls to their configured defaults.

    Important:
    The storage key is not always the plugin name. Use the configured
    PLUGIN_STORE_CONFIG[plugin]["key"] for get_global/set_global.
    """
    if defaults is None:
        defaults = get_room_plugin_defaults()

    for plugin, should_enable in defaults.items():
        plugin = _normalize_room_plugin_default_name(plugin)
        if plugin not in PLUGIN_STORE_CONFIG:
            log.warning("[ROOMS] Ignoring unknown room plugin default: %s", plugin)
            continue
        conf = PLUGIN_STORE_CONFIG[plugin]
        typ = conf["type"]
        key = conf["key"]
        store = bot.db.users.plugin(plugin)

        if typ == "dict":
            state = await store.get_global(key, default={})
            if not isinstance(state, dict):
                state = {}

            if should_enable:
                state[room_jid] = True
            else:
                state.pop(room_jid, None)

            log.info(f"[ROOMS][DICT] Setting defaults for plugin '{
                     plugin}' key '{key}': {state}")
            await store.set_global(key, state)

        elif typ == "list":
            list_field = conf.get("list_field", "rooms")
            state = await store.get_global(key, default={list_field: []})
            if not isinstance(state, dict):
                state = {list_field: []}

            rooms = state.get(list_field, [])
            if not isinstance(rooms, list):
                rooms = []

            if should_enable:
                if room_jid not in rooms:
                    rooms.append(room_jid)
            else:
                if room_jid in rooms:
                    rooms.remove(room_jid)

            state[list_field] = rooms

            log.info(f"[ROOMS][LIST] Setting defaults for plugin '{
                     plugin}' key '{key}': {rooms}")
            await store.set_global(key, state)

        else:
            raise ValueError(f"Unsupported storage type: {
                             typ} for plugin {plugin}")


async def _handle_room_feature_toggle(bot, sender_jid, msg, is_room, args, *, enabled: bool):
    """Shared implementation for rooms enable/disable."""
    action = "enable" if enabled else "disable"
    usage = f"{bot.prefix}rooms {action} [<room_jid>] <plugin>"
    resolved = await _resolve_room_settings_target(bot, msg, is_room, args, sender_jid, usage)
    if resolved is None:
        return
    room_jid, remaining = resolved
    if len(remaining) != 1:
        bot.reply_usage(msg, usage)
        return

    plugin = remaining[0].lower()
    try:
        previous = await get_room_feature(bot, room_jid, plugin)
        state = await set_room_feature(bot, room_jid, plugin, enabled)
    except KeyError:
        bot.reply_warn(
            msg,
            f"Unknown room plugin '{plugin}'. Use {bot.prefix}rooms plugins {room_jid} to list valid names.",
        )
        return

    if previous.enabled == state.enabled:
        bot.reply_info(msg, f"{state.name} is already {format_room_feature_line(state).split(': ', 1)[1]}.")
        return

    await audit_event(
        bot,
        "room_feature_changed",
        actor=sender_jid,
        target=room_jid,
        details={"plugin": state.name, "enabled": state.enabled},
    )
    bot.reply_ok(msg, f"{state.name} is now {'enabled' if state.enabled else 'disabled'} for {room_jid}.")
