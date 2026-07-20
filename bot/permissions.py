"""Bot role and permission helpers."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import slixmpp

from utils.command import Role, role_from_int

log = logging.getLogger(__name__)

_RATE_LIMIT_ROLE_ALIASES = {role.name.lower(): role for role in Role}


def configured_rate_limit_bypass_role(config: Mapping[str, Any]) -> Role | None:
    """Return the configured role threshold for rate-limit bypasses."""
    value = config.get("command_rate_limit_bypass_role", "moderator")
    if value is None or str(value).strip().lower() in {"", "none", "off", "false"}:
        return None
    return _RATE_LIMIT_ROLE_ALIASES.get(str(value).strip().lower(), Role.MODERATOR)


def role_bypasses_rate_limit(role: Role, config: Mapping[str, Any]) -> bool:
    """Return whether *role* is privileged enough to bypass command limits."""
    threshold = configured_rate_limit_bypass_role(config)
    return threshold is not None and role <= threshold


class PermissionMixin:
    """Role resolution helpers for the bot class."""

    def _parse_bare_jid(self, jid_value: object, *, label: str, fallback_to_none: bool = False) -> str | None:
        """Parse a JID and return its bare form as a string."""
        try:
            return slixmpp.JID(jid_value).bare
        except Exception as exc:
            mode = "none" if fallback_to_none else "strict"
            log.warning(
                "[BOT] Failed to parse %s JID '%s' (%s): %s",
                label,
                jid_value,
                mode,
                exc,
            )
            return None

    async def _get_owner_bare_jid(self) -> str | None:
        """Resolve the configured owner JID to its bare form."""
        try:
            import envsbot as app
            return slixmpp.JID(app.config["owner"]).bare
        except Exception as exc:
            log.warning("[BOT] Failed to parse owner JID: %s", exc)
            return None

    async def _get_room_role_from_presence(self, jid: str, room: str | None, db_role: Role) -> Role:
        """Elevate role to MODERATOR when the user is an admin/owner in the room."""
        if not room:
            return db_role
        try:
            from bot.room_state import JOINED_ROOMS

            room_info = JOINED_ROOMS.get(room)
            if not room_info:
                return db_role
            nicks = room_info.get("nicks", {})
            for nick_info in tuple(nicks.values()):
                try:
                    if str(nick_info.get("jid")) == str(jid):
                        affiliation = nick_info.get("affiliation", "")
                        if affiliation in ("admin", "owner") and db_role > Role.MODERATOR:
                            return Role.MODERATOR
                except Exception as exc:
                    log.debug("[BOT] Error checking room affiliation: %s", exc)
        except Exception:
            log.debug("[BOT] Could not inspect room presence state", exc_info=True)
        return db_role

    async def get_user_role(self, jid: object, room: str | None = None) -> Role:
        """Resolve a user's role using config and database.

        Every sender with a valid JID is a regular user by default.  Database
        rows only override that baseline (for example with a trusted, admin,
        new, or banned role); ``Role.NONE`` remains reserved for identities
        that cannot be resolved to a valid JID.
        """
        bare_jid = self._parse_bare_jid(jid, label="user")
        if bare_jid is None:
            return Role.NONE

        owner_jid = await self._get_owner_bare_jid()
        if owner_jid and bare_jid == owner_jid:
            return Role.OWNER

        row = await self.db.users.get(bare_jid)
        if row is None:
            return await self._get_room_role_from_presence(bare_jid, room, Role.USER)

        try:
            db_role = role_from_int(int(row["role"]))
        except (KeyError, TypeError, ValueError):
            return Role.NONE

        if db_role == Role.OWNER:
            log.warning("[BOT] Ignoring stored owner role for non-config user: %s", bare_jid)
            db_role = Role.USER
        elif db_role == Role.NONE:
            db_role = Role.USER

        return await self._get_room_role_from_presence(bare_jid, room, db_role)
