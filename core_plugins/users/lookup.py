"""Split module for core_plugins/users.py: lookup."""

import inspect
from slixmpp import JID

from .roles import GRANTABLE_PLUGINS


async def find_users_by_nick_safe(bot, nick: str):
    """
    Find users by nick using cache and fallback scan.
    """
    index = bot.db.users._nick_index
    return sorted(list(index.get(nick, [])))


def _parse_user_jid(value: str) -> str | None:
    """Return a bare user JID, rejecting room-only or malformed values."""
    try:
        jid = JID(str(value).strip())
    except Exception:
        return None

    if not jid.user or not jid.domain:
        return None

    return str(jid.bare)


def _plugin_name(value: str) -> str:
    """Normalize plugin grant names for storage and lookup."""
    return str(value or "").strip().lower().replace("-", "_")


def _valid_plugin_names(names) -> tuple[list[str], list[str]]:
    """Return (valid, invalid) plugin grant names without duplicates."""
    valid = []
    invalid = []
    for raw in names:
        name = _plugin_name(raw)
        if not name:
            continue
        if name not in GRANTABLE_PLUGINS:
            invalid.append(str(raw))
            continue
        if name not in valid:
            valid.append(name)
    return valid, invalid


async def _maybe_await(value):
    """Await awaitable values returned by slixmpp helpers."""
    if inspect.isawaitable(value):
        return await value
    return value
