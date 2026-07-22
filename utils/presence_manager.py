import logging

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

    @staticmethod
    def _set_avatar_hash(presence, avatar_hash):
        """Set one XEP-0153 avatar payload on a stream-bound presence.

        XEP-0153 registers ``vcard_temp_update`` as a stanza plugin. Using the
        plugin interface lets Slixmpp's outgoing filter update the same XML
        element instead of appending a second ``<x/>`` payload.
        """
        presence["vcard_temp_update"]["photo"] = avatar_hash

    def _send_presence(self, pto=None):
        """Create and send one stream-bound presence stanza.

        Building ``Presence()`` directly leaves the stanza detached from the
        active XML stream. Slixmpp may later replay that stanza to a newly
        subscribed roster contact, which then fails with "Tried to send stanza
        without a stream". ``make_presence()`` associates it with the bot's
        stream from the beginning.
        """
        show = self.status.get("show", "online")
        status = self.status.get("status", "")
        avatar_hash = self._avatar_hash()
        kwargs = {
            "pshow": None if show == "online" else show,
            "pstatus": status,
        }
        if pto is not None:
            kwargs["pto"] = pto

        # XEP-0153's outgoing presence filter resolves the cached avatar hash
        # using the stanza sender. Client presences normally omit ``from``,
        # which can make the filter replace an already attached photo hash
        # with an empty value. Use the exact bound full JID whenever an avatar
        # is advertised so the filter resolves the bot's own hash reliably.
        if avatar_hash:
            boundjid = getattr(self.bot, "boundjid", None)
            sender = str(getattr(boundjid, "full", "") or "").strip()
            if sender:
                kwargs["pfrom"] = sender

        presence = self.bot.make_presence(**kwargs)
        if avatar_hash:
            self._set_avatar_hash(presence, avatar_hash)

        if getattr(presence, "stream", None) is None:
            log.warning(
                "[PRESENCE] Skipping unbound presence stanza%s",
                f" to {pto}" if pto else "",
            )
            return False

        presence.send()
        return True

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
