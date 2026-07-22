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


__all__ = [
    "JOINED_ROOMS",
    "LEAVING_ROOMS",
    "RoomState",
    "WARNED_PLUGIN_DEFAULT_KEYS",
    "joined_room_jids",
    "room_state",
]
