import logging

# === set up logging ===
log = logging.getLogger(__name__)


# -------------------------------------------------
# PresenceManager Class
# -------------------------------------------------

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
