from __future__ import annotations

from types import SimpleNamespace

import pytest

from utils import room_toggles
from utils import xmpp_identity


class FakeJid:
    def __init__(self, bare: str, resource: str | None = None):
        self.bare = bare
        self.resource = resource


class FakeMsg(dict):
    def __init__(self, from_bare: str, resource: str | None = None, type_: str = "chat"):
        super().__init__()
        self["from"] = FakeJid(from_bare, resource)
        self["type"] = type_


@pytest.mark.asyncio
async def test_get_jids_from_nick_index_returns_single_jid_for_all_shapes():
    bot = SimpleNamespace(
        db=SimpleNamespace(
            users=SimpleNamespace(
                _nick_index={
                    "setnick": {"jid-a@example.test", "jid-b@example.test"},
                    "listnick": ["jid-c@example.test", "jid-d@example.test"],
                    "tuplenick": ("jid-e@example.test", "jid-f@example.test"),
                    "singlenick": "jid-g@example.test",
                    "emptynick": [],
                }
            )
        )
    )

    assert await xmpp_identity.get_jids_from_nick_index(bot, "setnick") in {
        "jid-a@example.test",
        "jid-b@example.test",
    }
    assert await xmpp_identity.get_jids_from_nick_index(bot, "listnick") == "jid-c@example.test"
    assert await xmpp_identity.get_jids_from_nick_index(bot, "tuplenick") == "jid-e@example.test"
    assert await xmpp_identity.get_jids_from_nick_index(bot, "singlenick") == "jid-g@example.test"
    assert await xmpp_identity.get_jids_from_nick_index(bot, "emptynick") is None
    assert await xmpp_identity.get_jids_from_nick_index(bot, "missing") is None


def test_room_toggle_disabled_message_uses_neutral_icon():
    assert room_toggles._format_disabled("Feature") == "ℹ️ Feature disabled in this room."


@pytest.mark.asyncio
async def test_muc_pm_manage_room_reports_missing_joined_room(monkeypatch):
    monkeypatch.setattr(xmpp_identity, "JOINED_ROOMS", {})

    allowed, room_jid, reason = await xmpp_identity.muc_pm_sender_can_manage_room(
        SimpleNamespace(),
        FakeMsg("room@example.test", "Alice"),
        is_room=False,
    )

    assert allowed is False
    assert room_jid == "room@example.test"
    assert reason == "⛔ Bot is not currently in that room."
