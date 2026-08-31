"""Shared durable admin-notification helper."""

from __future__ import annotations

import logging
from typing import Any

from utils.outbox import durable_send
from utils.xmpp_notify import prepare_notification_target

log = logging.getLogger(__name__)


def admin_notify_target(bot: Any) -> str:
    config = getattr(bot, "config", {}) or {}
    for key in (
        "admin_report_jid",
        "version_check_notify_jid",
        "room_invite_notify_jid",
        "owner",
    ):
        value = str(config.get(key, "") or "").strip()
        if value:
            return value
    return ""


async def notify_admin(
    bot: Any,
    text: str,
    *,
    category: str = "admin",
    dedupe_key: str | None = None,
) -> bool:
    target = admin_notify_target(bot)
    if not target:
        return False

    message_type = await prepare_notification_target(bot, target)
    if message_type is None:
        log.warning(
            "Admin notification deferred: MUC target %s is unavailable",
            target,
        )
        return False

    message = bot.make_message(mto=target, mbody=str(text), mtype=message_type)
    return await durable_send(
        bot,
        message,
        category=category,
        dedupe_key=dedupe_key,
    )
