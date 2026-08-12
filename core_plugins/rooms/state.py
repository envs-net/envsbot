"""Split module for core_plugins/rooms.py: state."""

import inspect
import logging

from slixmpp import JID

from bot.room_state import (
    JOINED_ROOMS,
)
from bot.room_state import (
    LEAVING_ROOMS as _LEAVING_ROOMS,
)
from bot.room_state import (
    WARNED_PLUGIN_DEFAULT_KEYS as _WARNED_ROOM_PLUGIN_DEFAULT_KEYS,
)
from utils.room_features import list_room_features

log = logging.getLogger(__name__)


_DIRECT_INVITE_NS = "jabber:x:conference"


_MUC_USER_NS = "http://jabber.org/protocol/muc#user"


def _jid_bare(value) -> str:
    """Return a best-effort lower-case bare JID string."""
    if value is None:
        return ""
    bare = getattr(value, "bare", None)
    if bare:
        return str(bare).lower()
    try:
        return str(JID(str(value)).bare).lower()
    except Exception:
        return str(value).split("/", 1)[0].lower()


def _safe_get_plugin(stanza, plugin_name: str):
    """Return a stanza plugin without noisy unknown-interface warnings."""
    get_plugin = getattr(stanza, "get_plugin", None)
    if not callable(get_plugin):
        return None
    try:
        return get_plugin(plugin_name, check=True)
    except TypeError:
        try:
            return get_plugin(plugin_name)
        except Exception:
            return None
    except Exception:
        return None


def _safe_plugin_value(plugin, key: str) -> str:
    """Return a string value from a stanza plugin."""
    if plugin is None:
        return ""
    try:
        value = plugin.get(key)
    except Exception:
        try:
            value = plugin[key]
        except Exception:
            return ""
    return "" if value is None else str(value).strip()


async def _maybe_await_result(result):
    """Await result when a slixmpp helper returns an awaitable."""
    if inspect.isawaitable(result):
        return await result
    return result


def _get_plugin_store(bot, plugin_name: str):
    """Return a plugin runtime store, or None when unavailable."""
    users = getattr(getattr(bot, "db", None), "users", None)
    plugin_getter = getattr(users, "plugin", None)
    if not callable(plugin_getter):
        return None
    try:
        return plugin_getter(plugin_name)
    except Exception:
        log.debug(
            "[ROOMS] Could not open plugin store %s",
            plugin_name,
            exc_info=True,
        )
        return None


async def _store_get_global(store, key: str, default=None):
    """Read a plugin-global key from a runtime store."""
    getter = getattr(store, "get_global", None)
    if not callable(getter):
        return default
    result = getter(key, default=default)
    result = await _maybe_await_result(result)
    return default if result is None else result


async def _store_set_global(store, key: str, value) -> None:
    """Write a plugin-global key to a runtime store."""
    setter = getattr(store, "set_global", None)
    if not callable(setter):
        return
    await _maybe_await_result(setter(key, value))


def _room_matches(left: object, right: str) -> bool:
    """Return True when two room JID values refer to the same bare room."""
    return _jid_bare(left) == right


def _plugin_cleanup_changed(summary: dict) -> bool:
    """Return True when a plugin cleanup summary removed anything."""
    for key, value in summary.items():
        if key == "plugin_hooks":
            continue
        try:
            if int(value or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return _plugin_hook_cleanup_changed(summary.get("plugin_hooks"))


def _plugin_hook_cleanup_changed(plugin_hooks) -> bool:
    """Return True if any plugin hook summary contains a positive counter."""
    if not isinstance(plugin_hooks, dict):
        return False
    for values in plugin_hooks.values():
        if not isinstance(values, dict):
            continue
        for value in values.values():
            try:
                if int(value or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _room_in_runtime_state(bot, room_jid: str) -> bool:
    """Return True if the room is currently tracked as joined at runtime."""
    presence_rooms = getattr(getattr(bot, "presence", None), "joined_rooms", {})
    return room_jid in JOINED_ROOMS or room_jid in presence_rooms


async def _leave_runtime_room(bot, room_jid: str) -> bool:
    """Leave a room and remove all runtime state for it.

    The room may exist in JOINED_ROOMS, in the presence helper, or both.
    Mark it as intentionally leaving so delayed MUC presence cannot recreate
    stale JOINED_ROOMS entries after delete/leave/sync.
    """
    room_data = JOINED_ROOMS.get(room_jid) or {}
    presence_rooms = getattr(getattr(bot, "presence", None), "joined_rooms", {})
    joined = room_jid in JOINED_ROOMS or room_jid in presence_rooms
    nick_to_leave = room_data.get("nick") or presence_rooms.get(room_jid)

    if joined or nick_to_leave:
        _LEAVING_ROOMS.add(room_jid)

    if nick_to_leave:
        try:
            muc = bot.plugin["xep_0045"]
            await _maybe_await_result(muc.leave_muc(room_jid, nick_to_leave))
        except Exception:
            log.warning("[ROOMS] Error leaving room %s", room_jid, exc_info=True)

    JOINED_ROOMS.pop(room_jid, None)
    presence_rooms.pop(room_jid, None)

    if joined:
        broadcast = getattr(getattr(bot, "presence", None), "broadcast", None)
        if callable(broadcast):
            broadcast()

    return joined


async def room_status_get(bot, room_jid, path=None):
    return await bot.db.rooms.status_get(room_jid, path)


async def room_status_set(bot, room_jid, path, value):
    await bot.db.rooms.status_set(room_jid, path, value)


async def room_status_delete(bot, room_jid, path):
    await bot.db.rooms.status_delete(room_jid, path)


def _yes_no(value: object) -> str:
    return "yes" if bool(value) else "no"


async def _room_diagnose_lines(bot, room_jid: str) -> list[str]:
    """Return operational diagnostics for one room."""
    db_room = await bot.db.rooms.get(room_jid)
    joined_info = JOINED_ROOMS.get(room_jid) or {}
    presence_joined = room_jid in getattr(getattr(bot, "presence", None), "joined_rooms", {})
    nicks = joined_info.get("nicks", {}) or {}
    pending_invites = getattr(bot, "pending_room_invites", {}) or {}
    invite_count = sum(
        1 for invite in pending_invites.values()
        if str(invite.get("room_jid", "")).lower() == room_jid.lower()
    )
    features = await list_room_features(bot, room_jid)
    enabled = sorted(feature.name for feature in features if feature.enabled)
    disabled = sorted(feature.name for feature in features if not feature.enabled)

    core_joined = bool(joined_info)
    lines = [
        f"🔎 Room diagnostics: {room_jid}",
        f"Known in DB: {_yes_no(db_room)}",
        f"Currently joined: {_yes_no(core_joined or presence_joined)}",
        f"Tracked occupants: {len(nicks)}",
        f"Pending invites: {invite_count}",
    ]
    if core_joined and not presence_joined:
        lines.append(
            "⚠️ Presence routing state is missing for this joined room."
        )
    elif presence_joined and not core_joined:
        lines.append(
            "⚠️ Core room state is missing for this presence-tracked room."
        )
    elif core_joined and presence_joined:
        runtime_nick = str(joined_info.get("nick") or "")
        presence_nick = str(
            getattr(bot.presence, "joined_rooms", {}).get(room_jid) or ""
        )
        if runtime_nick and presence_nick and runtime_nick != presence_nick:
            lines.append(
                "⚠️ Presence routing nick differs from the core runtime nick: "
                f"{presence_nick} != {runtime_nick}"
            )
    if db_room:
        try:
            lines.extend([
                f"Configured nick: {db_room[1]}",
                f"Autojoin: {_yes_no(db_room[2])}",
                f"Status: {db_room[3] if len(db_room) > 3 else 'unknown'}",
            ])
        except Exception:
            log.debug("[ROOMS] Could not format DB room row", exc_info=True)
    if joined_info:
        lines.extend([
            f"Runtime nick: {joined_info.get('nick', 'unknown')}",
            f"Runtime affiliation: {joined_info.get('affiliation', 'unknown')}",
            f"Runtime role: {joined_info.get('role', 'unknown')}",
        ])

    lines.extend([
        f"Enabled room plugins ({len(enabled)}): {', '.join(enabled) if enabled else 'none'}",
        f"Disabled room plugins ({len(disabled)}): {', '.join(disabled) if disabled else 'none'}",
    ])

    manager = getattr(bot, "bot_plugins", None)
    state_getter = getattr(manager, "plugin_state", None)
    if callable(state_getter):
        plugin_lines: list[str] = []
        for plugin in getattr(manager, "plugins", {}):
            state = await state_getter(plugin, room_jid=room_jid)
            details = {
                key: value
                for key, value in state.items()
                if key != "loaded"
            }
            if not details:
                continue
            summary = ", ".join(
                f"{key}={value}"
                for key, value in sorted(details.items())
            )
            plugin_lines.append(f"• {plugin}: {summary}")
        if plugin_lines:
            lines.append("Plugin room state:")
            lines.extend(plugin_lines)
    return lines

__all__ = [
    'log',
    'JOINED_ROOMS',
    '_LEAVING_ROOMS',
    '_DIRECT_INVITE_NS',
    '_MUC_USER_NS',
    '_WARNED_ROOM_PLUGIN_DEFAULT_KEYS',
    '_safe_get_plugin',
    '_safe_plugin_value',
    '_maybe_await_result',
    '_get_plugin_store',
    '_store_get_global',
    '_store_set_global',
    '_room_matches',
    '_plugin_cleanup_changed',
    '_plugin_hook_cleanup_changed',
    '_room_in_runtime_state',
    '_leave_runtime_room',
    'room_status_get',
    'room_status_set',
    'room_status_delete',
    '_yes_no',
    '_room_diagnose_lines',
]
