import slixmpp
import asyncio
import inspect
import logging

from slixmpp.xmlstream import ET

from utils.presence_manager import PresenceManager
from utils.plugin_manager import PluginManager
from utils.rate_limiter import TokenBucketRateLimiter
from utils.config import config, setup_logging
from utils.command import (
    resolve_command,
    check_permission,
    Role,
    role_from_int
)
from database.manager import DatabaseManager

# === set up logging ===
setup_logging()
log = logging.getLogger(__name__)


# -------------------------------------------------
# BOT CLASS
# -------------------------------------------------

class Bot(slixmpp.ClientXMPP):

    def __init__(self):
        # run __init__() from ClientXMPP
        super().__init__(config["jid"],
                         config["password"])

        self.nick = config.get("nick", "bot")
        self.admins = []
        self.prefix = config.get("prefix", ",")

        # Rate limiter (in-memory, per process)
        # capacity=4, refill 1 token every 0.5s
        self.rate_limiter = TokenBucketRateLimiter(
            capacity=4,
            refill_amount=1,
            refill_interval=0.5,
            deny_window=10.0,
            deny_threshold=6,
            base_block_seconds=30.0,
            backoff_multiplier=2.0,
            max_block_seconds=3600.0,
            notify_cooldown=10.0,
        )

        # Presence Manager
        self.presence = PresenceManager(self)

        self.register_plugin("xep_0030")
        self.register_plugin("xep_0045")
        self.register_plugin("xep_0084")
        self.register_plugin("xep_0163")
        self.register_plugin("xep_0054")
        self.register_plugin("xep_0199")

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

    # fired on "session_start"
    async def on_start(self, event):
        # send startup presence
        self.presence.broadcast()
        # Get roster
        await self.get_roster()
        # Connect to DB
        await self.db.connect()
        # load plugins
        await self.bot_plugins.load_all()
        # send presence again
        self.presence.broadcast()
        # set automatic mutual subscriptions
        self.roster.auto_subscribe = True

        log.info("[BOT] ✅ Bot started, all rooms joined")

    # fired when a MUC room message arrives
    async def on_muc_message(self, msg):
        room = msg['from'].bare
        nick = msg['mucnick']
        # ignore messages from ourselves (our nick)
        if self.presence.joined_rooms.get(room) == nick:
            return

        # proceed to command handling
        if msg["type"] == "groupchat":
            await self.handle_command(
                msg["body"],
                msg["from"],
                msg["mucnick"],
                msg,
                True
            )

    # fired when a direct message to the bot or a MUC DM arrives
    async def on_private_message(self, msg):

        if msg["type"] in ("chat", "normal"):
            await self.handle_command(
                msg["body"],
                msg["from"],
                None,
                msg,
                False
            )

    # -------------------------------------------------
    # HELPER FUNCTIONS
    # -------------------------------------------------

    async def get_user_role(self, jid, room=None) -> Role:
        """
        Resolve a user's role using config and database.
        """
        import slixmpp
        from plugins.rooms import JOINED_ROOMS
        jid = slixmpp.JID(jid).bare

        owner_jid = slixmpp.JID(config["owner"]).bare

        # owner override
        if jid == owner_jid:
            return Role.OWNER

        row = await self.db.users.get(jid)

        if row is None:
            return Role.NONE

        try:
            db_role = role_from_int(row['role'])
        except KeyError:
            return Role.NONE

        # Elevate to MODERATOR if user is admin/owner in any joined room
        if room and room in JOINED_ROOMS:
            nicks = JOINED_ROOMS[room].get("nicks", {})
            for nick_info in nicks.values():
                if str(nick_info.get("jid")) == str(jid):
                    affiliation = nick_info.get("affiliation", "")
                    if (affiliation in ("admin", "owner")
                            and db_role > Role.MODERATOR):
                        return Role.MODERATOR
        return db_role

    def reply(self, msg, text, mention=True, thread=True, rate_limit=True):
        """
        Smart reply helper for plugins.

        Features:
        - Mentions the sender in group chats
        - Supports message threading
        - Formats multi-line responses
        - Basic per-user rate limiting

        Args:
            msg: Original message object
            text (str|list): Reply text or list of lines
            mention (bool): Mention sender in group chats
            thread (bool): Thread reply if possible
            rate_limit (bool): Apply anti-spam limit
        """

        # Convert list responses into multi-line text
        if isinstance(text, list):
            text = "\n".join(text)

        msg_type = msg.get("type", "chat")

        if msg_type == "groupchat":

            body = text

            if mention:
                nick = msg.get("mucnick") or msg["from"].resource
                body = f"{nick}: {text}"

            message = self.make_message(
                mto=msg["from"].bare,
                mbody=body,
                mtype="groupchat"
            )

            if thread:
                thread_id = msg.get("thread") or msg.get("id")
                if thread_id:
                    try:
                        message["thread"] = thread_id
                    except Exception:
                        log.exception("[BOT] ❌Setting Thread failed!")

            # Make reply ephemeral
            message.append(ET.Element("{urn:xmpp:hints}no-store"))
            # send reply
            message.send()

            # support test MockMessage
            if hasattr(msg, "replies"):
                msg.replies.append(text)

        else:

            message = self.make_message(
                mto=msg["from"],
                mbody=text,
                mtype="chat"
            )

            if thread:
                thread_id = msg.get("thread") or msg.get("id")
                if thread_id:
                    try:
                        message["thread"] = thread_id
                    except Exception:
                        pass

            # Make reply ephemeral
            message.append(ET.Element("{urn:xmpp:hints}no-store"))
            # Send message
            message.send()

            # support test MockMessage
            if hasattr(msg, "replies"):
                msg.replies.append(text)

    # -------------------------------------------------
    # UNIFIED COMMAND HANDLER
    # -------------------------------------------------

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

        # Checking for real JID
        jid = None
        room = None
        muc = self.plugin.get("xep_0045", None)
        if muc:
            room = msg['from'].bare
            nick = msg.get("mucnick") or msg["from"].resource
            jid = muc.get_jid_property(room, nick, "jid")
        if jid is None:
            jid = sender_jid
        else:
            jid = str(slixmpp.JID(jid).bare)

        # Apply rate limiting on ingress
        allowed, retry_after = await self.rate_limiter.allow(jid)
        if not allowed:
            # Avoid notifying the whole room; log and occasional
            # admin notification only
            if self.rate_limiter.notify_allowed(jid):
                log.info(("[BOT] ⚠️Rate-limited %s "
                          "in room %s (retry_after=%.1fs)"),
                         jid, room, retry_after)
            return

        # --- resolve command using command resolver ---
        cmd_obj, args = resolve_command(text)

        if not cmd_obj:
            return

        cmd_name = cmd_obj.name

        # determine sender role
        user_role = await self.get_user_role(jid, room)

        # permission check
        if not check_permission(user_role, cmd_obj):
            self.reply(msg, "❌You are not allowed to use this command.")
            return

        # Commands which require permissions of at least "moderator"
        # shouldn't be used in GroupChat
        required_role = getattr(cmd_obj, "role", Role.NONE)
        if required_role <= Role.MODERATOR and is_room:
            self.reply(msg, "❌Use this command in MUC Direct Message only.")
            return

        try:
            handler = getattr(cmd_obj, "handler", None)
            if not handler:
                log.error(f"[BOT]❌Command '{cmd_name}' has no handler")
                return
            result = handler(self, sender_jid, nick, args, msg, is_room)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            log.exception(f"[BOT]❌ Error while executing command '{cmd_name}'")
            if user_role in (Role.OWNER, Role.ADMIN):
                err_msg = f"❌Command error: {e}"
            else:
                err_msg = (f"❌Command '{cmd_name}' "
                           f"failed due to internal error.")

            self.reply(msg, err_msg)


# -------------------------------------------------
# MAIN FUNCTION
# -------------------------------------------------

async def main():
    xmpp = Bot()

    # startup bot
    await xmpp.connect()

    log.info("[XMPP] ✅ Connected successfully. Starting event loop...")

    try:
        await xmpp.disconnected
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Gracefully shut down on CTRL-c
        log.info("[XMPP] Shutdown request")

        xmpp.disconnect()
        await xmpp.disconnected
    finally:
        log.info("[XMPP] disconnected. Closing Database...")
        await asyncio.shield(xmpp.db.close())
        log.info("[XMPP] ✅ Database closed! End!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
