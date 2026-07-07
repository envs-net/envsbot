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

# Also prune managed backup archives older than this many days.
# Set to 0 to disable age-based pruning.
BACKUP_RETENTION_DAYS = 0

# Create a managed backup once during each bot process start. This also covers
# service restarts, because a restart starts a fresh bot process.
BACKUP_ON_START = True


# ================= COMMAND RATE LIMITS =================

# Protect the bot from command spam. Limits are in-memory and reset on restart.
COMMAND_RATE_LIMIT_ENABLED = True
COMMAND_RATE_LIMIT_CAPACITY = 4
COMMAND_RATE_LIMIT_REFILL_AMOUNT = 1
COMMAND_RATE_LIMIT_REFILL_INTERVAL_SECONDS = 0.5
COMMAND_RATE_LIMIT_DENY_WINDOW_SECONDS = 10.0
COMMAND_RATE_LIMIT_DENY_THRESHOLD = 6
COMMAND_RATE_LIMIT_BASE_BLOCK_SECONDS = 30.0
COMMAND_RATE_LIMIT_BACKOFF_MULTIPLIER = 2.0
COMMAND_RATE_LIMIT_MAX_BLOCK_SECONDS = 3600.0
COMMAND_RATE_LIMIT_NOTIFY_COOLDOWN_SECONDS = 10.0

# Users with this role or better bypass command rate limits.
# Use one of: owner, superadmin, admin, moderator, trusted, user, new, none.
COMMAND_RATE_LIMIT_BYPASS_ROLE = "moderator"


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
    "idlerpg": False,
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


# ================= USER TRACKING =================

USERS = {
    "max_room_nicks": 5,
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

# Maximum number of new entries posted per regular feed poll.
# If a very active feed publishes more than this between two checks, older
# unseen entries are skipped and the newest item is remembered as seen.
RSS_MAX_ENTRIES_PER_POLL = 10

# Retry/backoff behavior for failing feeds.
# First failure retries after 5 minutes, second after 10 minutes, then grows
# exponentially up to the maximum delay.
RSS_RETRY_INITIAL_DELAY = 300
RSS_RETRY_BACKOFF_MULTIPLIER = 2.0
RSS_MAX_BACKOFF_TIME = 3600

# Duplicate title/description detection threshold, 0 < value <= 1.
RSS_SIMILARITY_THRESHOLD = 0.8
RSS_USER_AGENT = HTTP_USER_AGENT

# Explicit RSS HTTP fetch limits.
RSS_FETCH_TIMEOUT_SECONDS = HTTP_TIMEOUT_SECONDS
RSS_MAX_REDIRECTS = 5
RSS_MAX_READ_BYTES = 1048576

# Maximum length of a per-room RSS message template configured with ,rss template.
RSS_TEMPLATE_MAX_LENGTH = 1000


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


# ================= IDLERPG =================

# Classic IRC-style IdleRPG adapted for XMPP MUCs.
# Players level up by staying online and idle. Normal room messages add
# penalty time to the player's timer. See docs/idlerpg.md for details.
IDLERPG = {
    # Game loop interval. Lower values make timers, map movement and random
    # events feel more responsive, but also run the loop more often.
    "tick_seconds": 60,

    # Level timer formula: TTL = rp_base * (rp_step ** current_level).
    "rp_base": 600,
    "rp_step": 1.16,

    # Message/logout penalties. Message penalty formula:
    # penalty = max(1, len(body) * message_penalty) * (penalty_step ** current_level).
    # logout_grace_seconds lets short reconnects avoid logout penalties.
    "penalty_step": 1.14,
    "message_penalty": 1,
    "logout_penalty": 20,
    "logout_grace_seconds": 300,
    "max_penalty": 604800,
    "count_command_messages": False,

    # Output paging and text/website map dimensions. Coordinates are rendered
    # as [x,y] within this map size, for example [293,133] on a 500x500 map.
    "page_size": 10,
    "map_x": 500,
    "map_y": 500,
    # Original-style grid movement: every simulated second, online players
    # have equal chances to step left/right/neither and up/down/neither.
    "map_step_per_second": 1,
    # Legacy alias; prefer map_step_per_second for new configs.
    "map_step_per_tick": 1,
    "grid_battle_enabled": True,
    "quest_grid_step_seconds": 2,

    # Quest timing. Grid quests must reach route points before this deadline.
    "quest_min_level": 40,
    "quest_interval": 21600,
    "quest_min_duration": 43200,
    "quest_max_duration": 86400,

    # Random events. event_chance is checked once per game tick and room.
    # Event weights are relative to each other.
    "event_chance": 0.01,
    "item_chance": 0.20,
    "battle_event_weight": 0.55,
    "team_battle_event_weight": 0.08,
    "item_event_weight": 0.15,
    "item_damage_event_weight": 0.08,
    "item_steal_event_weight": 0.04,
    "alignment_event_weight": 0.10,
    "critical_strike_chance": 0.10,
    "item_drop_chance": 0.12,

    # Balancing percentages. Battle win/loss percentages are minimum values;
    # opponent level can increase them. Godsend/calamity/critical ranges are
    # percentages of the affected player's remaining time-to-level.
    "battle_win_min_percent": 7,
    "battle_loss_min_percent": 7,
    "critical_min_percent": 5,
    "critical_max_percent": 25,
    "godsend_min_percent": 5,
    "godsend_max_percent": 12,
    "calamity_min_percent": 5,
    "calamity_max_percent": 12,
    "alignment_bonus_percent": 7,
    "quest_reward_percent": 25,
    "team_battle_percent": 20,

    # Manual duels let nearby online players challenge each other. Distance is
    # measured on the IdleRPG map; cooldown applies to both duelists to avoid
    # spam and dogpiling.
    "manual_duel_max_distance": 10,
    "manual_duel_cooldown_seconds": 3600,

    # Unique envs.net-flavoured items can appear at higher levels and grant
    # small bonuses such as reduced penalties or slightly stronger battles.
    "unique_items_enabled": True,
    "unique_item_min_level": 25,
    "unique_item_chance": 0.025,

    # Announcements and optional room topic integration. Login announcements
    # default to True to make the game feel alive. Topic updates are disabled
    # by default because not every MUC wants bots to change subjects.
    "announce_login": True,
    "announce_top_interval": 21600,
    "announce_top_limit": 5,
    "update_room_topic": False,
    "topic_update_interval": 14400,
    # Optional prefix for room topics. Result: "<topic_custom_text> #1: ..."
    # If empty, export_public_base_url is used; otherwise "IdleRPG".
    "topic_custom_text": "",

    # Level-gated reward badges and season-age achievement gates keep long-term
    # achievements from all appearing at the very start of a season.
    "level_reward_min_level": 50,
    "season_achievement_gates_enabled": True,

    # Event log retained in bot state and exported for the website.
    "event_log_limit": 200,
    "event_retention_days": 90,
    "export_event_limit": 50,

    # Public JSON export for the website. Prefer exporting directly into a
    # web-readable directory instead of making the webserver read bot-internal
    # paths under /srv/envsbot.
    "export_enabled": True,
    "export_path": "data/idlerpg",
    "export_public_base_url": "",
    "export_top_limit": 50,

    # Seasons and Hall of Fame. Automatic season rollover is disabled by
    # default; manual `,idlerpg season end/reset/extend/clear-end` still works
    # for admins. Set season_duration_days to 0 for manual/endless seasons.
    "season_enabled": False,
    "season_duration_days": 90,
    "season_reset_on_rollover": False,
    "season_hof_size": 10,
}
