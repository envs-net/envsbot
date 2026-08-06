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

    async def _safe_send_message(
        self,
        message: Any,
        *,
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
        try:
            result = message.send()
            if inspect.isawaitable(result):
                result = await result
            if result is not False:
                return True
            error: Exception = RuntimeError("Slixmpp did not accept the stanza")
        except Exception as exc:
            error = exc
            log.exception("[BOT] Failed to send message: %s", exc)

        if persist:
            outbox = getattr(self, "outbox", None)
            enqueue = getattr(outbox, "enqueue_message", None)
            if callable(enqueue):
                try:
                    queued_id = await enqueue(
                        message,
                        category=category,
                        dedupe_key=dedupe_key,
                        max_attempts=max_attempts,
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

    def _schedule_reply_send(
        self,
        message: Any,
        *,
        persist: bool = False,
        category: str = "reply",
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
    ) -> asyncio.Task[Any]:
        """Track one short-lived reply task until it finishes or shutdown drains it."""
        if not persist and dedupe_key is None and max_attempts is None:
            send_coro = self._reply_send_wrapper(message)
        else:
            send_coro = self._reply_send_wrapper(
                message,
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
        persist: bool = False,
        category: str = "reply",
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
    ) -> asyncio.Task[Any] | None:
        """Smart reply helper for plugins."""
        del rate_limit  # legacy parameter; command rate limiting happens in dispatch
        try:
            message, _body = self._build_reply_message(msg, text, mention, thread, ephemeral, no_store)
            task = self._schedule_reply_send(
                message,
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
        persist: bool = False,
        category: str = "reply",
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
    ) -> bool:
        """Wrapper to send messages asynchronously with error handling."""
        try:
            if not persist and dedupe_key is None and max_attempts is None:
                return await self._safe_send_message(message)
            return await self._safe_send_message(
                message,
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
