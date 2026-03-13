import slixmpp
import asyncio
import json
import inspect
import os
import sys
import logging
import time

from plugin_manager import PluginManager
from logging_setup import setup_logging
from database import DatabaseManager
from command import resolve_command, check_permission, Role

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

        for room, nick in self.joined_rooms.items():
            self.bot.send_presence(
                pto=f"{room}/{nick}", pshow=show, pstatus=status)
        # log message
        log.info(f"{self.emoji(show)} Status set: '{show}': [{status}]")

    def emoji(self, show=None):

        show = show or self.status["show"]
        return self.emojis.get(show, "")


class Bot(slixmpp.ClientXMPP):

    def __init__(self, config_file):
        # load config file (json)
        with open(config_file) as f:
            self.config = json.load(f)
        # run __init__() from ClientXMPP
        super().__init__(self.config["jid"], self.config["password"])

        self.rooms = []
        self.nick = self.config.get("nick", "bot")
        self.admins = []
        owner = self.config.get("owner")
        if owner:
            self.admins.append(slixmpp.JID(owner).bare)
        self.prefix = self.config.get("prefix", ",")

        # Presence Manager
        self.presence = PresenceManager(self)

        # Database Manager
        self.db = DatabaseManager(self.config.get("db", "bot.db"))

        # Plugin Manager
        self.commands = {}
        self.plugins = PluginManager(self)
        self.plugins.load_all()

        self.add_event_handler("session_start", self.on_start)
        self.add_event_handler("groupchat_message", self.on_muc_message)
        self.add_event_handler("message", self.on_private_message)
        self.add_event_handler("muc::%s::got_online" % "*", self.on_muc_join)
        self.add_event_handler("muc::%s::got_offline" % "*", self.on_muc_leave)

    async def get_user_role(self, jid) -> Role:
        """
        Resolve a user's role using config and database.
        """

        jid = slixmpp.JID(jid).bare

        owner_jid = slixmpp.JID(self.config["owner"]).bare

        # owner override
        if jid == owner_jid:
            return Role.OWNER

        role_name = await self.db.users.get_role(jid)

        if not role_name:
            return Role.NONE

        try:
            return Role[role_name.upper()]
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
            log.info("Autojoining room %s as %s", room_jid, nick)
            self.plugin["xep_0045"].join_muc(
                room_jid,
                nick,
                pshow=self.presence.status["show"],
                pstatus=self.presence.status["status"])
            if room_jid not in self.rooms:
                self.rooms.append(room_jid)
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

        sender = str(msg["from"])

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

            # cleanup old entries occasionally
            if len(self._reply_rate) > 1000:
                cutoff = now - 60
                self._reply_rate = {
                    k: v for k, v in self._reply_rate.items()
                    if v > cutoff
                }

        if msg["type"] == "groupchat":
            body = text

            if mention:
                nick = msg.get("mucnick") or msg["from"].resource
                body = f"{nick}: {text}"

            # Build message safely (supports thread when possible)
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
                        pass

            message.send()

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

            message.send()

    async def on_start(self, event):
        # send startup presence
        self.presence.broadcast()
        # Get roster
        await self.get_roster()
        # Connect to DB
        await self.db.connect()
        # Autojoin Rooms from DB
        await self.autojoin_rooms()
        # send presence again
        self.presence.broadcast()
        # set automatic mutual subscriptions
        self.roster.auto_subscribe = True

        log.info("✅ Bot started, all rooms joined")

    def is_admin(self, jid):
        return slixmpp.JID(jid).bare in self.admins

    def on_muc_join(self, presence):

        room = presence["from"].bare
        nick = presence["muc"]["nick"]

        log.info("[MUC] 🤖 Joined room %s as %s", room, nick)

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
            if room in self.rooms:
                self.rooms.remove(room)
            log.info("[MUC] 🚪 Left room %s (%s)", room, nick)

    async def on_muc_message(self, msg):

        room = msg['from'].bare
        nick = msg['mucnick']
        if self.presence.joined_rooms.get(room) == nick:
            return

        if msg["type"] == "groupchat":
            await self.handle_command(
                msg["body"],
                msg["from"].bare,
                msg["mucnick"],
                msg,
                True
            )

    async def on_private_message(self, msg):

        if msg["type"] in ("chat", "normal"):
            await self.handle_command(
                msg["body"],
                msg["from"].bare,
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

        # resolve command using command resolver
        cmd_obj, args = resolve_command(text)

        if not cmd_obj:
            return

        cmd_name = cmd_obj.name

        # determine sender role
        user_role = await self.get_user_role(sender_jid)

        # permission check
        if not check_permission(user_role, cmd_obj):
            target = msg["from"].bare if is_room else msg["from"]

            self.send_message(
                mto=target,
                mbody="❌You are not allowed to use this command.",
                mtype="groupchat" if is_room else "chat"
            )
            return

        try:
            handler = cmd_obj.handler
            if inspect.iscoroutinefunction(handler):
                await handler(self, sender_jid, nick, args, msg, is_room)
            else:
                handler(self, sender_jid, nick, args, msg, is_room)
        except Exception as e:
            log.exception(f"❌ Error while executing command '{cmd_name}'")
            target = msg["from"].bare if is_room else msg["from"]
            if user_role in (Role.OWNER, Role.ADMIN):
                err_msg = f"❌Command error: {e}"
            else:
                err_msg = f"❌Command '{cmd_name}' failed due to internal error."

            self.send_message(
                mto=target,
                mbody=err_msg,
                mtype="groupchat" if is_room else "chat"
            )


async def main():
    xmpp = Bot("config.json")

    xmpp.register_plugin("xep_0030")
    xmpp.register_plugin("xep_0045")
    xmpp.register_plugin("xep_0084")
    xmpp.register_plugin("xep_0163")
    xmpp.register_plugin("xep_0054")

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
