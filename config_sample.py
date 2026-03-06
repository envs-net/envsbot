# ================= CONFIG =================
import logging

# === Logging ===
LOG_LEVEL = logging.INFO            # Logging verbosity

# === Account data ===
JID = "edna@domain.tld"             # JID of the bot
PASSWORD = "yourpassword"           # Password of the bot
NICK = "edna"                       # Nick of the bot

# === Adminstration ===
ADMINS = ["admin@domain.tld"]       # Bot Administrators
ROOMS = ["<room>@muc.domain.tld"]   # Rooms the bot should join
START_SHOW = "online"               # Startup status show
START_STATUS = "online"             # Startup status message

# === sqlite database ===
DB_FILE = "bot.db"                  # Bot sqlite DB
