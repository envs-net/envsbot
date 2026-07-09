#!/usr/bin/env python3

# envsbot: Modular XMPP Bot Framework
# Author: dan <mailto:fab@redterminal.org>
# Author: creme <mailto:creme@envs.net>
# License: GPL-3.0

import slixmpp
import asyncio
import inspect
import logging
import os
import shutil
import subprocess

from slixmpp.xmlstream import ET

from datetime import datetime
from utils.presence_manager import PresenceManager
from utils.plugin_manager import PluginManager
from utils.rate_limiter import TokenBucketRateLimiter
from utils.task_supervisor import TaskSupervisor
from utils.version import __version__
from utils.config import (
    ConfigError,
    config,
    exit_on_config_error,
    setup_logging,
    validate_startup_config,
)
from utils.command import (
    resolve_command,
    check_permission,
    Role,
    role_from_int,
)
from utils.command_execution import CommandExecutionContext, CommandExecutor
from database.manager import DatabaseManager

# === set up logging ===
setup_logging()
log = logging.getLogger(__name__)


_RATE_LIMIT_ROLE_ALIASES = {
    role.name.lower(): role for role in Role
}


def _configured_rate_limit_bypass_role() -> Role | None:
    """Return the configured role threshold for rate-limit bypasses."""
    value = config.get("command_rate_limit_bypass_role", "moderator")
    if value is None or str(value).strip().lower() in {"", "none", "off", "false"}:
        return None
    return _RATE_LIMIT_ROLE_ALIASES.get(str(value).strip().lower(), Role.MODERATOR)


def _role_bypasses_rate_limit(role: Role) -> bool:
    """Return whether *role* is privileged enough to bypass command limits."""
    threshold = _configured_rate_limit_bypass_role()
    return threshold is not None and role <= threshold


# -------------------------------------------------
# XMPP CONNECTION HELPERS
# -------------------------------------------------


def _get_configured_resource():
    """Return the optional configured XMPP resource."""
    resource = config.get("resource")
    if resource is None:
        return None

    resource = str(resource).strip()
    return resource or None


def _build_client_jid(jid, resource=None):
    """Build the login JID, optionally replacing/adding a resource."""
    jid = str(jid)
    if not resource:
        return jid

    bare_jid = jid.split("/", 1)[0]
    return f"{bare_jid}/{resource}"


def _configured_jid_domain():
    """Return the domain part of the configured bot JID if available."""
    jid = str(config.get("jid", ""))
    if "@" not in jid:
        return None
    domain = jid.split("@", 1)[1].split("/", 1)[0].strip()
    return domain or None


def _boundjid_domain(xmpp):
    """Return a best-effort domain from Slixmpp's bound JID object."""
    boundjid = getattr(xmpp, "boundjid", None)
    if boundjid is None:
        return None

    for attribute in ("domain", "host"):
        value = getattr(boundjid, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _connect_signature_parameters(connect_method):
    """Return inspectable connect() parameters, or an empty mapping."""
    try:
        return inspect.signature(connect_method).parameters
    except (TypeError, ValueError):
        return {}


def _connect_kwargs(xmpp):
    """Build kwargs for xmpp.connect() without passing unsupported names."""
    host = config.get("host") or _configured_jid_domain() or _boundjid_domain(xmpp)
    port = config.get("port")
    direct_tls = bool(config.get("direct_tls", False))

    parameters = _connect_signature_parameters(xmpp.connect)
    kwargs = {}

    if "address" in parameters and host and port is not None:
        kwargs["address"] = (host, int(port))
    else:
        if "host" in parameters and host:
            kwargs["host"] = host
        if "port" in parameters and port is not None:
            kwargs["port"] = int(port)

    if "use_ssl" in parameters:
        kwargs["use_ssl"] = direct_tls
    if direct_tls and "force_starttls" in parameters:
        kwargs["force_starttls"] = False

    return kwargs


async def connect_xmpp(xmpp):
    """Connect using optional host, port and direct-TLS config."""
    kwargs = _connect_kwargs(xmpp)
    host = (
        kwargs.get("host")
        or (kwargs.get("address") or (None, None))[0]
        or _configured_jid_domain()
        or "auto"
    )
    port = (
        kwargs.get("port")
        or (kwargs.get("address") or (None, None))[1]
        or "auto"
    )
    mode = "direct TLS" if config.get("direct_tls", False) else "STARTTLS"

    log.info("[XMPP] Connecting to %s:%s (%s)", host, port, mode)

    result = xmpp.connect(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


# -------------------------------------------------
# BOT CLASS
# -------------------------------------------------

class Bot(slixmpp.ClientXMPP):

    def __init__(self):
        # run __init__() from ClientXMPP
        super().__init__(_build_client_jid(config["jid"],
                                           _get_configured_resource()),
                         config["password"])

        self.nick = config.get("nick", "bot")
        self.admins = []
        self.prefix = config.get("prefix", ",")
        self.version = __version__
        self.last_version_check_result = None
        self.last_update_notified_version = None
        self.connection_start_time = None
        self.tasks = TaskSupervisor()
        self.command_executor = CommandExecutor(self)
        self._startup_backup_done = False

        # Rate limiter (in-memory, per process)
        # The limits are intentionally in-memory and reset on process restart.
        self.rate_limiter = TokenBucketRateLimiter(
            capacity=int(config.get("command_rate_limit_capacity", 4)),
            refill_amount=int(
                config.get("command_rate_limit_refill_amount", 1)
            ),
            refill_interval=float(
                config.get("command_rate_limit_refill_interval_seconds", 0.5)
            ),
            deny_window=float(
                config.get("command_rate_limit_deny_window_seconds", 10.0)
            ),
            deny_threshold=int(
                config.get("command_rate_limit_deny_threshold", 6)
            ),
            base_block_seconds=float(
                config.get("command_rate_limit_base_block_seconds", 30.0)
            ),
            backoff_multiplier=float(
                config.get("command_rate_limit_backoff_multiplier", 2.0)
            ),
            max_block_seconds=float(
                config.get("command_rate_limit_max_block_seconds", 3600.0)
            ),
            notify_cooldown=float(
                config.get("command_rate_limit_notify_cooldown_seconds", 10.0)
            ),
        )

        # Presence Manager
        self.presence = PresenceManager(self)

        self.register_plugin("xep_0012")
        self.register_plugin("xep_0030")
        self.register_plugin("xep_0045")
        self.register_plugin("xep_0054")
        self.register_plugin("xep_0084")
        self.register_plugin("xep_0092")
        self.register_plugin("xep_0153")
        self.register_plugin("xep_0163")
        self.register_plugin("xep_0199")
        self.register_plugin("xep_0249")
        self.register_plugin("xep_0359")
        self.register_plugin("xep_0461")
        self.register_plugin("xep_0511")

        # Database Manager
        self.db = DatabaseManager(config.get("db", "bot.db"))

        # Plugin Manager
        self.bot_plugins = PluginManager(self)

        self.add_event_handler("session_start", self.on_start)
        self.add_event_handler("groupchat_message", self.on_muc_message)
        self.add_event_handler("message", self.on_private_message)

    # -------------------------------------------------
    # EVENT HANDLERS
    # -------------------------------------------------

    async def _send_restart_notification(self):
        """Send restart completion notification if one was queued."""
        import json
        import os

        restart_file = str(config.get("restart_notification_file", "/tmp/envsbot_restart_notification.json") or "/tmp/envsbot_restart_notification.json")

        if not os.path.exists(restart_file):
            return

        try:
            with open(restart_file, 'r') as f:
                notif = json.load(f)
            os.remove(restart_file)

            log.info("[ADMIN] Processing restart notification: %s", notif)

            if notif.get("is_room") and notif.get("room"):
                # Send to the room
                message = self.make_message(
                    mto=notif["room"],
                    mbody=f"{notif['nick']}: ✅ Bot restart complete!",
                    mtype="groupchat"
                )
                await self._safe_send_message(message)
                log.info(
                    "[ADMIN] Bot restart notification sent to room %s",
                    notif["room"])
            else:
                # Send private message
                message = self.make_message(
                    mto=notif["sender"],
                    mbody="✅ Bot restart complete!",
                    mtype="chat"
                )
                await self._safe_send_message(message)
                log.info(
                    "[ADMIN] Bot restart notification sent to %s",
                    notif["sender"])
        except FileNotFoundError:
            log.debug("[ADMIN] No restart notification file found")
        except Exception as e:
            log.error("[ADMIN] Failed to process restart notification: %s", e)


    async def _create_startup_backup(self):
        """Create one optional managed backup during this bot process start."""
        if self._startup_backup_done:
            return
        self._startup_backup_done = True

        if not config.get("backup_on_start", True):
            log.info("[BACKUP] Startup backup disabled by config")
            return

        try:
            from utils.audit import audit_event
            from utils.backups import create_backup

            archive = await create_backup(self, reason="startup")
            log.info("[BACKUP] Startup backup created: %s", archive.name)
            await audit_event(
                self,
                "backup_created",
                actor="system",
                target=archive.name,
                details={"reason": "startup", "automatic": True},
            )
        except Exception:
            # Backups are important, but a failed backup must not prevent the bot
            # from joining rooms after a service restart. Operators still get a
            # clear log entry at ERROR level.
            log.exception("[BACKUP] Startup backup failed")

    async def _safe_send_message(self, message):
        """
        Safely send a message with proper error handling.

        Handles both sync and async send() methods.
        Logs any errors that occur.

        Args:
            message: slixmpp Message object to send
        """
        try:
            result = message.send()
            # Check if send() is a coroutine (async)
            if inspect.iscoroutine(result):
                await result
            # log.info("[BOT] Message sent to %s: %s", message['to'],
            # message['body'])
        except Exception as e:
            log.exception("[BOT] Failed to send message: %s", e)

    # fired on "session_start"
    async def on_start(self, event):
        self.connection_start_time = datetime.now()
        # Advertise support for receiving MUC private messages. Some clients
        # check entity capabilities before opening a MUC-PM to a bot occupant.
        try:
            self["xep_0030"].add_feature("http://jabber.org/protocol/muc#user")
        except Exception:
            log.debug("[BOT] Could not advertise MUC-PM feature", exc_info=True)

        # send startup presence
        self.presence.broadcast()
        # Get roster
        await self.get_roster()
        # Connect to DB
        await self.db.connect()
        # load plugins
        await self.bot_plugins.load_all()

        # === CALL on_ready() HOOKS (after DB is ready) ===
        await self.bot_plugins.call_on_ready()

        # Create an optional startup backup after DB/plugins are ready.
        await self._create_startup_backup()

        # Check for restart notification (after everything is initialized)
        await self._send_restart_notification()

        # send presence again
        self.presence.broadcast()
        # set automatic mutual subscriptions
        self.roster.auto_subscribe = True

        log.info("[BOT] ✅ Bot started, all rooms joined")

    # fired when a MUC room message arrives
    async def on_muc_message(self, msg):
        try:
            room = msg['from'].bare
            nick = msg.get('mucnick')  # Use .get() for safety

            # ignore messages from ourselves (our nick)
            bot_nick = self.presence.joined_rooms.get(room)
            if bot_nick == nick:
                return

            # proceed to command handling
            if msg["type"] == "groupchat":
                await self.handle_command(
                    msg["body"],
                    msg["from"],
                    nick,
                    msg,
                    True
                )
        except Exception as e:
            log.exception("[BOT] Error in on_muc_message: %s", e)

    # fired when a direct message to the bot or a MUC DM arrives
    async def on_private_message(self, msg):
        try:
            if msg["type"] in ("chat", "normal"):
                await self.handle_command(
                    msg["body"],
                    msg["from"],
                    None,
                    msg,
                    False
                )
        except Exception as e:
            log.exception("[BOT] Error in on_private_message: %s", e)

    # -------------------------------------------------
    # HELPER FUNCTIONS
    # -------------------------------------------------

    def _parse_bare_jid(self, jid_value, *, label, fallback_to_none=False):
        """
        Parse a JID and return its bare form as a string.

        If parsing fails, logs a warning and returns None unless
        fallback_to_none is False, in which case it returns the original
        value as a string.
        """
        try:
            return slixmpp.JID(jid_value).bare
        except Exception as e:
            log.warning("[BOT] Failed to parse %s JID '%s': %s",
                        label, jid_value, e)
            if fallback_to_none:
                return None
            return None

    async def _get_owner_bare_jid(self):
        """
        Resolve the configured owner JID to its bare form.
        """
        try:
            return slixmpp.JID(config["owner"]).bare
        except Exception as e:
            log.warning("[BOT] Failed to parse owner JID: %s", e)
            return None

    async def _get_room_role_from_presence(self, jid, room, db_role):
        """
        Elevate role to MODERATOR when the user is an admin/owner in the room.
        """
        from core_plugins.rooms import JOINED_ROOMS

        if not room:
            return db_role

        room_info = JOINED_ROOMS.get(room)
        if not room_info:
            return db_role

        nicks = room_info.get("nicks", {})
        for nick_info in tuple(nicks.values()):
            try:
                if str(nick_info.get("jid")) == str(jid):
                    affiliation = nick_info.get("affiliation", "")
                    if (affiliation in ("admin", "owner")
                            and db_role > Role.MODERATOR):
                        return Role.MODERATOR
            except Exception as e:
                log.debug("[BOT] Error checking room affiliation: %s", e)

        return db_role

    async def get_user_role(self, jid, room=None) -> Role:
        """
        Resolve a user's role using config and database.
        """
        jid = self._parse_bare_jid(jid, label="user")
        if jid is None:
            return Role.NONE

        owner_jid = await self._get_owner_bare_jid()

        # owner override
        if owner_jid and jid == owner_jid:
            return Role.OWNER

        row = await self.db.users.get(jid)

        if row is None:
            return Role.NONE

        try:
            db_role = role_from_int(int(row['role']))
        except (KeyError, TypeError, ValueError):
            return Role.NONE

        if db_role == Role.OWNER:
            log.warning(
                "[BOT] Ignoring stored owner role for non-config user: %s",
                jid,
            )
            db_role = Role.USER
        elif db_role == Role.NONE:
            db_role = Role.USER

        return await self._get_room_role_from_presence(jid, room, db_role)

    def _format_reply_body(self, msg, text, mention):
        """
        Build the outbound reply body without changing reply semantics.
        """
        if msg.get("type", "chat") == "groupchat" and mention:
            nick = msg.get("mucnick") or msg["from"].resource
            return f"{nick}: {text}"
        return text

    # ------------------------------
    # bot.reply() method and helpers
    # ------------------------------

    def _build_reply_message(self, msg, text, mention, thread, ephemeral,
                             no_store=None):
        """
        Create the outbound message object for reply().
        """
        msg_type = msg.get("type", "chat")
        body = text

        if isinstance(body, list):
            body = "\n".join(body)

        body = self._format_reply_body(msg, body, mention)

        if msg_type == "groupchat":
            message = self.make_message(
                mto=msg["from"].bare,
                mbody=body,
                mtype="groupchat"
            )
        else:
            message = self.make_message(
                mto=msg["from"],
                mbody=body,
                mtype="chat"
            )

        if thread:
            thread_id = msg.get("thread") or msg.get("id")
            if thread_id:
                try:
                    message["thread"] = thread_id
                except Exception:
                    if msg_type == "groupchat":
                        log.debug("[BOT] Setting thread failed!")

        if no_store is None:
            no_store = ephemeral or msg_type != "groupchat"

        if no_store:
            message.append(ET.Element("{urn:xmpp:hints}no-store"))

        return message, body

    def _record_test_reply(self, msg, text):
        """
        Preserve test-side reply capture behavior.
        """
        if hasattr(msg, "replies"):
            msg.replies.append(text)

    def reply_ok(self, msg, text, **kwargs):
        """Send a success reply with a consistent prefix."""
        self.reply(msg, f"✅ {text}", **kwargs)

    def reply_info(self, msg, text, **kwargs):
        """Send an informational reply with a consistent prefix."""
        self.reply(msg, f"ℹ️ {text}", **kwargs)

    def reply_warn(self, msg, text, **kwargs):
        """Send a warning reply with a consistent prefix."""
        self.reply(msg, f"🟡️ {text}", **kwargs)

    def reply_error(self, msg, text, **kwargs):
        """Send an error reply with a consistent prefix."""
        self.reply(msg, f"🔴 {text}", **kwargs)

    def reply_usage(self, msg, usage, **kwargs):
        """Send a command usage reply."""
        self.reply_warn(msg, f"Usage: {usage}", **kwargs)

    async def audit(self, event, *, actor=None, target=None, details=None):
        """Write an audit event if the audit log is available."""
        try:
            audit_log = getattr(getattr(self, "db", None), "audit", None)
            if audit_log is None:
                return
            await audit_log.append(
                event,
                actor=str(actor) if actor is not None else None,
                target=str(target) if target is not None else None,
                details=details or {},
            )
        except Exception:
            log.debug("[AUDIT] Failed to write audit event", exc_info=True)

    def reply(self, msg, text, mention=True, thread=True, rate_limit=True,
              ephemeral=False, no_store=None):
        """
        Smart reply helper for plugins.

        Features:
        - Mentions the sender in group chats
        - Supports message threading
        - Formats multi-line responses
        - Basic per-user rate limiting
        - Safe message sending

        Args:
            msg: Original message object
            text: Reply text or list of lines
            mention: Mention sender in group chats
            thread: Thread reply if possible
            rate_limit: Apply anti-spam limit
            ephemeral: Mark as ephemeral (no-store)
            no_store: Override XEP-0334 no-store hint handling. ``None`` keeps
                the legacy default: private replies are no-store, groupchat
                replies are stored unless ephemeral=True. ``False`` sends a
                normal persistent reply, useful for explicit admin status
                outputs in PM/DM.
        """
        try:
            message, body = self._build_reply_message(
                msg, text, mention, thread, ephemeral, no_store
            )

            # send reply safely
            asyncio.create_task(self._reply_send_wrapper(message))

            # support test MockMessage
            self._record_test_reply(msg, text if not isinstance(text, list)
                                    else "\n".join(text))

        except Exception as e:
            msg_type = msg.get("type", "chat")
            if msg_type == "groupchat":
                log.exception("[BOT] Error creating groupchat reply: %s", e)
            else:
                log.exception("[BOT] Error creating private reply: %s", e)

    async def _reply_send_wrapper(self, message):
        """
        Wrapper to send messages asynchronously with error handling.
        """
        try:
            await self._safe_send_message(message)
        except Exception as e:
            log.exception("[BOT] Error in reply send wrapper: %s", e)

    # -------------------------------------------------
    # UNIFIED COMMAND HANDLER
    # -------------------------------------------------

    def _joined_room_jids(self) -> set[str]:
        """Return known joined room bare JIDs from runtime room state."""
        rooms = set()
        try:
            rooms.update(str(room) for room in getattr(self.presence,
                                                       "joined_rooms", {}))
        except Exception:
            log.debug("[MUC] Could not inspect presence joined rooms",
                      exc_info=True)
        try:
            from core_plugins.rooms import JOINED_ROOMS

            rooms.update(str(room) for room in JOINED_ROOMS)
        except Exception:
            log.debug("[MUC] Could not inspect plugin joined rooms",
                      exc_info=True)
        return rooms

    def _is_muc_private_message(self, msg) -> bool:
        """Return True for a private message sent via a MUC occupant JID."""
        try:
            msg_type = msg.get("type", "chat")
            from_jid = msg["from"]
            room = str(from_jid.bare)
            nick = getattr(from_jid, "resource", None)
        except Exception:
            return False

        return (
            msg_type in ("chat", "normal")
            and bool(nick)
            and room in self._joined_room_jids()
        )

    def _get_message_room_and_nick(self, msg):
        """
        Resolve room and nick from a message if possible.
        """
        room = None
        nick = None
        try:
            from_jid = msg['from']
            room = from_jid.bare
            nick = msg.get("mucnick") or msg["from"].resource
        except Exception as exc:
            log.debug("[MUC] Could not resolve message room/nick: %s", exc)
        return room, nick

    def _lookup_muc_occupant_jid(self, room, nick):
        """Resolve a MUC occupant's real JID from live MUC state."""
        muc = self.plugin.get("xep_0045", None)

        if muc:
            try:
                jid = muc.get_jid_property(room, nick, "jid")
                if jid:
                    return jid
            except Exception:
                log.debug("[BOT] Error getting JID from XEP-0045 state",
                          exc_info=True)

        try:
            from core_plugins.rooms import JOINED_ROOMS

            room_data = JOINED_ROOMS.get(room, {}) or {}
            nick_data = (room_data.get("nicks", {}) or {}).get(nick, {}) or {}
            jid = nick_data.get("jid")
            if jid:
                return jid
        except Exception:
            log.debug("[BOT] Error getting JID from joined room state",
                      exc_info=True)

        return None

    def _bare_jid_value(self, jid_value):
        """Return a best-effort bare JID string without leaking resources."""
        bare = getattr(jid_value, "bare", None)
        if bare:
            return str(bare)
        return str(jid_value).split("/", 1)[0]

    def _resolve_sender_jid(self, msg, sender_jid, nick):
        """
        Resolve the real sender JID for room messages, with fallback.
        """
        jid = None
        room = None
        msg_type = msg.get("type", "chat")

        if (msg_type in ("chat", "normal")
                and not self._is_muc_private_message(msg)):
            return self._bare_jid_value(sender_jid), None

        try:
            room, nick = self._get_message_room_and_nick(msg)
            jid = self._lookup_muc_occupant_jid(room, nick)
        except Exception:
            log.debug("[BOT] Error getting JID from MUC context", exc_info=True)

        if jid is None:
            return self._bare_jid_value(sender_jid), room

        try:
            import slixmpp
            return str(slixmpp.JID(jid).bare), room
        except Exception as e:
            log.warning("[BOT] Failed to parse resolved JID: %s", e)
            return str(sender_jid), room

    def _can_execute_command_in_room(self, cmd_obj, is_room, room=None):
        """
        Enforce the MUC direct-message restriction for privileged commands.
        """
        if not is_room:
            return True

        required_role = getattr(cmd_obj, "role", Role.NONE)
        if required_role > Role.MODERATOR:
            return True

        try:
            from core_plugins.rooms import room_invite_admin_rooms

            if (getattr(cmd_obj, "name", "") == "rooms invite"
                    and str(room or "").lower() in room_invite_admin_rooms()):
                return True
        except Exception:
            log.debug("[BOT] Could not inspect room invite admin rooms", exc_info=True)

        return False

    def _command_error_message(self, user_role, cmd_name, error):
        """
        Preserve the existing public/internal error wording.
        """
        if user_role in (Role.OWNER, Role.ADMIN):
            return f"🔴 Command error: {error}"
        return f"🔴 Command '{cmd_name}' failed due to internal error."

    async def handle_command(self, body, sender_jid, nick, msg, is_room):
        """
        Parse and execute a bot command from a message.

        This method is called by both private-message and groupchat
        handlers.  It checks whether the message begins with the
        configured command prefix, resolves the command using the
        command resolver, verifies user permissions, and executes
        the command handler.

        Workflow
        --------
        1. Validate that the message body exists and begins with the command
           prefix.
        2. Strip the prefix and process rate limiting
        3. Resolve the command using `resolve_command()`.
        4. Determine the sender's role (owner, admin, moderator, user, none).
        5. Verify that the user has permission to execute the command.
        6. Execute the command handler (async or sync).
        7. Catch and report execution errors.

        Parameters
        ----------
        body : str
            Raw message body received from the XMPP message.
        sender_jid : str
            JID of the message sender.
        nick : str
            Nickname of the sender in a groupchat. May be None for private
            messages.
        msg : slixmpp.Message
            Original Slixmpp message object used for replies and metadata.
        is_room : bool
            True if the message was received in a MUC (groupchat), False if it
            was a private chat message.

        Notes
        -----
        - Commands are detected using the bot's configured prefix (e.g. ",").
        - Command resolution supports:
            * multi-word commands
            * command aliases
            * longest-match detection
        - Permission checks are based on the role hierarchy:
                    OWNER = 1
                    SUPERADMIN = 10
                    ADMIN = 20
                    MODERATOR = 40
                    TRUSTED = 60
                    USER = 80
                    NEW = 90
                    NONE = 95
                    BANNED = 100

          Lower numbers have higher privileges.

        - Errors are logged and a user-friendly message is returned to the
          sender.
        """
        if not body:
            return
        if not body.startswith(self.prefix):
            return

        text = body[len(self.prefix):].strip()
        if not text:
            return

        jid, room = self._resolve_sender_jid(msg, sender_jid, nick)
        cmd_obj, args = resolve_command(text)
        if not cmd_obj:
            return

        cmd_name = cmd_obj.name
        user_role = await self.get_user_role(jid, room)

        # Apply configurable command rate limiting after command and role
        # resolution so privileged operators can be exempted safely.
        if (config.get("command_rate_limit_enabled", True)
                and not _role_bypasses_rate_limit(user_role)):
            allowed, retry_after = await self.rate_limiter.allow(jid)
            if not allowed:
                if self.rate_limiter.notify_allowed(jid):
                    log.info(("[BOT] 🟡️ Rate-limited %s "
                              "in room %s (retry_after=%.1fs)"),
                             jid, room, retry_after)
                return

        if not check_permission(user_role, cmd_obj):
            self.reply(msg, "🔴 You are not allowed to use this command.")
            return

        if not self._can_execute_command_in_room(cmd_obj, is_room, room):
            self.reply(msg, "🔴 Use this command in MUC Direct Message only.")
            return

        context = CommandExecutionContext(
            command_name=cmd_name,
            sender_jid=jid,
            nick=nick,
            room=room,
            is_room=is_room,
            role=user_role,
            args=tuple(args),
        )
        await self.command_executor.execute(cmd_obj, context, msg)


# --------------------------------------------------
# GET LATEST GIT TAG (for version display)
# --------------------------------------------------
def get_latest_git_tag():
    try:
        tag = subprocess.check_output(
            ['git', 'describe', '--tags', '--abbrev=0'],
            stderr=subprocess.STDOUT
        ).strip().decode('utf-8')
        return tag
    except subprocess.CalledProcessError:
        return None  # No tags found or not a git repo


# -------------------------------------------------
# MAIN FUNCTION
# -------------------------------------------------

async def main():
    try:
        validate_startup_config(config)
    except ConfigError as e:
        exit_on_config_error(e)

    xmpp = Bot()

    # startup bot
    await connect_xmpp(xmpp)

    log.info("[XMPP] ✅ Connected successfully. Starting event loop...")

    try:
        await xmpp.disconnected
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Gracefully shut down on CTRL-c
        log.info("[XMPP] Shutdown request")

        xmpp.disconnect()

        try:
            await asyncio.wait_for(xmpp.disconnected, timeout=2.0)
        except asyncio.TimeoutError:
            log.warning("[XMPP] Disconnect timeout")

    finally:
        log.info("[XMPP] disconnected. Closing Database...")
        try:
            await xmpp.db.close()
        except Exception as e:
            log.exception(f"[XMPP] Error closing database: {e}")
        log.info("[XMPP] ✅ Database closed! End!")



def copy_initial_chat_slang(source="init_chat_slang.csv", target="chat_slang.csv") -> None:
    """Copy the default chat slang file into place on first startup."""
    if os.path.exists(source) and not os.path.exists(target):
        try:
            shutil.copyfile(source, target)
            log.info("[INIT] ✅ Copied %s to %s", source, target)
        except Exception as e:
            log.error("[INIT] 🔴 Failed to copy %s to %s: %s", source, target, e)
    elif not os.path.exists(source):
        log.warning("[INIT] 🔴 Source file %s not found. Skipping copy.", source)
    else:
        log.info("[INIT] ✅ Target file %s already exists. Skipping copy.", target)


def cli() -> None:
    """Console-script entrypoint for running envsbot."""
    copy_initial_chat_slang()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("[INIT] Shutdown requested by keyboard interrupt")


if __name__ == "__main__":
    cli()
