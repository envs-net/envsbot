import pytest

from database.manager import DatabaseManager


@pytest.mark.asyncio
async def test_outbox_deduplicates_claims_and_marks_sent(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        first = await db.outbox.enqueue(
            destination="room@example.org",
            body="hello",
            message_type="groupchat",
            category="rss",
            dedupe_key="rss:one",
        )
        second = await db.outbox.enqueue(
            destination="room@example.org",
            body="hello updated",
            message_type="groupchat",
            category="rss",
            dedupe_key="rss:one",
        )
        assert first == second
        assert (await db.outbox.counts())["pending"] == 1

        claimed = await db.outbox.claim_due(limit=10)
        assert len(claimed) == 1
        assert claimed[0].body == "hello updated"
        assert (await db.outbox.counts())["inflight"] == 1

        await db.outbox.mark_sent(claimed[0].id)
        assert await db.outbox.counts() == {
            "pending": 0,
            "inflight": 0,
            "dead": 0,
            "total": 0,
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_outbox_defer_does_not_consume_attempt_and_failure_can_die(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        message_id = await db.outbox.enqueue(
            destination="room@example.org",
            body="hello",
            message_type="groupchat",
            category="rss",
            dedupe_key="rss:defer",
            max_attempts=2,
        )
        message = (await db.outbox.claim_due())[0]
        await db.outbox.defer(message.id, retry_delay_seconds=1, reason="not joined")
        row = await db.fetch_one(
            "SELECT status, attempts, last_error FROM outbox_messages WHERE id=?",
            (message_id,),
        )
        assert dict(row) == {
            "status": "pending",
            "attempts": 0,
            "last_error": "not joined",
        }

        await db.execute(
            "UPDATE outbox_messages SET available_at=0 WHERE id=?",
            (message_id,),
        )
        message = (await db.outbox.claim_due())[0]
        assert await db.outbox.mark_failed(
            message, RuntimeError("temporary"), retry_delay_seconds=1
        ) is False
        await db.execute(
            "UPDATE outbox_messages SET available_at=0 WHERE id=?",
            (message_id,),
        )
        message = (await db.outbox.claim_due())[0]
        assert await db.outbox.mark_failed(
            message, RuntimeError("permanent"), retry_delay_seconds=1
        ) is True
        assert (await db.outbox.counts())["dead"] == 1
        assert await db.outbox.retry_dead(category="rss") == 1
        assert (await db.outbox.counts())["pending"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_outbox_recovers_inflight_rows_after_restart(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        await db.outbox.enqueue(
            destination="user@example.org",
            body="hello",
            message_type="chat",
            dedupe_key="message:recover",
        )
        assert len(await db.outbox.claim_due()) == 1
        assert await db.outbox.recover_inflight(older_than_seconds=0) == 1
        assert (await db.outbox.counts())["pending"] == 1
    finally:
        await db.close()
