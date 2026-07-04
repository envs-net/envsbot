import logging

from slixmpp.stanza.presence import Presence
from slixmpp.xmlstream import ET

# === set up logging ===
log = logging.getLogger(__name__)


# -------------------------------------------------
# PresenceManager Class
# -------------------------------------------------

class PresenceManager:
    """
    Manages the bot presence status and broadcasts it to the server and to
    joined MUC rooms.

    If the bot profile plugin has published an avatar, ``bot.avatar_hash`` is
    added to outgoing presence using XEP-0153. This is important for MUC users
    who do not have the bot in their roster: they may not receive PEP avatar
    updates, but they do see the directed MUC presence.
    """

    def __init__(self, bot):
        """Initialize the PresenceManager with a bot instance."""
        self.bot = bot

        self.status = {
            "show": "online",
            "status": "I'm ready to serve you!"
        }

        self.joined_rooms = {}
        self._last_info_logged_status = None

        self.emojis = {
            "online": "✅",
            "chat": "💬",
            "away": "👋 ",
            "xa": "💤",
            "dnd": "⛔"
        }

    def update(self, show, status):
        """Update the bot's presence status and broadcast the change."""
        self.status["show"] = show
        self.status["status"] = status

        self.broadcast()

    def _avatar_hash(self):
        """Return the current XEP-0153 avatar hash, if available."""
        avatar_hash = getattr(self.bot, "avatar_hash", None)
        if not avatar_hash:
            return None
        return str(avatar_hash)

    def _append_avatar_hash(self, presence, avatar_hash):
        """Append the XEP-0153 vCard avatar hash payload."""
        x = ET.Element("{vcard-temp:x:update}x")
        photo = ET.SubElement(x, "photo")
        photo.text = avatar_hash
        presence.append(x)

    def _send_presence(self, pto=None):
        """
        Send one presence stanza, including the avatar hash when known.

        Slixmpp's convenience send_presence() helper does not let us append the
        XEP-0153 payload, so we build the stanza manually only when needed.
        """
        show = self.status.get("show", "online")
        status = self.status.get("status", "")
        avatar_hash = self._avatar_hash()

        if not avatar_hash:
            kwargs = {"pshow": show, "pstatus": status}
            if pto is not None:
                kwargs["pto"] = pto
            self.bot.send_presence(**kwargs)
            return

        presence = Presence()
        if pto:
            presence["to"] = pto
        if show and show != "online":
            presence["show"] = show
        if status:
            presence["status"] = status
        self._append_avatar_hash(presence, avatar_hash)
        self.bot.send(presence)

    def broadcast(self):
        """
        Broadcast the current presence status globally and to joined rooms.
        """
        show = self.status.get("show", "online")
        status = self.status.get("status", "")

        try:
            self._send_presence()
        except Exception:
            log.exception("[PRESENCE] Failed to send presence")

        # --- Get JOINED_ROOMS from "rooms" plugin (safe access) ---
        try:
            rooms_plugin = self.bot.bot_plugins.plugins.get("rooms", None)
            if rooms_plugin is not None:
                # Make a defensive copy to avoid race conditions
                rooms_copy = dict(rooms_plugin.JOINED_ROOMS)
                for room, room_data in rooms_copy.items():
                    try:
                        nick = room_data.get("nick")
                        if nick:
                            self._send_presence(pto=f"{room}/{nick}")
                    except Exception as e:
                        log.debug(
                            "[PRESENCE] Failed to send presence to room "
                            f"{room}: {e}")
        except Exception as e:
            log.debug(f"[PRESENCE] Error accessing rooms plugin: {e}")

        # Log the first status broadcast at INFO, but keep repeated
        # unchanged broadcasts at DEBUG to avoid noisy startup logs while
        # still making them visible when debug logging is enabled.
        current_status = (show, status)
        log_method = log.info
        if self._last_info_logged_status == current_status:
            log_method = log.debug
        else:
            self._last_info_logged_status = current_status

        log_method(f"[PRESENCE] {self.emoji(show)} Status set: "
                   f"'{show}': [{status}]")

    def emoji(self, show=None):
        """Get the emoji representation for a given presence state."""
        show = show or self.status.get("show", "online")
        return self.emojis.get(show, "")
