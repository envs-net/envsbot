"""Incoming XMPP message routing helpers."""

from __future__ import annotations

import inspect
import logging
from typing import Any

log = logging.getLogger(__name__)


class MessageRoutingMixin:
    """Route MUC and private messages into command dispatch."""

    async def _cache_incoming_message(self, msg: Any, *, is_room: bool) -> None:
        """Cache an incoming message without breaking normal routing."""
        try:
            await self.message_cache.add_message(
                msg,
                is_room=is_room,
                joined_rooms=self.presence.joined_rooms,
            )
        except Exception:
            log.exception(
                "[MESSAGE_CACHE] event=add status=failed is_room=%s",
                is_room,
            )

    async def on_muc_message(self, msg: Any) -> None:
        """Handle public groupchat messages only while the runtime is ready."""
        if not getattr(self, "accepting_commands", False):
            return
        try:
            room = msg["from"].bare
            nick = msg.get("mucnick")
            bot_nick = self.presence.joined_rooms.get(room)
            if bot_nick == nick:
                return
            if msg["type"] == "groupchat":
                await self._cache_incoming_message(msg, is_room=True)
                plugin_manager = getattr(self, "bot_plugins", None)
                dispatch_runtime_event = getattr(plugin_manager, "dispatch_runtime_event", None)
                if callable(dispatch_runtime_event):
                    result = dispatch_runtime_event("public_groupchat_message", msg)
                    if inspect.isawaitable(result):
                        await result
                await self.handle_command(msg["body"], msg["from"], nick, msg, True)
        except Exception as exc:
            log.exception("[BOT] Error in on_muc_message: %s", exc)

    async def on_private_message(self, msg: Any) -> None:
        """Handle direct messages and MUC private messages only when ready."""
        if not getattr(self, "accepting_commands", False):
            return
        try:
            if msg["type"] in ("chat", "normal"):
                await self._cache_incoming_message(msg, is_room=False)
                plugin_manager = getattr(self, "bot_plugins", None)
                dispatch_runtime_event = getattr(
                    plugin_manager,
                    "dispatch_runtime_event",
                    None,
                )
                if callable(dispatch_runtime_event):
                    result = dispatch_runtime_event("private_message_received", msg)
                    if inspect.isawaitable(result):
                        await result
                await self.handle_command(msg["body"], msg["from"], None, msg, False)
        except Exception as exc:
            log.exception("[BOT] Error in on_private_message: %s", exc)
