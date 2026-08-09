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
from utils.logging_helpers import kv
from utils.performance import observe_group
from utils.redaction import redact_text, redact_value

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
    return redact_text(value, max_length=160)


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
                details=redact_value(details),
            )
        except Exception:
            log.debug("[COMMAND] Failed to write command audit event", exc_info=True)

    async def _record_usage(
        self,
        context: CommandExecutionContext,
        *,
        success: bool,
        duration_ms: int,
    ) -> None:
        """Persist aggregate usage without retaining actor or message content."""
        db = getattr(self.bot, "db", None)
        store = getattr(db, "command_usage", None)
        record = getattr(store, "record", None)
        if not callable(record):
            return
        if context.is_room:
            command_context = "room"
        elif context.room:
            command_context = "muc-pm"
        else:
            command_context = "direct"
        try:
            await record(
                context.command_name,
                context=command_context,
                success=success,
                duration_ms=duration_ms,
            )
        except Exception:
            log.debug("[COMMAND] Failed to record usage statistics", exc_info=True)

    async def execute(self, cmd_obj: Any, context: CommandExecutionContext, msg: Any) -> None:
        """Run one command handler and handle all cross-cutting concerns."""
        handler = getattr(cmd_obj, "handler", None)
        if not handler:
            log.error("[BOT]🔴 Command '%s' has no handler", context.command_name)
            return

        timeout_override = getattr(cmd_obj, "timeout_seconds", None)
        timeout = (
            self.timeout_seconds()
            if timeout_override is None
            else max(0.0, float(timeout_override))
        )
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
        except TimeoutError:
            status = "timeout"
            error_text = f"timeout after {timeout:g}s"
            log.warning(
                "[COMMAND] event=timeout %s",
                kv(command=context.command_name, actor=context.sender_jid, room=context.room, timeout=f"{timeout:g}s"),
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
            observe_group("commands", context.command_name, duration_ms / 1000.0)
            slow_threshold = self.slow_log_seconds()
            if slow_threshold > 0 and duration_ms >= int(slow_threshold * 1000):
                log.info(
                    "[COMMAND] event=slow %s",
                    kv(command=context.command_name, actor=context.sender_jid, room=context.room, duration_ms=duration_ms, status=status),
                )
            await self._audit(
                context,
                status=status,
                duration_ms=duration_ms,
                error=error_text,
            )
            await self._record_usage(
                context,
                success=status == "ok",
                duration_ms=duration_ms,
            )
