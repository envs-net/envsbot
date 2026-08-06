from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import core_plugins.outbox as plugin


@pytest.mark.asyncio
async def test_outbox_status_and_retry_commands():
    runtime = SimpleNamespace(
        runtime_state=AsyncMock(return_value={
            "worker_running": True,
            "pending": 2,
            "inflight": 0,
            "dead": 1,
            "oldest_pending_age_seconds": 10,
            "delivered_since_start": 5,
            "failed_attempts_since_start": 1,
            "last_error": None,
        }),
        wakeup=SimpleNamespace(set=MagicMock()),
    )
    store = SimpleNamespace(retry_dead=AsyncMock(return_value=1))
    bot = SimpleNamespace(
        outbox=runtime,
        db=SimpleNamespace(outbox=store),
        prefix=",",
        reply=MagicMock(),
        reply_ok=MagicMock(),
        reply_error=MagicMock(),
        reply_usage=MagicMock(),
    )
    msg = MagicMock()

    await plugin.outbox_command(bot, "a", "a", ["status"], msg, False)
    assert "pending: 2" in "\n".join(bot.reply.call_args.args[1])

    await plugin.outbox_command(bot, "a", "a", ["retry", "rss"], msg, False)
    store.retry_dead.assert_awaited_once_with(category="rss")
    runtime.wakeup.set.assert_called_once()
