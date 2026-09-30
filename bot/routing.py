"""Incoming XMPP message routing helpers."""

from __future__ import annotations

import inspect
import logging
from typing import Any

from envs_xmpp_core.xmpp.messaging import message_context_from_stanza

from utils.message_cache import is_delayed_message

log = logging.getLogger(__name__)


class MessageRoutingMixin:
    """Route MUC and private messages into command dispatch."""

    message_cache: Any
    presence: Any
    handle_command: Any

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

    async def _prepare_incoming_message(self, msg: Any) -> tuple[Any | None, bool]:
        """Decrypt OMEMO when available and report the incoming transport mode."""
        decrypt = getattr(self, "_decrypt_incoming_omemo_message", None)
        if not callable(decrypt):
            return msg, False
        result = decrypt(msg)
        if inspect.isawaitable(result):
            return await result
        return result

    def _set_incoming_encryption_context(self, encrypted: bool):
        setter = getattr(self, "_set_reply_encryption_context", None)
        return setter(encrypted) if callable(setter) else None

    def _reset_incoming_encryption_context(self, token: Any) -> None:
        if token is None:
            return
        resetter = getattr(self, "_reset_reply_encryption_context", None)
        if callable(resetter):
            resetter(token)

    async def on_muc_message(self, msg: Any) -> None:
        """Handle public groupchat messages only while the runtime is ready."""
        if not getattr(self, "accepting_commands", False):
            return
        if is_delayed_message(msg):
            log.debug("[BOT] Ignoring delayed MUC history message")
            return
        try:
            incoming = message_context_from_stanza(msg)
            room = incoming.sender_bare
            nick = msg.get("mucnick")
            bot_nick = self.presence.joined_rooms.get(room)
            if bot_nick == nick:
                return
            if incoming.is_room:
                msg, encrypted = await self._prepare_incoming_message(msg)
                if msg is None:
                    return
                context = message_context_from_stanza(msg, encrypted=encrypted)
                token = self._set_incoming_encryption_context(context.encrypted)
                try:
                    # Never persist decrypted OMEMO plaintext in the ordinary
                    # message cache. Plain messages keep their existing cache
                    # behavior unchanged.
                    if not encrypted:
                        await self._cache_incoming_message(msg, is_room=True)
                    plugin_manager = getattr(self, "bot_plugins", None)
                    dispatch_runtime_event = getattr(plugin_manager, "dispatch_runtime_event", None)
                    if callable(dispatch_runtime_event):
                        result = dispatch_runtime_event("public_groupchat_message", msg)
                        if inspect.isawaitable(result):
                            await result
                    await self.handle_command(context.body, msg["from"], nick, msg, True)
                finally:
                    self._reset_incoming_encryption_context(token)
        except Exception as exc:
            log.exception("[BOT] Error in on_muc_message: %s", exc)

    async def on_private_message(self, msg: Any) -> None:
        """Handle direct messages and MUC private messages only when ready."""
        if not getattr(self, "accepting_commands", False):
            return
        try:
            if message_context_from_stanza(msg).message_type in ("chat", "normal"):
                msg, encrypted = await self._prepare_incoming_message(msg)
                if msg is None:
                    return
                context = message_context_from_stanza(
                    msg, encrypted=encrypted, joined_rooms=self.presence.joined_rooms
                )
                token = self._set_incoming_encryption_context(context.encrypted)
                try:
                    if not encrypted:
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
                    await self.handle_command(context.body, msg["from"], None, msg, False)
                finally:
                    self._reset_incoming_encryption_context(token)
        except Exception as exc:
            log.exception("[BOT] Error in on_private_message: %s", exc)
