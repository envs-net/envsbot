"""Audit helper safe for runtime and unit-test bot doubles."""

from __future__ import annotations

import inspect
import logging

log = logging.getLogger(__name__)


async def audit_event(bot, event: str, *, actor=None, target=None, details=None) -> None:
    """Write an audit event if the bot exposes an async or sync audit hook."""
    hook = getattr(bot, "audit", None)
    if hook is None or not callable(hook):
        return
    try:
        result = hook(event, actor=actor, target=target, details=details or {})
        if inspect.isawaitable(result):
            await result
    except Exception:
        log.debug("[AUDIT] Failed to write audit event", exc_info=True)
