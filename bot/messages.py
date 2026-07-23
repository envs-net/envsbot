"""Message reply helpers for envsbot."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from slixmpp.xmlstream import ET

log = logging.getLogger(__name__)


class MessageMixin:
    """Common reply and safe-send helpers for the bot."""

    async def _safe_send_message(self, message: Any) -> bool:
        """Safely send a message with sync/async send() support.

        Return ``True`` once the stanza was handed to Slixmpp and ``False``
        when creating or sending it raised an exception.  Callers that need
        reliable delivery bookkeeping (for example direct RSS subscriptions)
        can therefore avoid marking an item as delivered after a failed send.
        """
        try:
            result = message.send()
            if inspect.isawaitable(result):
                result = await result
            return result is not False
        except Exception as exc:
            log.exception("[BOT] Failed to send message: %s", exc)
            return False

    def _format_reply_body(self, msg: Any, text: str, mention: bool) -> str:
        """Build the outbound reply body without changing reply semantics."""
        if msg.get("type", "chat") == "groupchat" and mention:
            nick = msg.get("mucnick") or msg["from"].resource
            return f"{nick}: {text}"
        return text

    def _build_reply_message(
        self,
        msg: Any,
        text: str | list[str],
        mention: bool,
        thread: bool,
        ephemeral: bool,
        no_store: bool | None = None,
    ) -> tuple[Any, str]:
        """Create the outbound message object for reply()."""
        msg_type = msg.get("type", "chat")
        body = "\n".join(text) if isinstance(text, list) else text
        body = self._format_reply_body(msg, body, mention)

        if msg_type == "groupchat":
            message = self.make_message(mto=msg["from"].bare, mbody=body, mtype="groupchat")
        else:
            message = self.make_message(mto=msg["from"], mbody=body, mtype="chat")

        if thread:
            thread_id = msg.get("thread") or msg.get("id")
            if thread_id:
                try:
                    message["thread"] = thread_id
                except Exception:
                    if msg_type == "groupchat":
                        log.debug("[BOT] Setting thread failed!")

        if no_store is None:
            no_store = ephemeral
        if no_store:
            message.append(ET.Element("{urn:xmpp:hints}no-store"))

        return message, body

    def _record_test_reply(self, msg: Any, text: str) -> None:
        """Preserve test-side reply capture behavior."""
        if hasattr(msg, "replies"):
            msg.replies.append(text)

    def reply_ok(self, msg: Any, text: str, **kwargs: Any) -> None:
        """Send a success reply with a consistent prefix."""
        self.reply(msg, f"✅ {text}", **kwargs)

    def reply_info(self, msg: Any, text: str, **kwargs: Any) -> None:
        """Send an informational reply with a consistent prefix."""
        self.reply(msg, f"ℹ️ {text}", **kwargs)

    def reply_warn(self, msg: Any, text: str, **kwargs: Any) -> None:
        """Send a warning reply with a consistent prefix."""
        self.reply(msg, f"🟡️ {text}", **kwargs)

    def reply_error(self, msg: Any, text: str, **kwargs: Any) -> None:
        """Send an error reply with a consistent prefix."""
        self.reply(msg, f"🔴 {text}", **kwargs)

    def reply_usage(self, msg: Any, usage: str, **kwargs: Any) -> None:
        """Send a command usage reply."""
        self.reply_warn(msg, f"Usage: {usage}", **kwargs)

    def reply(
        self,
        msg: Any,
        text: str | list[str],
        mention: bool = True,
        thread: bool = True,
        rate_limit: bool = True,
        ephemeral: bool = False,
        no_store: bool | None = None,
    ) -> None:
        """Smart reply helper for plugins."""
        del rate_limit  # legacy parameter; command rate limiting happens in dispatch
        try:
            message, _body = self._build_reply_message(msg, text, mention, thread, ephemeral, no_store)
            asyncio.create_task(self._reply_send_wrapper(message))
            self._record_test_reply(msg, text if not isinstance(text, list) else "\n".join(text))
        except Exception as exc:
            msg_type = msg.get("type", "chat")
            if msg_type == "groupchat":
                import envsbot as app
                app.log.exception("[BOT] Error creating groupchat reply: %s", exc)
            else:
                import envsbot as app
                app.log.exception("[BOT] Error creating private reply: %s", exc)

    async def _reply_send_wrapper(self, message: Any) -> None:
        """Wrapper to send messages asynchronously with error handling."""
        try:
            await self._safe_send_message(message)
        except Exception as exc:
            log.exception("[BOT] Error in reply send wrapper: %s", exc)
