"""Shared durable admin-notification helper."""

from __future__ import annotations

from typing import Any

from utils.outbox import durable_send


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
    message_type = "groupchat" if "@conference." in target or "@muc." in target else "chat"
    message = bot.make_message(mto=target, mbody=str(text), mtype=message_type)
    return await durable_send(
        bot,
        message,
        category=category,
        dedupe_key=dedupe_key,
    )
