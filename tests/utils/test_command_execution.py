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
async def test_command_executor_allows_command_specific_timeout_override(monkeypatch):
    monkeypatch.setitem(ce.config, "command_timeout_seconds", 0.001)
    bot = SimpleNamespace(audit=AsyncMock(), reply=MagicMock(), reply_error=MagicMock())
    bot._command_error_message = MagicMock(return_value="friendly error")
    completed = False

    async def guarded(*_args):
        nonlocal completed
        await asyncio.sleep(0.01)
        completed = True

    await ce.CommandExecutor(bot).execute(
        SimpleNamespace(handler=guarded, timeout_seconds=0),
        _context(),
        MagicMock(),
    )

    assert completed is True
    bot.reply_error.assert_not_called()
    assert bot.audit.await_args.kwargs["details"]["status"] == "ok"


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


@pytest.mark.asyncio
async def test_command_executor_preserves_reply_encryption_inside_timeout_task(monkeypatch):
    monkeypatch.setitem(ce.config, "command_timeout_seconds", 5)
    current_owner = None
    current_value = True
    seen = []

    def get_context():
        if current_owner is asyncio.current_task():
            return current_value
        # The outer routing task owns the incoming OMEMO context.
        if current_owner is None:
            return True
        return None

    def set_context(value):
        nonlocal current_owner, current_value
        previous = (current_owner, current_value)
        current_owner = asyncio.current_task()
        current_value = value
        return previous

    def reset_context(token):
        nonlocal current_owner, current_value
        current_owner, current_value = token

    bot = SimpleNamespace(
        audit=AsyncMock(),
        reply=MagicMock(),
        reply_error=MagicMock(),
        _get_reply_encryption_context=get_context,
        _set_reply_encryption_context=set_context,
        _reset_reply_encryption_context=reset_context,
        _command_error_message=MagicMock(return_value="friendly error"),
    )

    async def handler(*_args):
        seen.append(get_context())

    await ce.CommandExecutor(bot).execute(
        SimpleNamespace(handler=handler),
        _context(),
        MagicMock(),
    )

    assert seen == [True]
