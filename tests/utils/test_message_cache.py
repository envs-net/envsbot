from __future__ import annotations

import asyncio
from collections import deque
import pytest

from utils import message_cache


class ExplodingMsg:
    def __init__(self, *, explode_on: str):
        self.explode_on = explode_on

    def get(self, key, default=None):
        if key == self.explode_on:
            raise RuntimeError("boom")
        return default


class DummyFrom:
    def __init__(self, bare: str, resource: str = ""):
        self.bare = bare
        self.resource = resource

    def __str__(self):
        return f"{self.bare}/{self.resource}" if self.resource else self.bare


class FakeStore:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.saved = []
        self.cleared = []

    async def load_recent(self, limit, *, min_received_at=None):
        rows = self.rows
        if min_received_at is not None:
            rows = [
                row
                for row in rows
                if int(row.get("received_at") or 0) >= min_received_at
            ]
        return rows[-limit:]

    async def save_batch(self, entries, *, limit_per_conversation):
        self.saved.extend(dict(entry) for entry in entries)
        self.rows.extend(dict(entry) for entry in entries)
        by_conversation = {}
        for row in self.rows:
            by_conversation.setdefault(row["conversation"], []).append(row)
        self.rows = [
            row
            for rows in by_conversation.values()
            for row in rows[-limit_per_conversation:]
        ]

    async def clear_conversation(self, conversation):
        self.cleared.append(conversation)
        before = len(self.rows)
        self.rows = [row for row in self.rows if row["conversation"] != conversation]
        return before - len(self.rows)


@pytest.fixture(autouse=True)
def clear_message_cache_state():
    message_cache._PROCESSED_STANZAS.clear()
    message_cache._PROCESSED_STANZA_ORDER.clear()


def test_get_stanza_id_prefers_stanza_id_then_message_id():
    assert message_cache.get_stanza_id(
        {"stanza_id": {"id": "stable"}, "id": "msg"}
    ) == "stable"
    assert message_cache.get_stanza_id({"stanza_id": {}, "id": 123}) == "123"
    assert message_cache.get_stanza_id({}) is None
    assert message_cache.get_stanza_id(
        ExplodingMsg(explode_on="stanza_id")
    ) is None


def test_remember_stanza_tracks_duplicates_and_eviction():
    assert message_cache.remember_stanza("test", None) is True
    assert message_cache.remember_stanza("test", "a") is True
    assert message_cache.remember_stanza("test", "a") is False

    message_cache._PROCESSED_STANZA_ORDER["small"] = deque(maxlen=2)
    assert message_cache.remember_stanza("small", "one") is True
    assert message_cache.remember_stanza("small", "two") is True
    assert message_cache.remember_stanza("small", "three") is True
    assert message_cache.remember_stanza("small", "one") is True


def test_reply_helpers_extract_target_and_quote():
    assert message_cache.get_reply_target({"reply": {"id": "reply-id"}}) == "reply-id"
    assert message_cache.get_reply_target({"reply": {}}) is None
    assert message_cache.get_reply_target(ExplodingMsg(explode_on="reply")) is None
    assert message_cache.extract_reply_quote("> first\n> second\nanswer") == "first\nsecond"
    assert message_cache.extract_reply_quote(">\nanswer") is None
    assert message_cache.extract_reply_quote("") is None


def test_conversation_key_isolates_muc_private_messages():
    room = "room@conference.example.org"
    groupchat = {
        "from": DummyFrom(room, "alice"),
        "type": "groupchat",
    }
    muc_pm = {"from": DummyFrom(room, "alice"), "type": "chat"}
    direct = {"from": DummyFrom("alice@example.org", "phone"), "type": "chat"}

    assert message_cache.conversation_key(groupchat, is_room=True) == room
    assert message_cache.conversation_key(
        muc_pm,
        is_room=False,
        joined_rooms={room: "bot"},
    ) == f"mucpm:{room}/alice"
    assert message_cache.conversation_key(direct, is_room=False) == "alice@example.org"


@pytest.mark.asyncio
async def test_shared_cache_eviction_lookup_and_persisted_writer():
    store = FakeStore()
    cache = message_cache.MessageCache(max_messages=2)
    await cache.start(store)

    assert await cache.add_entry(
        {
            "conversation": "room",
            "body": "one",
            "stanza_id": "id1",
            "nick": "Alice",
            "received_at": 1,
        }
    )
    assert await cache.add_entry(
        {
            "conversation": "room",
            "body": "two",
            "stanza_id": "id2",
            "nick": "Bob",
            "received_at": 2,
        }
    )
    assert await cache.add_entry(
        {
            "conversation": "room",
            "body": "three",
            "stanza_id": "id3",
            "nick": "Carol",
            "received_at": 3,
        }
    )
    assert not await cache.add_entry(
        {"conversation": "room", "body": "duplicate", "stanza_id": "id3"}
    )

    assert [entry["body"] for entry in cache.get_messages("room")] == ["two", "three"]
    assert cache.get_by_id("room", "id1") is None
    assert cache.get_by_id("room", "id2")["nick"] == "Bob"
    assert cache.get_messages("room", limit=0) == []
    assert cache.get_last("room")["body"] == "three"
    assert cache.stats("room")["messages"] == 2

    await cache.close()
    assert [entry["body"] for entry in store.saved] == ["one", "two", "three"]


@pytest.mark.asyncio
async def test_add_message_and_clear_conversation():
    store = FakeStore()
    cache = message_cache.MessageCache(max_messages=5)
    await cache.start(store)
    msg = {
        "body": " Hello ",
        "from": DummyFrom("room@conference.example.org", "alice"),
        "type": "groupchat",
        "mucnick": "alice",
        "id": "msg-1",
    }

    assert await cache.add_message(msg, is_room=True)
    entry = cache.get_by_id("room@conference.example.org", "msg-1")
    assert entry["body"] == "Hello"
    assert entry["nick"] == "alice"
    assert await cache.clear_conversation("room@conference.example.org") == 1
    assert cache.get_messages("room@conference.example.org") == []
    assert store.cleared == ["room@conference.example.org"]
    await cache.close()
    assert store.rows == []


@pytest.mark.asyncio
async def test_cache_can_restart_without_duplicating_loaded_messages():
    store = FakeStore()
    cache = message_cache.MessageCache(max_messages=5)
    await cache.start(store)
    await cache.add_entry({
        "conversation": "room",
        "body": "hello",
        "stanza_id": "id-1",
    })
    await cache.close()

    await cache.start(store)
    assert [entry["body"] for entry in cache.get_messages("room")] == ["hello"]
    await cache.close()


@pytest.mark.asyncio
async def test_cache_reports_and_retries_persistence_failure(monkeypatch):
    class FlakyStore(FakeStore):
        def __init__(self):
            super().__init__()
            self.fail = True

        async def save_batch(self, entries, *, limit_per_conversation, **_kwargs):
            if self.fail:
                raise RuntimeError("db unavailable")
            await super().save_batch(entries, limit_per_conversation=limit_per_conversation)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(message_cache.asyncio, "sleep", no_sleep)
    store = FlakyStore()
    cache = message_cache.MessageCache(max_messages=5, max_age_days=0)
    await cache.start(store)
    await cache.add_entry({"conversation": "room", "body": "one"})
    await cache._queue.join()
    assert cache.stats()["degraded"] is True
    assert cache.stats()["retry_backlog"] == 1

    store.fail = False
    await cache.add_entry({"conversation": "room", "body": "two"})
    await cache._queue.join()
    assert cache.stats()["degraded"] is False
    assert [entry["body"] for entry in store.saved] == ["one", "two"]
    await cache.close()


@pytest.mark.asyncio
async def test_cache_counts_entries_dropped_from_bounded_retry_backlog(monkeypatch):
    class FailingStore(FakeStore):
        async def save_batch(self, entries, *, limit_per_conversation, **_kwargs):
            raise RuntimeError("database unavailable")

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(message_cache.asyncio, "sleep", no_sleep)
    cache = message_cache.MessageCache(max_messages=1, max_age_days=0)
    cache._retry_backlog = deque(maxlen=2)
    await cache.start(FailingStore())
    for number in range(4):
        await cache.add_entry({
            "conversation": "room",
            "body": f"message-{number}",
        })
    await cache._queue.join()

    stats = cache.stats()
    assert stats["retry_backlog"] == 2
    assert stats["dropped_persistence_entries"] == 2
    assert stats["degraded"] is True
    await cache.close()


@pytest.mark.asyncio
async def test_cache_age_limit_ignores_stale_loaded_rows(monkeypatch):
    now = 2_000_000_000
    monkeypatch.setattr(message_cache.time, "time", lambda: now)
    store = FakeStore(rows=[
        {"cache_key": "old", "conversation": "room", "body": "old", "received_at": now - 40 * 86400},
        {"cache_key": "new", "conversation": "room", "body": "new", "received_at": now - 10},
    ])
    cache = message_cache.MessageCache(max_messages=5, max_age_days=30)
    await cache.start(store)
    assert [entry["body"] for entry in cache.get_messages("room")] == ["new"]
    await cache.close()


@pytest.mark.asyncio
async def test_message_cache_writer_is_tracked_as_core_service():
    from utils.task_supervisor import TaskSupervisor

    supervisor = TaskSupervisor()
    cache = message_cache.MessageCache(max_messages=5, task_supervisor=supervisor)
    await cache.start(FakeStore())

    infos = supervisor.snapshot(include_done=False)
    writer = next(info for info in infos if info.name == "message-cache-writer")
    assert writer.plugin == "_core"
    assert writer.kind == "service"

    await cache.close()
    await asyncio.sleep(0)
    assert all(
        info.name != "message-cache-writer"
        for info in supervisor.snapshot(include_done=True)
    )
