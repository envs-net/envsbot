# ================= CONFIG =================
import logging

# === Logging ===
LOG_LEVEL = logging.INFO                    # Logging verbosity

# === Account data ===
JID = "bot@domain.tld/envsbot"              # JID of the bot
PASSWORD = "<password>"               # Password of the bot
NICK = "envsbot"                            # Nick of the bot

# === Adminstration ===
ADMINS = ["admin@domain.tld"]                   # Bot Administrators
# Rooms to join
ROOMS = ["room@muc.domain.tld"]

# === Startup status ===
START_SHOW = "online"                       # online|chat|away|xa|dnd
START_STATUS = "I'm ready to serve you!"    # Startup status message
START_PRIORITY = 0                          # Startup priority

# === sqlite database ===
DB_FILE = "bot.db"                          # Bot sqlite DB

# === Personal Data ===
AVATAR = "envsbot.jpg"                      # Avatar file
AVATAR_TYPE = "image/jpeg"                  # Avatar type
VCARD_FN = "EnvsBot, der envs Service Bot"  # Bot Fullname
VCARD_NICKNAME = "envsbot"                  # Bot Nickname
VCARD_JABBERID = "bot@domain.tld"           # Bot Jid
# URLs to bot Git repository and Homepage
VCARD_URL = "https://git.envs.net/dan/envsbot"
VCARD_EMAIL_USERID = "dan@envs.net"         # Author Email
VCARD_BDAY = "2026-03-06"                   # Birthday of bot
VCARD_GENDER = "it/its"                     # Bot gender
# Bot description
VCARD_DESC = """I'm a bot which will have a lot of tools which will be all
documented inside the bot. I'm still in development, but my development
progresses. I'm still in an early stage of development and a lot of
functionality has still to be implemented.\n\n
You can send a XMPP subscription request to the above JABBERID/XNPP address
and I'll send a subscription request back, and if you accept it, I'll
automatically be added to your roster."""
# Organisation
VCARD_ORG_ORGNAME = "Envs pubnix/tilde"
VCARD_ORG_ORGUNIT = "XMPP server"
VCARD_TITLE = "Automatic helper bot"
