"""Message reply helpers for envsbot."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from envs_xmpp_core.xmpp.messaging import message_context_from_stanza
from envs_xmpp_core.xmpp.omemo import TaskLocalEncryptionMode
from envs_xmpp_core.xmpp.outbound import (
    can_persist_without_encryption_context,
    resolve_reply_encryption,
    transport_accepted,
)
from slixmpp.xmlstream import ET

from bot.connection import session_is_ready
from utils.outbox import ensure_message_origin_id

log = logging.getLogger(__name__)

_REPLY_ENCRYPTION = TaskLocalEncryptionMode("envsbot_reply_encrypted")


class MessageMixin:
    """Common reply and safe-send helpers for the bot."""

    make_message: Any

    def _set_reply_encryption_context(
        self,
        encrypted: bool | None,
    ):
        """Set the encryption mode inherited by replies in the current task."""
        return _REPLY_ENCRYPTION.set(encrypted)

    def _reset_reply_encryption_context(
        self,
        token,
    ) -> None:
        """Restore the previous task-local reply encryption mode."""
        _REPLY_ENCRYPTION.reset(token)

    def _get_reply_encryption_context(self) -> bool | None:
        """Return the current task's reply encryption mode, if any."""
        return _REPLY_ENCRYPTION.get()

    async def _safe_send_message(
        self,
        message: Any,
        *,
        encrypted: bool | None = None,
        persist: bool = False,
        category: str = "message",
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
    ) -> bool:
        """Safely send a message and optionally persist transport failures.

        A durable enqueue counts as accepted for callers such as RSS and
        reminders: their own cursor/state can advance because the central
        outbox owns the remaining delivery retries.
        """
        origin_id: str | None = None
        if persist:
            # Attach the durable identity before the *first* transport attempt.
            # If this send is accepted but the process dies before durable state
            # is cleared, outbox recovery will replay the same XEP-0359 ID.
            origin_id = ensure_message_origin_id(message)

        encrypted = resolve_reply_encryption(encrypted, self._get_reply_encryption_context())
        if getattr(self, "omemo_reset_pending_restart", False) and encrypted is not False:
            # Identity rotation disables OMEMO until restart; explicit reset
            # acknowledgements may use plaintext, but ordinary DM traffic must
            # not silently change its security mode in the interim.
            log.warning("[OMEMO] Deferring outbound delivery until identity reset restarts")
            return False
        if encrypted is None and bool(getattr(self, "omemo_enabled", False)):
            # Scheduled DM traffic has no inbound command/task encryption
            # context (RSS, daily health, upgrade/restart notes, outbox retry).
            # The default MUST be the encrypted transport for direct chats.
            # Preserve explicit False for intentionally plaintext replies and
            # never try OMEMO for an ordinary public groupchat message.
            try:
                message_type = str(message["type"] or "chat").lower()
            except Exception:
                # Unknown stanza shape with OMEMO active: fail closed rather
                # than risk sending a private notification in plaintext.
                log.warning("[OMEMO] Cannot classify outbound message type")
                return False
            if message_type in {"chat", "normal"}:
                encrypted = True
            elif message_type != "groupchat":
                log.warning("[OMEMO] Refusing unknown outbound message type: %s", message_type)
                return False

        if not session_is_ready(self):
            if encrypted is True:
                # A queued stanza would lose its task-local OMEMO recipient
                # context and could later be replayed as plaintext.
                log.warning("[OMEMO] Encrypted reply not queued while the XMPP session is unavailable")
                return False
            error: Exception = RuntimeError("XMPP session is not ready")
            log.debug("[BOT] Deferring send because the XMPP session is not ready")
        else:
            try:
                if encrypted is True:
                    send_omemo = getattr(self, "_send_omemo_message_object", None)
                    if not callable(send_omemo):
                        raise RuntimeError("OMEMO transport is unavailable")
                    result = await send_omemo(message)
                    if not transport_accepted(result):
                        raise RuntimeError("OMEMO transport rejected outbound stanza")
                    return True
                result = message.send()
                if inspect.isawaitable(result):
                    result = await result
                if transport_accepted(result):
                    return True
                error = RuntimeError("Slixmpp did not accept the stanza")
            except Exception as exc:
                error = exc
                if encrypted is True:
                    log.warning("[OMEMO] Encrypted send failed: %s", exc)
                    if not bool(getattr(self, "omemo_plaintext_fallback", False)):
                        # Never persist an encrypted reply as plaintext. The
                        # queue cannot currently retain OMEMO recipient/session
                        # context safely across restarts.
                        return False
                    log.warning("[OMEMO] Falling back to plaintext send")
                    try:
                        result = message.send()
                        if inspect.isawaitable(result):
                            result = await result
                        if transport_accepted(result):
                            return True
                        error = RuntimeError("Slixmpp did not accept the plaintext fallback stanza")
                    except Exception as fallback_exc:
                        error = fallback_exc
                        log.exception("[BOT] Plaintext fallback send failed: %s", fallback_exc)
                else:
                    log.exception("[BOT] Failed to send message: %s", exc)

        if persist and can_persist_without_encryption_context(encrypted):
            outbox = getattr(self, "outbox", None)
            enqueue = getattr(outbox, "enqueue_message", None)
            if callable(enqueue):
                try:
                    queued_id = await enqueue(
                        message,
                        category=category,
                        dedupe_key=dedupe_key,
                        max_attempts=max_attempts,
                        origin_id=origin_id,
                    )
                    if queued_id is not None:
                        log.warning(
                            "[OUTBOX] Queued failed message id=%s category=%s",
                            queued_id,
                            category,
                        )
                        return True
                except Exception:
                    log.exception("[OUTBOX] Failed to persist outbound message")
        log.debug("[BOT] Message delivery failed without durable ownership: %s", error)
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

        # The same route contract also covers MUC-PMs (full occupant JID).
        route = message_context_from_stanza(msg).reply_route
        message = self.make_message(mto=route.target, mbody=body, mtype=route.message_type)

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

    def _schedule_reply_send(
        self,
        message: Any,
        *,
        encrypted: bool | None = None,
        persist: bool = False,
        category: str = "reply",
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
    ) -> asyncio.Task[Any]:
        """Track one short-lived reply task until it finishes or shutdown drains it."""
        if not persist and dedupe_key is None and max_attempts is None and encrypted is not True:
            send_coro = self._reply_send_wrapper(message)
        else:
            send_coro = self._reply_send_wrapper(
                message,
                encrypted=encrypted,
                persist=persist,
                category=category,
                dedupe_key=dedupe_key,
                max_attempts=max_attempts,
            )
        task = asyncio.create_task(send_coro)
        tasks = getattr(self, "_reply_tasks", None)
        if tasks is None:
            tasks = set()
            self._reply_tasks = tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    async def _drain_reply_tasks(self, *, timeout: float = 3.0) -> tuple[int, int]:
        """Let pending replies finish, then cancel anything left after *timeout*."""
        tasks = getattr(self, "_reply_tasks", None)
        if not tasks:
            return 0, 0

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, float(timeout))
        completed = 0
        cancelled = 0

        # Existing command handlers may schedule their final reply immediately
        # after shutdown stops accepting new commands. Re-check the tracked set
        # until it stays empty or the shared deadline is reached.
        while True:
            active = {task for task in tuple(tasks) if not task.done()}
            if not active:
                await asyncio.sleep(0)
                active = {task for task in tuple(tasks) if not task.done()}
                if not active:
                    tasks.clear()
                    break

            remaining = max(0.0, deadline - loop.time())
            done, pending = await asyncio.wait(active, timeout=remaining)
            completed += len(done)
            tasks.difference_update(done)

            if pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                cancelled += len(pending)
                tasks.difference_update(pending)

            if loop.time() >= deadline:
                late = {task for task in tuple(tasks) if not task.done()}
                for task in late:
                    task.cancel()
                if late:
                    await asyncio.gather(*late, return_exceptions=True)
                    cancelled += len(late)
                    tasks.difference_update(late)
                break

        return completed, cancelled

    def reply(
        self,
        msg: Any,
        text: str | list[str],
        mention: bool = True,
        thread: bool = True,
        rate_limit: bool = True,
        ephemeral: bool = False,
        no_store: bool | None = None,
        *,
        encrypted: bool | None = None,
        persist: bool = False,
        category: str = "reply",
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
    ) -> asyncio.Task[Any] | None:
        """Smart reply helper for plugins."""
        del rate_limit  # legacy parameter; command rate limiting happens in dispatch
        try:
            message, _body = self._build_reply_message(msg, text, mention, thread, ephemeral, no_store)
            if encrypted is None:
                encrypted = self._get_reply_encryption_context()
            task = self._schedule_reply_send(
                message,
                encrypted=encrypted,
                persist=persist,
                category=category,
                dedupe_key=dedupe_key,
                max_attempts=max_attempts,
            )
            self._record_test_reply(msg, text if not isinstance(text, list) else "\n".join(text))
            return task
        except Exception as exc:
            msg_type = msg.get("type", "chat")
            if msg_type == "groupchat":
                import envsbot as app
                app.log.exception("[BOT] Error creating groupchat reply: %s", exc)
            else:
                import envsbot as app
                app.log.exception("[BOT] Error creating private reply: %s", exc)
            return None

    async def _reply_send_wrapper(
        self,
        message: Any,
        *,
        encrypted: bool | None = None,
        persist: bool = False,
        category: str = "reply",
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
    ) -> bool:
        """Wrapper to send messages asynchronously with error handling."""
        try:
            if not persist and dedupe_key is None and max_attempts is None and encrypted is not True:
                return await self._safe_send_message(message)
            return await self._safe_send_message(
                message,
                encrypted=encrypted,
                persist=persist,
                category=category,
                dedupe_key=dedupe_key,
                max_attempts=max_attempts,
            )
        except TypeError as exc:
            # Keep compatibility with reduced test doubles and older embedders.
            text = str(exc)
            if "unexpected keyword" not in text and "keyword argument" not in text:
                raise
            return await self._safe_send_message(message)
        except Exception as exc:
            log.exception("[BOT] Error in reply send wrapper: %s", exc)
            return False
