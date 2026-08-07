import pytest

from database.manager import DatabaseManager
from database.outbox import OutboxCapacityError


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
        origin_before = (
            await db.fetch_one(
                "SELECT origin_id FROM outbox_messages WHERE id=?",
                (first,),
            )
        )["origin_id"]
        second = await db.outbox.enqueue(
            destination="room@example.org",
            body="hello updated",
            message_type="groupchat",
            category="rss",
            dedupe_key="rss:one",
            origin_id="must-not-replace-existing",
        )
        assert first == second
        assert (await db.outbox.counts())["pending"] == 1
        origin_after = (
            await db.fetch_one(
                "SELECT origin_id FROM outbox_messages WHERE id=?",
                (first,),
            )
        )["origin_id"]
        assert origin_after == origin_before

        claimed = await db.outbox.claim_due(limit=10)
        assert len(claimed) == 1
        assert claimed[0].body == "hello updated"
        assert claimed[0].origin_id == origin_before
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


@pytest.mark.asyncio
async def test_outbox_enforces_global_destination_category_and_byte_limits(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        await db.outbox.enqueue(
            destination="a@example.org",
            body="one",
            category="rss",
            max_pending=2,
            max_bytes=1024,
            max_per_destination=1,
            max_per_category=2,
        )
        with pytest.raises(OutboxCapacityError, match="destination limit"):
            await db.outbox.enqueue(
                destination="a@example.org",
                body="two",
                category="other",
                max_pending=2,
                max_bytes=1024,
                max_per_destination=1,
                max_per_category=2,
            )
        await db.outbox.enqueue(
            destination="b@example.org",
            body="two",
            category="rss",
            max_pending=2,
            max_bytes=1024,
            max_per_destination=1,
            max_per_category=2,
        )
        with pytest.raises(OutboxCapacityError, match="pending message limit"):
            await db.outbox.enqueue(
                destination="c@example.org",
                body="three",
                category="rss",
                max_pending=2,
                max_bytes=1024,
                max_per_destination=1,
                max_per_category=3,
            )

        await db.outbox.delete_dead()
        await db.execute("DELETE FROM outbox_messages")
        await db.outbox.enqueue(
            destination="a@example.org",
            body="one",
            category="rss",
            max_per_category=1,
        )
        with pytest.raises(OutboxCapacityError, match="category limit"):
            await db.outbox.enqueue(
                destination="b@example.org",
                body="two",
                category="rss",
                max_per_category=1,
            )

        await db.execute("DELETE FROM outbox_messages")
        with pytest.raises(OutboxCapacityError, match="queue byte limit"):
            await db.outbox.enqueue(
                destination="a@example.org",
                body="payload",
                max_bytes=4,
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_outbox_claim_due_is_fair_between_destinations(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        for index in range(3):
            await db.outbox.enqueue(
                destination="busy@example.org",
                body=f"busy-{index}",
                dedupe_key=f"busy:{index}",
            )
        await db.outbox.enqueue(
            destination="quiet@example.org",
            body="quiet",
            dedupe_key="quiet:1",
        )

        claimed = await db.outbox.claim_due(limit=2)
        assert {item.destination for item in claimed} == {
            "busy@example.org",
            "quiet@example.org",
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_outbox_dead_letter_retention_prunes_old_rows(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        message_id = await db.outbox.enqueue(
            destination="dead@example.org",
            body="dead",
            max_attempts=1,
        )
        message = (await db.outbox.claim_due())[0]
        assert await db.outbox.mark_failed(
            message, RuntimeError("dead"), retry_delay_seconds=1
        ) is True
        await db.execute("UPDATE outbox_messages SET dead_at=0 WHERE id=?", (message_id,))
        assert await db.outbox.prune_dead(retention_days=1) == 1
        assert (await db.outbox.counts())["dead"] == 0
    finally:
        await db.close()

@pytest.mark.asyncio
async def test_outbox_retry_keeps_stable_origin_id(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect(start_background=False)
    try:
        message_id = await db.outbox.enqueue(
            destination="user@example.org",
            body="retry me",
            origin_id="stable-origin",
            max_attempts=2,
        )
        claimed = (await db.outbox.claim_due())[0]
        assert claimed.origin_id == "stable-origin"
        assert await db.outbox.mark_failed(
            claimed, RuntimeError("temporary"), retry_delay_seconds=1
        ) is False
        await db.execute(
            "UPDATE outbox_messages SET available_at=0 WHERE id=?",
            (message_id,),
        )
        retried = (await db.outbox.claim_due())[0]
        assert retried.origin_id == "stable-origin"
    finally:
        await db.close()
