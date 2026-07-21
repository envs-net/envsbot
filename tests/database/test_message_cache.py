from __future__ import annotations

import pytest

from database.manager import DatabaseManager
from utils.message_cache import MessageCache


@pytest.mark.asyncio
async def test_message_cache_survives_restart_and_prunes_per_conversation(tmp_db_path):
    db = DatabaseManager(tmp_db_path)
    await db.connect()

    first = MessageCache(max_messages=3, max_age_days=0)
    await first.start(db.message_cache)
    for index in range(3):
        await first.add_entry(
            {
                "conversation": "room@conference.example.org",
                "body": f"message-{index}",
                "stanza_id": f"id-{index}",
                "nick": "alice",
                "received_at": index + 1,
            }
        )
    await first.close()

    second = MessageCache(max_messages=2, max_age_days=0)
    await second.start(db.message_cache)
    assert [
        entry["body"]
        for entry in second.get_messages("room@conference.example.org")
    ] == ["message-1", "message-2"]
    assert second.get_by_id("room@conference.example.org", "id-0") is None
    assert second.get_by_id("room@conference.example.org", "id-2")["nick"] == "alice"
    assert await db.message_cache.count() == 2

    await second.close()
    await db.close()
