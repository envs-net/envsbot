# ================= ENVSBOT CONFIG SAMPLE =================
#
# Copy this file to config.py and adjust it for your installation.
# Keep config.py private: it contains your bot password and optional API keys.


# ================= XMPP ACCOUNT =================

# XMPP account used by the bot.
JID = "envsbot@domain.tld"
PASSWORD = "yourpassword"
NICK = "EnvsBot"

# Optional XMPP resource. Set to None to let Slixmpp/server choose one.
RESOURCE = "service"

# Bare JID of the bot owner. The owner has the highest runtime role.
OWNER = "owner@domain.tld"

# Optional additional privileged users. Roles can also be managed at runtime
# through the users commands.
ADMINS = []


# ================= CONNECTION =================

# Optional connection host override. None uses the domain from JID.
CONNECT_HOST = None

# XMPP client-to-server port.
# 5222 = normal C2S with STARTTLS
# 5223 = direct TLS / legacy SSL when your server requires it
CONNECT_PORT = 5222

# False = regular STARTTLS on port 5222.
# True = direct TLS / legacy SSL, commonly on port 5223.
CONNECT_DIRECT_TLS = False

# XMPP query timeout used by diagnostic/info commands.
XMPP_QUERY_TIMEOUT_SECONDS = 8


# ================= BOT RUNTIME =================

# Python logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL.
LOG_LEVEL = "INFO"

# Command prefix used to trigger bot commands in rooms and direct chats.
COMMAND_PREFIX = ","

# Default timezone for bot-side date/time handling.
TIMEZONE = "Europe/Berlin"

# SQLite database file, relative to the bot directory unless absolute.
DB_FILE = "bot.db"

# File used to remember who requested a bot restart across process restarts.
RESTART_NOTIFICATION_FILE = "/tmp/envsbot_restart_notification.json"

# Command used by ,bot shutdown. Keep this as a list of arguments.
STOP_CMD = ["/usr/bin/systemctl", "--user", "stop", "envsbot.service"]


# ================= BACKUPS =================

# Managed ZIP backups are written here. The default is ignored by git.
# Archives include bot.db, config.py, vcard.py and chat_slang.csv when present.
BACKUP_DIR = "data/backups"

# Keep this many managed backup archives after creating a new one.
BACKUP_KEEP = 15

# Create a managed backup once during each bot process start. This also covers
# service restarts, because a restart starts a fresh bot process.
BACKUP_ON_START = True


# ================= HTTP DEFAULTS =================

# Generic HTTP timeout and User-Agent used by plugins unless a plugin-specific
# value is set below. Keep the User-Agent versionless so it does not have to be
# updated for every release.
HTTP_TIMEOUT_SECONDS = 8
HTTP_USER_AGENT = "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)"

# Safety guard for user-supplied URLs fetched by RSS and URL title checks.
# Keep False for normal public bots. Set True only for trusted/private rooms.
ALLOW_PRIVATE_FETCH_URLS = False


# ================= vCARD / AVATAR =================

# Bot avatar. Set AVATAR_PATH = None to disable avatar publishing.
# Put your own avatar below data/ and do not overwrite the default repo avatar.
AVATAR_PATH = "avatar.jpg"
AVATAR_TYPE = "image/jpeg"  # image/jpeg or image/png

# Timeout for vCard fetches made by vcard, weather and birthday helpers.
VCARD_FETCH_TIMEOUT_SECONDS = 10

# The visible profile fields themselves are configured in vcard.py.


# ================= RELEASE UPDATE CHECK =================

# Manual ,checkupdate works even when periodic checks are disabled.
VERSION_CHECK_ENABLED = False
VERSION_CHECK_INTERVAL = 3600
VERSION_CHECK_URL = "https://github.com/envs-net/envsbot/releases/latest"
# Empty = notify OWNER. If this is a MUC room, the bot joins it before sending.
VERSION_CHECK_NOTIFY_JID = ""
UPDATECHECK_TIMEOUT_SECONDS = 15


# ================= ROOM INVITES =================

# When enabled, incoming MUC invites are stored as pending room invites and
# announced to ROOM_INVITE_NOTIFY_JID, VERSION_CHECK_NOTIFY_JID, or OWNER.
# The bot does not join the invited room until an admin accepts the invite.
ROOM_INVITES_ENABLED = True
ROOM_INVITE_NOTIFY_JID = ""  # empty = VERSION_CHECK_NOTIFY_JID, then OWNER

# Pending room invites older than this many days are expired automatically.
# Set to 0 to keep pending invites until accepted/declined/cleanup.
ROOM_INVITE_MAX_AGE_DAYS = 30


# ================= ROOM PLUGIN DEFAULTS =================

# Default room feature state used for newly added rooms and for
# ,rooms set_plugin_defaults. Missing keys keep their internal fallback.
# Unknown keys are ignored with a warning. Per-room changes are still stored
# in the database and can be managed with ,rooms enable/disable.
ROOM_PLUGIN_DEFAULTS = {
    "birthday_notify": False,
    "dice": True,
    "ducks": False,
    "help": False,
    "information": True,
    "karma": False,
    "pin": True,
    "poll": False,
    "presence": True,
    "reminder": True,
    "sed": True,
    "tell": True,
    "tools": True,
    "urlcheck": True,
    "vcard": True,
    "weather": True,
    "xkcd": False,
    "xmpp": True,
}


# ================= URL CHECK =================

# Suppress repeated output for the same URL in the same room for this many seconds.
URLCHECK_WAIT_SECONDS = 120

# URL fetch limits for title/description extraction and YouTube metadata.
URLCHECK_FETCH_TIMEOUT_SECONDS = 8
URLCHECK_MAX_REDIRECTS = 5
URLCHECK_MAX_READ_BYTES = 65536
URLCHECK_USER_AGENT = HTTP_USER_AGENT

# YouTube Data API key for richer URL metadata lookups. None disables YouTube
# API data but regular URL title checks still work.
YOUTUBE_API_KEY = None


# ================= RSS / ATOM =================

# Default global feed check interval in seconds.
RSS_GLOBAL_QUERY_INTERVAL = 1200

# Number of existing entries to show when a feed is newly added.
MAX_NEW_FEED_ENTRIES = 5

# Backoff behavior for failing feeds.
RSS_MAX_BACKOFF_TIME = 86400
RSS_BACKOFF_INCREMENT_MULTIPLIER = 60

# Duplicate title/description detection threshold, 0 < value <= 1.
RSS_SIMILARITY_THRESHOLD = 0.8
RSS_USER_AGENT = HTTP_USER_AGENT

# Explicit RSS HTTP fetch limits.
RSS_FETCH_TIMEOUT_SECONDS = HTTP_TIMEOUT_SECONDS
RSS_MAX_REDIRECTS = 5
RSS_MAX_READ_BYTES = 1048576


# ================= BIRTHDAY NOTIFY =================

# Cache positive and negative vCard BDAY results for this many seconds.
BIRTHDAY_CACHE_TTL_SECONDS = 43200

# Delay first scan after startup so room joins and presence can settle.
BIRTHDAY_INITIAL_SCAN_DELAY_SECONDS = 10

# Periodic loop interval in seconds. The expensive full scan still only runs once per day.
BIRTHDAY_CHECK_INTERVAL_SECONDS = 3600


# ================= REMINDERS =================

REMINDER_ENABLED = True
REMINDER_MAX_AGE_DAYS = 365


# ================= DUCK GAME =================

DUCKS = {
    "min_messages": 150,
    "max_messages": 500,
    "spawn_chance": 20,
    "max_ducks_per_day": 3,
    "timeout": 0,
    "count_commands": False,
    "state_save_every": 1,
}


# ================= USER TRACKING =================

USERS = {
    "max_room_nicks": 5,
}


# ================= SED CORRECTIONS =================

SED_REGEX_TIMEOUT = 1.0
SED_MAX_PATTERN_LENGTH = 256
SED_MAX_REPLACEMENT_LENGTH = 1000
SED_MAX_INPUT_LENGTH = 5000
SED_MAX_OUTPUT_LENGTH = 8000
SED_CACHE_SIZE = 10


# ================= POLLS =================

POLL_MAX_OPTIONS = 10
POLL_MAX_QUESTION_LEN = 200
POLL_MAX_OPTION_LEN = 100
POLL_MAX_HISTORY_PER_ROOM = 50


# ================= PINS =================

PIN_PAGE_SIZE = 10
PIN_RECENT_CACHE_SIZE = 80


# ================= KARMA / TELL =================

KARMA_DELAY_SECONDS = 60
TELL_DELIVERY_DELAY_SECONDS = 5


# ================= XKCD =================

XKCD_CHECK_INTERVAL = 3600
XKCD_INDEX_START_DELAY_SECONDS = 30
XKCD_INDEX_REQUEST_DELAY_SECONDS = 0.15
XKCD_HTTP_TIMEOUT = 10
