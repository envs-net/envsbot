from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import utils.command_execution as ce
from utils.command import Role


def _context(role=Role.ADMIN):
    return ce.CommandExecutionContext(
        command_name="config set",
        sender_jid="admin@example.org",
        nick="admin",
        room="room@conf",
        is_room=False,
        role=role,
        args=("KEY", "value"),
    )


@pytest.mark.asyncio
async def test_command_executor_audits_admin_command(monkeypatch):
    monkeypatch.setitem(ce.config, "command_timeout_seconds", 5)
    bot = SimpleNamespace(audit=AsyncMock(), reply=MagicMock(), reply_error=MagicMock())
    bot._command_error_message = MagicMock(return_value="friendly error")
    executor = ce.CommandExecutor(bot)
    handler = AsyncMock()
    cmd = SimpleNamespace(handler=handler)
    msg = MagicMock()

    await executor.execute(cmd, _context(), msg)

    handler.assert_awaited_once()
    bot.audit.assert_awaited_once()
    assert bot.audit.await_args.args[0] == "command_executed"
    assert bot.audit.await_args.kwargs["target"] == "config set"
    assert bot.audit.await_args.kwargs["details"]["status"] == "ok"


@pytest.mark.asyncio
async def test_command_executor_reports_timeout(monkeypatch):
    monkeypatch.setitem(ce.config, "command_timeout_seconds", 0.01)
    bot = SimpleNamespace(audit=AsyncMock(), reply=MagicMock(), reply_error=MagicMock())
    bot._command_error_message = MagicMock(return_value="friendly error")
    executor = ce.CommandExecutor(bot)

    async def slow(*_args):
        await asyncio.sleep(1)

    msg = MagicMock()
    await executor.execute(SimpleNamespace(handler=slow), _context(), msg)

    bot.reply_error.assert_called_once()
    assert "timed out" in bot.reply_error.call_args.args[1]
    assert bot.audit.await_args.kwargs["details"]["status"] == "timeout"


@pytest.mark.asyncio
async def test_command_executor_does_not_audit_regular_user(monkeypatch):
    monkeypatch.setitem(ce.config, "command_timeout_seconds", 5)
    bot = SimpleNamespace(audit=AsyncMock(), reply=MagicMock(), reply_error=MagicMock())
    bot._command_error_message = MagicMock(return_value="friendly error")
    handler = AsyncMock()

    await ce.CommandExecutor(bot).execute(
        SimpleNamespace(handler=handler),
        _context(role=Role.USER),
        MagicMock(),
    )

    handler.assert_awaited_once()
    bot.audit.assert_not_awaited()
