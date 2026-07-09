"""Diagnostic hook helpers for plugin manager integrations."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)


async def call_runtime_state_hook(bot, name: str, hook, *, room_jid: str | None = None) -> dict[str, Any]:
    """Call a plugin ``get_runtime_state`` hook and normalize the result."""
    if hook is None:
        return {"loaded": True}
    if not callable(hook):
        return {"loaded": True, "error": "get_runtime_state is not callable"}
    try:
        result = hook(bot, room_jid=room_jid)
        if inspect.isawaitable(result):
            result = await result
        if result is None:
            result = {}
        if not isinstance(result, dict):
            result = {"result": result}
        return {"loaded": True, **result}
    except Exception as exc:
        log.exception("[PLUGIN] get_runtime_state failed for %s", name)
        return {"loaded": True, "error": str(exc)}


def _state_line(name: str, state: dict[str, Any]) -> str:
    if not state:
        return f"ℹ️ {name}: no diagnostic hook"
    return f"ℹ️ {name}: " + ", ".join(f"{key}={value}" for key, value in sorted(state.items()))


async def call_doctor_hook(
    bot,
    name: str,
    hook,
    *,
    room_jid: str | None = None,
    state_getter: Callable[[str, str | None], Awaitable[dict[str, Any]]],
) -> list[str]:
    """Call a plugin ``doctor`` hook or fall back to runtime state."""
    if hook is None:
        return [_state_line(name, await state_getter(name, room_jid))]
    if not callable(hook):
        return [f"🔴 {name}: doctor hook is not callable"]
    try:
        result = hook(bot, room_jid=room_jid)
        if inspect.isawaitable(result):
            result = await result
        if result is None:
            return [f"✅ {name}: ok"]
        if isinstance(result, str):
            return [result]
        return [str(line) for line in result]
    except Exception as exc:
        log.exception("[PLUGIN] doctor hook failed for %s", name)
        return [f"🔴 {name}: doctor failed: {exc}"]
