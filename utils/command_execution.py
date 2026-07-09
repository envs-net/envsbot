"""Central command execution wrapper for EnvsBot."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from typing import Any

from utils.command import Role
from utils.config import config

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandExecutionContext:
    """Small immutable command execution context used for diagnostics."""

    command_name: str
    sender_jid: str
    nick: str | None
    room: str | None
    is_room: bool
    role: Role
    args: tuple[str, ...]


def _float_config(key: str, default: float) -> float:
    try:
        return float(config.get(key, default) or default)
    except Exception:
        return default


def _should_audit_command(role: Role) -> bool:
    """Return whether command executions by this role should be audited."""
    return role <= Role.MODERATOR


def _safe_detail(value: Any) -> str:
    """Return a compact value for audit details without leaking huge messages."""
    text = str(value)
    if len(text) > 160:
        return text[:157] + "..."
    return text


class CommandExecutor:
    """Execute command handlers with consistent timeout/audit/error behavior."""

    def __init__(self, bot: Any):
        self.bot = bot

    def timeout_seconds(self) -> float:
        """Return configured command execution timeout in seconds."""
        return max(0.0, _float_config("command_timeout_seconds", 30.0))

    def slow_log_seconds(self) -> float:
        """Return threshold for slow command logging in seconds."""
        return max(0.0, _float_config("command_slow_log_seconds", 2.0))

    async def _audit(
        self,
        context: CommandExecutionContext,
        *,
        status: str,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        """Write best-effort audit information for privileged commands."""
        if not _should_audit_command(context.role):
            return
        audit = getattr(self.bot, "audit", None)
        if not callable(audit):
            return
        details: dict[str, Any] = {
            "command": context.command_name,
            "role": str(context.role),
            "room": context.room,
            "is_room": context.is_room,
            "args_count": len(context.args),
            "status": status,
            "duration_ms": duration_ms,
        }
        if error:
            details["error"] = _safe_detail(error)
        try:
            await audit(
                "command_executed",
                actor=context.sender_jid,
                target=context.command_name,
                details=details,
            )
        except Exception:
            log.debug("[COMMAND] Failed to write command audit event", exc_info=True)

    async def execute(self, cmd_obj: Any, context: CommandExecutionContext, msg: Any) -> None:
        """Run one command handler and handle all cross-cutting concerns."""
        handler = getattr(cmd_obj, "handler", None)
        if not handler:
            log.error("[BOT]🔴 Command '%s' has no handler", context.command_name)
            return

        timeout = self.timeout_seconds()
        started = time.monotonic()
        status = "ok"
        error_text: str | None = None
        try:
            result = handler(
                self.bot,
                context.sender_jid,
                context.nick,
                list(context.args),
                msg,
                context.is_room,
            )
            if inspect.isawaitable(result):
                if timeout > 0:
                    await asyncio.wait_for(result, timeout=timeout)
                else:
                    await result
        except asyncio.TimeoutError:
            status = "timeout"
            error_text = f"timeout after {timeout:g}s"
            log.warning(
                "[COMMAND] Command timed out: %s actor=%s room=%s timeout=%ss",
                context.command_name,
                context.sender_jid,
                context.room,
                timeout,
            )
            self.bot.reply_error(
                msg,
                f"Command '{context.command_name}' timed out after {timeout:g}s.",
            )
        except Exception as exc:
            status = "error"
            error_text = f"{type(exc).__name__}: {exc}"
            log.exception(
                "[BOT]🔴  Error while executing command '%s'",
                context.command_name,
            )
            self.bot.reply(
                msg,
                self.bot._command_error_message(
                    context.role,
                    context.command_name,
                    exc,
                ),
            )
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            slow_threshold = self.slow_log_seconds()
            if slow_threshold > 0 and duration_ms >= int(slow_threshold * 1000):
                log.info(
                    "[COMMAND] Slow command: %s actor=%s room=%s duration=%dms status=%s",
                    context.command_name,
                    context.sender_jid,
                    context.room,
                    duration_ms,
                    status,
                )
            await self._audit(
                context,
                status=status,
                duration_ms=duration_ms,
                error=error_text,
            )
