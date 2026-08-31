from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core_plugins.rooms import invites
from utils import admin_notify, updatecheck


@pytest.mark.asyncio
async def test_admin_notification_durably_queues_when_muc_target_is_unavailable(
    monkeypatch,
):
    bot = SimpleNamespace(
        config={"admin_report_jid": "admins@chat.example.org"},
        make_message=lambda **kwargs: kwargs,
    )
    prepare = AsyncMock(return_value=None)
    durable = AsyncMock(return_value=True)
    monkeypatch.setattr(admin_notify, "prepare_notification_target", prepare)
    monkeypatch.setattr(admin_notify, "durable_send", durable)

    assert await admin_notify.notify_admin(
        bot,
        "health",
        category="health",
        dedupe_key="health:1",
    ) is True

    prepare.assert_awaited_once_with(bot, "admins@chat.example.org")
    durable.assert_awaited_once_with(
        bot,
        {
            "mto": "admins@chat.example.org",
            "mbody": "health",
            "mtype": "groupchat",
        },
        category="health",
        dedupe_key="health:1",
    )


@pytest.mark.asyncio
async def test_update_notification_does_not_mark_failed_muc_join_as_sent(
    monkeypatch,
):
    monkeypatch.setitem(
        updatecheck.config,
        "version_check_notify_jid",
        "admins@chat.example.org",
    )
    monkeypatch.setitem(updatecheck.config, "owner", "owner@example.org")
    joined = AsyncMock(return_value=False)
    prepare = AsyncMock(return_value=None)
    monkeypatch.setattr(updatecheck, "ensure_notification_target_joined", joined)
    monkeypatch.setattr(updatecheck, "prepare_notification_target", prepare)

    safe_send = AsyncMock(return_value=True)
    bot = SimpleNamespace(
        make_message=lambda **kwargs: kwargs,
        _safe_send_message=safe_send,
    )

    assert await updatecheck.send_update_notification(bot, "9.9.9") is False

    joined.assert_awaited_once_with(bot, "admins@chat.example.org")
    prepare.assert_awaited_once_with(
        bot,
        "admins@chat.example.org",
        joined=False,
    )
    safe_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_notification_uses_prepared_message_type(monkeypatch):
    monkeypatch.setitem(
        updatecheck.config,
        "version_check_notify_jid",
        "admins@chat.example.org",
    )
    monkeypatch.setitem(updatecheck.config, "owner", "owner@example.org")
    monkeypatch.setattr(
        updatecheck,
        "ensure_notification_target_joined",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        updatecheck,
        "prepare_notification_target",
        AsyncMock(return_value="groupchat"),
    )

    safe_send = AsyncMock(return_value=True)
    bot = SimpleNamespace(
        make_message=lambda **kwargs: kwargs,
        _safe_send_message=safe_send,
    )

    assert await updatecheck.send_update_notification(bot, "9.9.9") is True
    message = safe_send.await_args.args[0]
    assert message["mtype"] == "groupchat"


@pytest.mark.asyncio
async def test_room_invite_notification_does_not_fall_back_to_direct_chat(
    monkeypatch,
):
    monkeypatch.setitem(
        invites.config,
        "room_invite_notify_jid",
        "admins@chat.example.org",
    )
    joined = AsyncMock(return_value=False)
    prepare = AsyncMock(return_value=None)
    monkeypatch.setattr(invites, "ensure_notification_target_joined", joined)
    monkeypatch.setattr(invites, "prepare_notification_target", prepare)

    safe_send = AsyncMock(return_value=True)
    bot = SimpleNamespace(
        make_message=lambda **kwargs: kwargs,
        _safe_send_message=safe_send,
    )

    await invites._notify_room_invite(bot, "new invite")

    joined.assert_awaited_once_with(bot, "admins@chat.example.org")
    prepare.assert_awaited_once_with(
        bot,
        "admins@chat.example.org",
        joined=False,
    )
    safe_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_room_invite_notification_uses_prepared_message_type(monkeypatch):
    monkeypatch.setitem(
        invites.config,
        "room_invite_notify_jid",
        "admins@chat.example.org",
    )
    monkeypatch.setattr(
        invites,
        "ensure_notification_target_joined",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        invites,
        "prepare_notification_target",
        AsyncMock(return_value="groupchat"),
    )

    safe_send = AsyncMock(return_value=True)
    bot = SimpleNamespace(
        make_message=lambda **kwargs: kwargs,
        _safe_send_message=safe_send,
    )

    await invites._notify_room_invite(bot, "new invite")
    message = safe_send.await_args.args[0]
    assert message["mtype"] == "groupchat"
