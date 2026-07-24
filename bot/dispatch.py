"""Command dispatch and sender context resolution."""

from __future__ import annotations

import logging
from typing import Any

import slixmpp

from bot.context import CommandContext
from bot.permissions import role_bypasses_rate_limit
from utils.command import Role, is_command_group
from utils.command_execution import CommandExecutionContext
from utils.permissions import can_execute_command

log = logging.getLogger(__name__)


class CommandDispatchMixin:
    """Message context resolution and unified command handling."""

    def _joined_room_jids(self) -> set[str]:
        """Return known joined room bare JIDs from runtime room state."""
        rooms: set[str] = set()
        try:
            rooms.update(str(room) for room in getattr(self.presence, "joined_rooms", {}))
        except Exception:
            log.debug("[MUC] Could not inspect presence joined rooms", exc_info=True)
        try:
            from bot.room_state import JOINED_ROOMS

            rooms.update(str(room) for room in JOINED_ROOMS)
        except Exception:
            log.debug("[MUC] Could not inspect plugin joined rooms", exc_info=True)
        return rooms

    def _is_muc_private_message(self, msg: Any) -> bool:
        """Return True for a private message sent via a MUC occupant JID."""
        try:
            msg_type = msg.get("type", "chat")
            from_jid = msg["from"]
            room = str(from_jid.bare)
            nick = getattr(from_jid, "resource", None)
        except Exception:
            return False
        return msg_type in ("chat", "normal") and bool(nick) and room in self._joined_room_jids()

    def _get_message_room_and_nick(self, msg: Any) -> tuple[str | None, str | None]:
        """Resolve room and nick from a message if possible."""
        room = None
        nick = None
        try:
            from_jid = msg["from"]
            room = from_jid.bare
            nick = msg.get("mucnick") or msg["from"].resource
        except Exception as exc:
            log.debug("[MUC] Could not resolve message room/nick: %s", exc)
        return room, nick

    def _lookup_muc_occupant_jid(self, room: str | None, nick: str | None) -> Any:
        """Resolve a MUC occupant's real JID from live MUC state."""
        muc = getattr(self, "plugin", {}).get("xep_0045", None)
        if muc:
            try:
                jid = muc.get_jid_property(room, nick, "jid")
                if jid:
                    return jid
            except Exception:
                log.debug("[BOT] Error getting JID from XEP-0045 state", exc_info=True)

        try:
            from bot.room_state import JOINED_ROOMS

            room_data = JOINED_ROOMS.get(room, {}) or {}
            nick_data = (room_data.get("nicks", {}) or {}).get(nick, {}) or {}
            jid = nick_data.get("jid")
            if jid:
                return jid
        except Exception:
            log.debug("[BOT] Error getting JID from joined room state", exc_info=True)
        return None

    def _bare_jid_value(self, jid_value: Any) -> str:
        """Return a best-effort bare JID string without leaking resources."""
        bare = getattr(jid_value, "bare", None)
        if bare:
            return str(bare)
        return str(jid_value).split("/", 1)[0]

    def _resolve_sender_jid(self, msg: Any, sender_jid: Any, nick: str | None) -> tuple[str, str | None]:
        """Resolve the real sender JID for room messages, with fallback."""
        jid = None
        room = None
        msg_type = msg.get("type", "chat")

        if msg_type in ("chat", "normal") and not self._is_muc_private_message(msg):
            return self._bare_jid_value(sender_jid), None

        try:
            room, nick = self._get_message_room_and_nick(msg)
            jid = self._lookup_muc_occupant_jid(room, nick)
        except Exception:
            log.debug("[BOT] Error getting JID from MUC context", exc_info=True)

        if jid is None:
            return self._bare_jid_value(sender_jid), room

        try:
            return str(slixmpp.JID(jid).bare), room
        except Exception as exc:
            log.warning("[BOT] Failed to parse resolved JID: %s", exc)
            return str(sender_jid), room

    def _command_error_message(self, user_role: Role, cmd_name: str, error: Exception) -> str:
        """Preserve the existing public/internal error wording."""
        if user_role in (Role.OWNER, Role.ADMIN):
            return f"🔴 Command error: {error}"
        return f"🔴 Command '{cmd_name}' failed due to internal error."

    def _is_loaded_plugin_help_target(self, text: str) -> bool:
        """Return whether *text* exactly names one loaded plugin."""
        tokens = tuple(part.lower() for part in str(text).split() if part)
        if len(tokens) != 1:
            return False
        try:
            plugins = getattr(getattr(self, "bot_plugins", None), "plugins", {})
            return any(str(name).lower() == tokens[0] for name in plugins)
        except Exception:
            log.debug("[COMMAND] Could not inspect loaded plugin names", exc_info=True)
            return False

    async def build_command_context(
        self,
        body: str,
        sender_jid: Any,
        nick: str | None,
        msg: Any,
        is_room: bool,
        cmd_obj: Any,
        args: list[str],
    ) -> CommandContext:
        """Resolve sender, room and role into a reusable command context."""
        jid, room = self._resolve_sender_jid(msg, sender_jid, nick)
        role = await self.get_user_role(jid, room)
        return CommandContext(
            command_name=cmd_obj.name,
            sender_jid=jid,
            nick=nick,
            room=room,
            is_room=is_room,
            is_muc_pm=self._is_muc_private_message(msg),
            role=role,
            args=tuple(args),
            raw_body=body,
        )

    async def handle_command(self, body: str | None, sender_jid: Any, nick: str | None, msg: Any, is_room: bool) -> None:
        """Parse and execute a bot command from a message."""
        if not body:
            return
        if not body.startswith(self.prefix):
            return
        if not getattr(self, "accepting_commands", True):
            self.reply(msg, "🔴 Bot is shutting down; please retry shortly.")
            return

        text = body[len(self.prefix):].strip()
        if not text:
            return

        import envsbot as app
        cmd_obj, args = app.resolve_command(text)
        if not cmd_obj and (
            is_command_group(text) or self._is_loaded_plugin_help_target(text)
        ):
            cmd_obj, _ = app.resolve_command("help")
            args = text.split()
        if not cmd_obj:
            return

        context = await self.build_command_context(body, sender_jid, nick, msg, is_room, cmd_obj, args)

        if self.config.get("command_rate_limit_enabled", True) and not role_bypasses_rate_limit(context.role, self.config):
            allowed, retry_after = await self.rate_limiter.allow(context.sender_jid)
            if not allowed:
                if self.rate_limiter.notify_allowed(context.sender_jid):
                    log.info(
                        "[COMMAND] event=rate_limited actor=%s room=%s retry_after=%.1fs",
                        context.sender_jid,
                        context.room,
                        retry_after,
                    )
                return

        from utils.permissions import configured_room_invite_admin_rooms

        invite_admin_rooms = configured_room_invite_admin_rooms(self.config)

        decision = can_execute_command(
            context,
            cmd_obj,
            room_invite_admin_rooms=invite_admin_rooms,
            permission_checker=app.check_permission,
        )
        if not decision.allowed:
            self.reply(msg, decision.reason)
            return

        execution_context = CommandExecutionContext(
            command_name=context.command_name,
            sender_jid=context.sender_jid,
            nick=context.nick,
            room=context.room,
            is_room=context.is_room,
            role=context.role,
            args=context.args,
        )
        await self.command_executor.execute(cmd_obj, execution_context, msg)
