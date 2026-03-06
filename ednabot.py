# ========== EDNA Bot ==========
import asyncio
import logging

from pathlib import Path

from slixmpp import ClientXMPP
from slixmpp.xmlstream import ET

import config

# === set up logging ===
logging.basicConfig(level=config.LOG_LEVEL)
log = logging.getLogger(__name__)

# ===== Actual EdnaBot Class =====
class EdnaBot(ClientXMPP):
    """ A XMPP bot with various functions """

    def __init__(self, jid, password):
        """ Initialize bot and set event handlers

            Handlers:
                session_start(event)        - bot start event
                on_message(msg)             - got chat message
        """
        super().__init__(jid, password)

        # Register plugins
        self.register_plugin('xep_0030')    # Service Discovery
        self.register_plugin('xep_0045')    # Multi User Chat

        self.add_event_handler("session_start", self.session_start)
        self.add_event_handler("message", self.on_message)

    # ===== Callback for startup =====
    async def session_start(self, event):
        """ Called when session starts
            - Joins rooms
            - Sets initial presence/status
        """
        self.status = self.make_presence(pshow=config.START_SHOW,
                                         pstatus=config.START_STATUS,
                                         ppriority=0)
        self.status.send()
        await self.get_roster()

        for room in config.ROOMS:
            self.plugin["xep_0045"].join_muc(room, config.NICK,
                                             pstatus=config.START_STATUS,
                                             pshow=config.START_SHOW)

        # set automatic mutual subscriptions
        self.roster.auto_subscribe = True

        # Bot started
        log.info("✅ Bot started, all rooms joined")

    # ===== Callback if message arrives =====
    async def on_message(self, msg):
        """ Callback, that's called when the bot gets a message """

        # ignore own messages
        if msg['type'] == "groupchat" and msg['mucnick'] == config.NICK:
            return

        # Check if msg is from admin
        if self.is_admin(msg['from'].bare):
            await self.admin_cmds(msg)
        else:
            await self.user_cmds(msg)

    # ===== helper functions =====
    # ===== Checks if a JID is bot admin =====
    def is_admin(self, jid):
        """ Checks if jid is bot admin """

        if jid in config.ADMINS:
            return True
        return False

    # ===== Send ephemeral message, which won't be stored on the server =====
    def send_ephemeral(self, mto: str, mtype: str, mbody):
        """
        Sends ephemeral message which doesn't get stored on the
        server.
        """

        msg = self.Message()
        msg['to'] = mto
        msg['type'] = mtype
        msg['body'] = mbody
        no_store = ET.Element("{urn:xmpp:hints}no-store")
        msg.append(no_store)
        msg.send()

    # ===== Show online/chat/away/xa/dnd status with comment =====
    def show_status(self, msg):
        """ Shows status to requesting JID """

        # show status
        if self.status['show'] == "online":
            send_body = f"✅ Online: {self.status['status']}"
        elif self.status['show'] == "chat":
            send_body = f"🗨 Free for chat: {self.status['status']}"
        elif self.status['show'] == "away":
            send_body = f"🫧 Away: {self.status['status']}"
        elif self.status['show'] == "xa":
            send_body = f"💤 Extended away: {self.status['status']}"
        elif self.status['show'] == "dnd":
            send_body = f"⛔Do not disturb: {self.status['status']}"
        else:
            send_body = "❌offline"
        mfrom = msg['from'] if msg['type'] == "chat" else msg['from'].bare
        self.send_ephemeral(mfrom, msg['type'], send_body)

    # ===== Set MUC status of bot =====
    def set_muc_status(self, room=None, show=None, status=None, priority=None):
        """ Sends a presence to a room """

        if room is None:
            return
        pres = self.make_presence(pto=f"{room}/{config.NICK}")
        if show:
            pres['show'] = show
        if status:
            pres['status'] = status
        if priority:
            pres['priority'] = priority
        pres.send()

    # ===== COMMANDS SECTION =====
    # ===== All Administrator Commands =====
    async def admin_cmds(self, msg):
        """ All administrator commands """

        mtype = msg['type']
        nick = msg['mucnick'] if mtype == "groupchat" else ""
        body = msg['body']
        parts = body.split()
        cmd = parts[0] if parts else ""

        match cmd:
            case ",help" | ",h":
                self.cmd_help(msg, mtype, nick, cmd, parts, body)
            case ",status" | ",s":
                self.cmd_status(msg, mtype, nick, cmd, parts, body)
            case ",roster" | ",r":
                self.cmd_roster(msg, mtype, nick, cmd, parts, body)
            case _:
                return

    # ===== All User Commands =====
    async def user_cmds(self, msg):
        """ All user commands """

        mtype = msg['type']
        nick = msg['mucnick'] if mtype == "groupchat" or mtype == "chat" else ""
        body = msg['body']
        parts = body.split()
        cmd = parts[0] if parts else ""

        match cmd:
            case ",help" | ",h":
                self.cmd_help(msg, mtype, nick, cmd, parts, body)
            case ",status" | ",s":
                self.cmd_status(msg, mtype, nick, cmd, parts, body)
            case _:
                return

    # ===== Help Command (,help) =====
    def cmd_help(self, msg, mtype, nick, cmd, parts, body):
        """ Shows different help files for users and admins """

        if self.is_admin(msg['from'].bare):
            send_body = f"✅ Help:\n{ADMIN_HELP}"
        else:
            send_body = f"✅ {nick + " " if nick != "" else ""}Help:"
            if mtype == "groupchat":
                send_body += " Help only in direct chat. No spamming!"
            else:
                send_body += f"\n{USER_HELP}"
        mfrom = msg['from'] if mtype == "chat" else msg['from'].bare
        self.send_ephemeral(mfrom, mtype, send_body)

    # ===== Status command (,status) =====
    def cmd_status(self, msg, mtype, nick, cmd, parts, body):
        """
        Show/Set presence for bot and participated rooms

        Admin:
          - <,s|,status> [chat|online|away|xa|dnd [status comment]]
            shows status if rest is omitted or garbled. Otherwise sets status.
        User:
          - <,s|,status>
            shows status
        """

        if (self.is_admin(msg['from'].bare) and len(parts) >= 2
                and parts[1] in ["chat", "online", "away", "xa", "dnd"]):
            # build presence
            if len(parts) >= 3:
                status = " ".join(parts[2:])
            else:
                status = ""
            self.status = self.make_presence(pshow=parts[1], pstatus=status,
                                             ppriority=0)
            # set presence of bot and in all rooms
            self.status.send()
            for room in config.ROOMS:
                self.set_muc_status(room=room, show=parts[1], status=status)
            # show status
            self.show_status(msg)
        else:
            # just show status
            self.show_status(msg)

    # ===== Roster Command (,roster) =====
    def cmd_roster(self, msg, mtype, nick, cmd, parts, body):
        return


# ===== MAIN ROUTINE =====
if __name__ == '__main__':
    # Get help from files
    ADMIN_HELP = Path('admin_help.txt').read_text()
    USER_HELP = Path('user_help.txt').read_text()
    xmpp = EdnaBot(config.JID, config.PASSWORD)
    if xmpp.connect():
        log.info("Connected successfully. Starting event loop...")
        try:
            # Run the slixmpp event loop forever
            asyncio.get_event_loop().run_forever()
        except KeyboardInterrupt:
            # Gracefully shut down on CTRL-c
            log.info("Bot stopped manually.")
            xmpp.disconnect()
    else:
        log.error("Unable to connect to XMPP server.")
