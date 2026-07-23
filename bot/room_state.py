"""Bot-owned runtime state for joined MUC rooms.

The state lives in the bot layer so command dispatch, permission checks,
shared XMPP helpers, and the rooms plugin all depend on the same neutral
runtime object.  The rooms plugin manages this state but does not own it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RoomState:
    """Mutable runtime state shared by the bot and room-aware plugins."""

    joined_rooms: dict[str, dict[str, Any]] = field(default_factory=dict)
    leaving_rooms: set[str] = field(default_factory=set)
    warned_plugin_default_keys: set[str] = field(default_factory=set)


room_state = RoomState()

# Transitional aliases keep existing room-aware plugins source-compatible
# while ownership remains in the bot layer.
JOINED_ROOMS = room_state.joined_rooms
LEAVING_ROOMS = room_state.leaving_rooms
WARNED_PLUGIN_DEFAULT_KEYS = room_state.warned_plugin_default_keys


def _bare_jid_key(value: Any) -> str:
    """Return a normalized bare-JID comparison key."""
    bare = getattr(value, "bare", value)
    return str(bare or "").split("/", 1)[0].strip().casefold()


def joined_room_jids(bot: Any = None, extra_rooms: Any = None) -> set[str]:
    """Return normalized JIDs for every room currently known as joined."""
    result: set[str] = set()

    for rooms in (
        extra_rooms,
        getattr(getattr(bot, "presence", None), "joined_rooms", None),
        JOINED_ROOMS,
    ):
        if not rooms:
            continue
        try:
            values = rooms.keys() if hasattr(rooms, "keys") else rooms
            for room in values:
                key = _bare_jid_key(room)
                if key:
                    result.add(key)
        except (AttributeError, TypeError):
            continue

    return result


def known_room_jids(
    bot: Any = None,
    extra_rooms: Any = None,
    stored_rooms: Any = None,
) -> set[str]:
    """Return normalized JIDs for joined and persistently stored MUC rooms.

    Database room rows are commonly represented as tuples, while tests and
    helper callers may provide mappings or plain JID values.  Keeping that
    normalization in the neutral bot layer prevents stored-but-temporarily-
    left MUCs from being mistaken for direct roster contacts or users.
    """
    result = joined_room_jids(bot, extra_rooms)

    if not stored_rooms:
        return result

    try:
        values = stored_rooms.keys() if hasattr(stored_rooms, "keys") else stored_rooms
        for room in values:
            if isinstance(room, dict):
                room = room.get("room_jid") or room.get("jid") or room.get("room")
            elif isinstance(room, (tuple, list)):
                room = room[0] if room else None
            key = _bare_jid_key(room)
            if key:
                result.add(key)
    except (AttributeError, TypeError):
        pass

    return result


__all__ = [
    "JOINED_ROOMS",
    "LEAVING_ROOMS",
    "RoomState",
    "WARNED_PLUGIN_DEFAULT_KEYS",
    "joined_room_jids",
    "known_room_jids",
    "room_state",
]
