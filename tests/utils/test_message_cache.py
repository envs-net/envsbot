from __future__ import annotations

from collections import deque

import pytest

from utils import message_cache


class ExplodingMsg(dict):
    def __init__(self, *, explode_on: str):
        super().__init__()
        self.explode_on = explode_on

    def get(self, key, default=None):
        if key == self.explode_on:
            raise RuntimeError("boom")
        return super().get(key, default)


@pytest.fixture(autouse=True)
def clear_message_cache_state():
    message_cache._SHARED_MESSAGE_CACHES.clear()
    message_cache._SHARED_PROCESSED_STANZAS.clear()
    message_cache._SHARED_PROCESSED_STANZA_ORDER.clear()


def test_paginate_items_clamps_pages():
    items = [1, 2, 3, 4, 5]

    assert message_cache.paginate_items(items, 1, 2) == ([1, 2], 1, 3, 5)
    assert message_cache.paginate_items(items, 99, 2) == ([5], 3, 3, 5)
    assert message_cache.paginate_items(items, -1, 2) == ([1, 2], 1, 3, 5)
    assert message_cache.paginate_items([], 5, 10) == ([], 1, 1, 0)


def test_get_stanza_id_prefers_stanza_id_then_message_id():
    assert message_cache.get_stanza_id({"stanza_id": {"id": "stable"}, "id": "msg"}) == "stable"
    assert message_cache.get_stanza_id({"stanza_id": {}, "id": 123}) == "123"
    assert message_cache.get_stanza_id({}) is None
    assert message_cache.get_stanza_id(ExplodingMsg(explode_on="stanza_id")) is None


def test_remember_stanza_tracks_duplicates_and_eviction():
    assert message_cache.remember_stanza("test", None) is True
    assert message_cache.remember_stanza("test", "a") is True
    assert message_cache.remember_stanza("test", "a") is False

    message_cache._SHARED_PROCESSED_STANZA_ORDER["small"] = deque(maxlen=2)
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


def test_cache_message_and_lookup_by_room_and_id():
    message_cache.cache_message("plugin", "room", "Alice", "hello", "id1", extra={"ts": 1})
    message_cache.cache_message("plugin", "room", "Bob", "world", "id2")

    messages = message_cache.get_cached_messages("plugin", "room")
    assert [entry["body"] for entry in messages] == ["hello", "world"]
    assert messages[0]["ts"] == 1
    assert message_cache.get_last_cached_message("plugin", "room")["nick"] == "Bob"
    assert message_cache.get_cached_message_by_id("plugin", "room", "id1")["body"] == "hello"
    assert message_cache.get_cached_message_by_id("plugin", "room", "missing") is None
    assert message_cache.get_last_cached_message("plugin", "empty") is None

    message_cache.cache_message("plugin", "room", "Carol", "short", "id3", maxlen=1)
    assert [entry["body"] for entry in message_cache.get_cached_messages("plugin", "room")] == ["short"]
