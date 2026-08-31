from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.room_state import JOINED_ROOMS
from core_plugins.rooms import invites
from utils import admin_alerts, outbox, updatecheck


@pytest.mark.asyncio
async def test_outbox_rejoins_configured_notification_room(monkeypatch):
    JOINED_ROOMS.clear()
    join = AsyncMock(return_value=True)
    monkeypatch.setattr(outbox, "ensure_room_joined", join)
    bot = SimpleNamespace(
        config={"admin_report_jid": "admins@chat.example.org"}
    )
    runtime = outbox.PersistentOutbox(bot)

    assert await runtime._ensure_notification_room_ready(
        "admins@chat.example.org", "groupchat"
    ) is True
    join.assert_awaited_once_with(bot, "admins@chat.example.org")


@pytest.mark.asyncio
async def test_outbox_does_not_join_arbitrary_groupchat_destination(monkeypatch):
    JOINED_ROOMS.clear()
    join = AsyncMock(return_value=True)
    monkeypatch.setattr(outbox, "ensure_room_joined", join)
    runtime = outbox.PersistentOutbox(SimpleNamespace(config={}))

    assert await runtime._ensure_notification_room_ready(
        "random@chat.example.org", "groupchat"
    ) is False
    join.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_room_invite_refreshes_reason_and_timestamp(monkeypatch):
    bot = SimpleNamespace(
        db=SimpleNamespace(conn=None),
        pending_room_invites={
            7: {
                "id": 7,
                "room_jid": "room@conference.test",
                "inviter": "alice@example.org",
                "reason": "old reason",
                "created_at": 100,
            }
        },
        pending_room_invite_index={
            ("room@conference.test", "alice@example.org"): 7
        },
    )
    monkeypatch.setattr(invites.time, "time", lambda: 200)

    stored = await invites._store_pending_room_invite(
        bot,
        "room@conference.test",
        "alice@example.org",
        "new reason",
    )

    assert stored is bot.pending_room_invites[7]
    assert stored["reason"] == "new reason"
    assert stored["created_at"] == 200


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("1.8.4rc1", "1.8.4", -1),
        ("1.8.4", "1.8.4rc1", 1),
        ("1.8.4beta2", "1.8.4rc1", -1),
        ("1.8.4", "1.8.4.0", 0),
    ],
)
def test_compare_versions_handles_prereleases(left, right, expected):
    assert updatecheck.compare_versions(left, right) == expected


def test_remote_version_check_treats_stable_as_newer_than_rc():
    assert updatecheck.is_remote_version_newer("1.8.4", "1.8.4rc1") is True
    assert updatecheck.is_remote_version_newer("1.8.4rc1", "1.8.4") is False


@pytest.mark.asyncio
async def test_failed_admin_alert_does_not_start_cooldown(monkeypatch):
    send = AsyncMock(return_value=False)
    monkeypatch.setattr(admin_alerts, "notify_admin", send)
    monkeypatch.setattr(admin_alerts.time, "time", lambda: 10_000)
    manager = admin_alerts.AdminAlertManager(
        SimpleNamespace(config={"admin_alert_cooldown_seconds": 3600})
    )

    await manager._set("demo", True, "Demo failed", fingerprint="same")
    assert manager._states["demo"].last_notified_at == 0

    await manager._set("demo", True, "Demo failed", fingerprint="same")
    assert send.await_count == 2
    assert manager._states["demo"].last_notified_at == 0


@pytest.mark.asyncio
async def test_failed_resolution_remains_active_for_retry(monkeypatch):
    send = AsyncMock(side_effect=[True, False, True])
    monkeypatch.setattr(admin_alerts, "notify_admin", send)
    manager = admin_alerts.AdminAlertManager(SimpleNamespace(config={}))

    await manager._set("demo", True, "Demo failed", fingerprint="same")
    await manager._set("demo", False, "Demo recovered")
    assert manager._states["demo"].active is True

    await manager._set("demo", False, "Demo recovered")
    assert manager._states["demo"].active is False
