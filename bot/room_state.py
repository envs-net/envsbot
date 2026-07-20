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


__all__ = [
    "JOINED_ROOMS",
    "LEAVING_ROOMS",
    "RoomState",
    "WARNED_PLUGIN_DEFAULT_KEYS",
    "room_state",
]
