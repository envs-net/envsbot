import slixmpp
import asyncio
import inspect
import logging
import time

from slixmpp.xmlstream import ET

from utils.plugin_manager import PluginManager
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


class PresenceManager:

    def __init__(self, bot):

        self.bot = bot

        self.status = {
            "show": "online",
            "status": "I'm ready to serve you!"
        }

        self.joined_rooms = {}

        self.emojis = {
            "online": "✅",
            "chat": "💬",
            "away": "👋 ",
            "xa": "💤",
            "dnd": "⛔"
        }

    def update(self, show, status):

        self.status["show"] = show
        self.status["status"] = status

        self.broadcast()

    def broadcast(self):

        show = self.status["show"]
        status = self.status["status"]

        self.bot.send_presence(pshow=show, pstatus=status)

        # --- Get JOINED_ROOMS from "rooms" plugin ---
        rooms_plugin = self.bot.plugins.plugins.get("rooms", None)
        if rooms_plugin is not None:
            rooms = dict(rooms_plugin.JOINED_ROOMS)
            for room in rooms.keys():
                self.bot.send_presence(
                    pto=f"{room}/{rooms[room]['nick']}",
                    pshow=show,
                    pstatus=status)
        # log message
        log.info(f"[PRESENCE] {self.emoji(show)} Status set: "
                 f"'{show}': [{status}]")

    def emoji(self, show=None):

        show = show or self.status["show"]
        return self.emojis.get(show, "")


class Bot(slixmpp.ClientXMPP):

    def __init__(self):
        # run __init__() from ClientXMPP
        super().__init__(config["jid"],
                         config["password"])

        self.nick = config.get("nick", "bot")
        self.admins = []
        self.prefix = config.get("prefix", ",")

        # Presence Manager
        self.presence = PresenceManager(self)

        self.register_plugin("xep_0030")
        self.register_plugin("xep_0045")
        self.register_plugin("xep_0084")
        self.register_plugin("xep_0163")
        self.register_plugin("xep_0054")

        # Database Manager
        self.db = DatabaseManager(config.get("db", "bot.db"))

        # Plugin Manager
        self.plugins = PluginManager(self)

        self.add_event_handler("session_start", self.on_start)
        self.add_event_handler("groupchat_message", self.on_muc_message)
        self.add_event_handler("message", self.on_private_message)
        self.add_event_handler("muc::%s::got_offline" % "*", self.on_muc_leave)

    async def get_user_role(self, jid) -> Role:
        """
        Resolve a user's role using config and database.
        """

        jid = slixmpp.JID(jid).bare

        owner_jid = slixmpp.JID(config["owner"]).bare

        # owner override
        if jid == owner_jid:
            return Role.OWNER

        row = await self.db.users.get(jid)

        if row is None:
            return Role.NONE

        try:
            return role_from_int(row['role'])
        except KeyError:
            return Role.NONE

    async def autojoin_rooms(self):
        """
        Join all rooms marked with autojoin in the database.
        """

        rows = await self.db.rooms.list()
        for room_jid, nick, autojoin, status in rows:
            if not autojoin:
                continue
            log.info("[MUC] Autojoining room %s as %s", room_jid, nick)
            self.plugin["xep_0045"].join_muc(
                room_jid,
                nick,
                pshow=self.presence.status["show"],
                pstatus=self.presence.status["status"])
            self.presence.joined_rooms[room_jid] = nick

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

        sender = str(msg["from"].bare)

        # basic rate limit storage
        if not hasattr(self, "_reply_rate"):
            self._reply_rate = {}

        # Rate limiting (2 replies per second per user)
        if rate_limit:
            now = time.time()
            last = self._reply_rate.get(sender, 0)

            if now - last < 0.5:
                return

            self._reply_rate[sender] = now

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
                        log.debug("[BOT] ❌Setting Thread failed: {e}")

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

    async def on_start(self, event):
        # send startup presence
        self.presence.broadcast()
        # Get roster
        await self.get_roster()
        # Connect to DB
        await self.db.connect()
        # load plugins
        await self.plugins.load_all()
        # send presence again
        self.presence.broadcast()
        # set automatic mutual subscriptions
        self.roster.auto_subscribe = True

        log.info("[BOT] ✅ Bot started, all rooms joined")

    def on_muc_leave(self, presence):
        """
        Handle occupants leaving a MUC.

        If the bot itself leaves a room, remove the room from the
        presence manager's joined_rooms mapping.
        """

        room = presence["from"].bare
        nick = presence["muc"]["nick"]

        # ignore if we never registered this room
        if room not in self.presence.joined_rooms:
            return

        # if the leaving nick is our own nick, we left the room
        if self.presence.joined_rooms.get(room) == nick:
            self.presence.joined_rooms.pop(room, None)
            log.info("[MUC] 🚪 Left room %s (%s)", room, nick)

    async def on_muc_message(self, msg):

        room = msg['from'].bare
        nick = msg['mucnick']
        if self.presence.joined_rooms.get(room) == nick:
            return

        if msg["type"] == "groupchat":
            await self.handle_command(
                msg["body"],
                msg["from"],
                msg["mucnick"],
                msg,
                True
            )

    async def on_private_message(self, msg):

        if msg["type"] in ("chat", "normal"):
            await self.handle_command(
                msg["body"],
                msg["from"],
                None,
                msg,
                False
            )

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
        2. Strip the prefix and resolve the command using `resolve_command()`.
        3. Determine the sender's role (owner, admin, moderator, user, none).
        4. Verify that the user has permission to execute the command.
        5. Execute the command handler (async or sync).
        6. Catch and report execution errors.

        Parameters
        ----------
        body : str
            Raw message body received from the XMPP message.
        sender_jid : str
            Bare JID of the message sender.
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
                OWNER (1)
                ADMIN (2)
                MODERATOR (3)
                USER (4)
                NONE (5)
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

        # --- resolve command using command resolver ---
        cmd_obj, args = resolve_command(text)

        if not cmd_obj:
            return

        cmd_name = cmd_obj.name

        jid = None
        muc = self.plugin.get("xep_0045", None)
        if muc:
            room = msg['from'].bare
            nick = msg.get("mucnick") or msg["from"].resource
            jid = muc.get_jid_property(room, nick, "jid")
        if jid is None:
            jid = sender_jid
        jid = str(slixmpp.JID(jid))

        # determine sender role
        user_role = await self.get_user_role(jid)

        # permission check
        if not check_permission(user_role, cmd_obj):
            self.reply(msg, "❌You are not allowed to use this command.")
            return

        # Commands which require permissions of at least "moderator"
        # shouldn't be used in GroupChat
        if user_role <= Role.MODERATOR and is_room:
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
        log.info("[XMPP] Database closed! End!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
