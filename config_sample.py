# ================= ENVSBOT CONFIG SAMPLE =================
#
# Generated from utils/config/spec.py. Do not edit this sample by hand;
# change the schema and run scripts/generate_config_sample.py instead.
# Copy this file to config.py and adjust it for your installation.
# Keep config.py private: it contains your bot password and optional API keys.

# ================= XMPP ACCOUNT =================

# XMPP account used by the bot.
# Startup-only: restart envsbot after changing this value.
JID = 'envsbot@domain.tld'

# Password.
# Startup-only: restart envsbot after changing this value.
PASSWORD = 'yourpassword'

# Nick.
NICK = 'EnvsBot'

# Optional XMPP resource. Set to None to let Slixmpp/server choose one.
# Startup-only: restart envsbot after changing this value.
RESOURCE = 'service'

# Bare JID of the bot owner. The owner has the highest runtime role.
OWNER = 'owner@domain.tld'

# Optional additional privileged users. Roles can also be managed at runtime through
# the users commands.
ADMINS = []


# ================= CONNECTION =================

# Optional connection host override. None uses the domain from JID.
# Startup-only: restart envsbot after changing this value.
CONNECT_HOST = None

# XMPP client-to-server port. 5222 = normal C2S with STARTTLS 5223 = direct TLS /
# legacy SSL when your server requires it
# Startup-only: restart envsbot after changing this value.
CONNECT_PORT = 5222

# False = regular STARTTLS on port 5222. True = direct TLS / legacy SSL, commonly on
# port 5223.
# Startup-only: restart envsbot after changing this value.
CONNECT_DIRECT_TLS = False

# XMPP query timeout used by diagnostic/info commands.
XMPP_QUERY_TIMEOUT_SECONDS = 8

# Maximum bytes read from compliance.conversations.im for ,xmpp compliance. The
# command only needs a small HTML preview containing the score marker.
XMPP_COMPLIANCE_MAX_READ_BYTES = 262144


# ================= BOT RUNTIME =================

# Python logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL.
LOG_LEVEL = 'INFO'

# Directory for the rotating envsbot.log file. Use an absolute path such as
# /var/log/envsbot with the hardened systemd unit.
# Startup-only: restart envsbot after changing this value.
LOG_DIR = 'logs'

# Command prefix used to trigger bot commands in rooms and direct chats.
COMMAND_PREFIX = ','

# Default timezone for bot-side date/time handling.
TIMEZONE = 'Europe/Berlin'

# SQLite database file, relative to the bot directory unless absolute.
# Startup-only: restart envsbot after changing this value.
DB_FILE = 'data/bot.db'

# Directory for mutable support files such as vcard.py, chat_slang.csv, slang review
# queues and profile hash markers. None keeps the historical application-root location
# for compatibility. Hardened systemd installs should set /var/lib/envsbot.
# Startup-only: restart envsbot after changing this value.
RUNTIME_DATA_DIR = None

# File used to remember who requested a bot restart across process restarts. Keep this
# outside /tmp when systemd PrivateTmp=true is enabled.
RESTART_NOTIFICATION_FILE = 'data/envsbot_restart_notification.json'

# Optional external command used by ,bot shutdown. Leave empty to perform a clean
# internal exit. With systemd, use Restart=on-failure so ,bot restart (exit code 75)
# restarts while a clean shutdown remains stopped.
STOP_CMD = []

# Stop cmd timeout seconds.
STOP_CMD_TIMEOUT_SECONDS = 10.0

# Command execution guardrails. Slow commands are logged; timed-out commands return a
# friendly error and the traceback stays in the log.
COMMAND_TIMEOUT_SECONDS = 30

# Command slow log seconds.
COMMAND_SLOW_LOG_SECONDS = 2.0

# Default paging behavior for commands supporting [page|last|all]. "all" shows the
# full list by default. A positive integer, e.g. 20, shows page 1 with that many
# entries unless the user explicitly asks for all/last/page.
DEFAULT_PAGINATION = 'all'

# SQLite connection busy timeout in milliseconds. Applied when the database connection
# is opened.
# Startup-only: restart envsbot after changing this value.
DATABASE_BUSY_TIMEOUT_MS = 5000

# Whether SQLite WAL journal mode is enabled. Applied when the database connection is
# opened.
# Startup-only: restart envsbot after changing this value.
DATABASE_WAL_ENABLED = False

# Grace period for shutdown/restart DB cleanup. Keep this larger than the internal
# flush wait so the SQLite connection can close cleanly.
DATABASE_SHUTDOWN_TIMEOUT_SECONDS = 15.0

# Periodic low-impact SQLite maintenance. The worker runs PRAGMA optimize, checkpoints
# WAL when enabled and prunes old aggregate command statistics.
# Startup-only: restart envsbot after changing this value.
DATABASE_MAINTENANCE_INTERVAL_SECONDS = 21600

# Create a consistent SQLite snapshot before applying pending schema migrations.
# Startup-only: restart envsbot after changing this value.
DATABASE_BACKUP_BEFORE_MIGRATE = True

# Command usage retention days.
COMMAND_USAGE_RETENTION_DAYS = 365

# Event-loop monitor and native systemd watchdog integration. With the bundled service
# unit, a process that is alive but no longer responsive is restarted.
# Startup-only: restart envsbot after changing this value.
WATCHDOG_ENABLED = True

# Watchdog interval seconds.
# Startup-only: restart envsbot after changing this value.
WATCHDOG_INTERVAL_SECONDS = 20.0

# Watchdog lag warning seconds.
# Startup-only: restart envsbot after changing this value.
WATCHDOG_LAG_WARNING_SECONDS = 2.0

# Watchdog lag failure seconds.
# Startup-only: restart envsbot after changing this value.
WATCHDOG_LAG_FAILURE_SECONDS = 30.0

# Automatic restart/backoff for protected long-running plugin workers. This many
# automatic restarts are allowed in one failure streak; if the restarted worker fails
# again, the circuit opens and an admin is notified.
# Startup-only: restart envsbot after changing this value.
TASK_RESTART_MAX_ATTEMPTS = 5

# Task restart initial seconds.
# Startup-only: restart envsbot after changing this value.
TASK_RESTART_INITIAL_SECONDS = 5.0

# Task restart max seconds.
# Startup-only: restart envsbot after changing this value.
TASK_RESTART_MAX_SECONDS = 300.0

# Task restart reset seconds.
# Startup-only: restart envsbot after changing this value.
TASK_RESTART_RESET_SECONDS = 900.0

# Heartbeats older than this are reported by `,tasks stale`; values below 60 seconds
# are rejected.
TASK_STALE_AFTER_SECONDS = 3600.0


# ================= BACKUPS =================

# Keep this many verified pre-migration SQLite snapshots.
DATABASE_MIGRATION_BACKUP_KEEP = 5

# Also prune pre-migration SQLite snapshots older than this many days. 0 disables age-
# based pruning.
DATABASE_MIGRATION_BACKUP_RETENTION_DAYS = 90

# Managed ZIP backups are written here. The default is ignored by git. Archives
# include bot.db, config.py, vcard.py, chat_slang.csv, slang_additions.csv and
# slang_removals.csv when present.
BACKUP_DIR = 'data/backups'

# Keep this many managed backup archives after creating a new one.
BACKUP_KEEP = 15

# Also prune managed backup archives older than this many days. Set to 0 to disable
# age-based pruning.
BACKUP_RETENTION_DAYS = 0

# Create a managed backup once during each bot process start. This also covers service
# restarts, because a restart starts a fresh bot process.
BACKUP_ON_START = True

# Create an automatic managed backup this many hours after the newest managed backup.
# Set to 0 to disable periodic backups and the stale-backup age alert. When enabled,
# this value should be lower than ADMIN_ALERT_BACKUP_MAX_AGE_HOURS so a scheduled
# backup is created before the stale-backup alert threshold.
# Startup-only: restart envsbot after changing this value.
BACKUP_INTERVAL_HOURS = 24

# Restore each newly created backup into a temporary directory and run SQLite
# integrity_check before accepting it.
BACKUP_SMOKE_TEST_ON_CREATE = True


# ================= PERSISTENT OUTBOX =================

# Persistent outbound delivery queue. Failed RSS, reminder and admin-report messages
# are stored in SQLite and retried across reconnects/restarts.
# Startup-only: restart envsbot after changing this value.
OUTBOX_ENABLED = True

# Outbox poll seconds.
# Startup-only: restart envsbot after changing this value.
OUTBOX_POLL_SECONDS = 5.0

# Outbox batch size.
# Startup-only: restart envsbot after changing this value.
OUTBOX_BATCH_SIZE = 20

# Outbox max attempts.
# Startup-only: restart envsbot after changing this value.
OUTBOX_MAX_ATTEMPTS = 12

# Outbox retry initial seconds.
# Startup-only: restart envsbot after changing this value.
OUTBOX_RETRY_INITIAL_SECONDS = 30

# Outbox retry max seconds.
# Startup-only: restart envsbot after changing this value.
OUTBOX_RETRY_MAX_SECONDS = 1800

# Outbox inflight timeout seconds.
# Startup-only: restart envsbot after changing this value.
OUTBOX_INFLIGHT_TIMEOUT_SECONDS = 300

# Hard growth limits for long outages or broken destinations.
# Startup-only: restart envsbot after changing this value.
OUTBOX_MAX_PENDING = 10000

# Outbox max bytes.
# Startup-only: restart envsbot after changing this value.
OUTBOX_MAX_BYTES = 52428800

# Outbox max per destination.
# Startup-only: restart envsbot after changing this value.
OUTBOX_MAX_PER_DESTINATION = 1000

# Outbox max per category.
# Startup-only: restart envsbot after changing this value.
OUTBOX_MAX_PER_CATEGORY = 5000

# Dead letters older than this are pruned by database maintenance. 0 disables age-
# based pruning.
OUTBOX_DEAD_RETENTION_DAYS = 30


# ================= IMMEDIATE ADMIN ALERTS =================

# Send deduplicated state-change warnings to the same destination used by the admin
# report. Ongoing incidents are repeated only after the cooldown.
# Startup-only: restart envsbot after changing this value.
ADMIN_ALERTS_ENABLED = True

# Admin alert interval seconds.
# Startup-only: restart envsbot after changing this value.
ADMIN_ALERT_INTERVAL_SECONDS = 60

# Admin alert cooldown seconds.
# Startup-only: restart envsbot after changing this value.
ADMIN_ALERT_COOLDOWN_SECONDS = 3600

# Admin alert outbox oldest seconds.
ADMIN_ALERT_OUTBOX_OLDEST_SECONDS = 1800

# Admin alert room missing seconds.
ADMIN_ALERT_ROOM_MISSING_SECONDS = 1800

# Alert when the newest managed backup is older than this many hours while periodic
# managed backups are enabled. BACKUP_INTERVAL_HOURS = 0 disables the stale-age alert.
ADMIN_ALERT_BACKUP_MAX_AGE_HOURS = 36

# Admin alert idlerpg export failures.
ADMIN_ALERT_IDLERPG_EXPORT_FAILURES = 3


# ================= DAILY ADMIN REPORT =================

# Optional compact XMPP-only health report. No HTTP metrics endpoint is opened.
ADMIN_REPORT_ENABLED = False

# "daily" always sends; "problems_only" skips a scheduled report when the immediate
# alert manager currently has no active incident.
ADMIN_REPORT_MODE = 'daily'

# Empty uses VERSION_CHECK_NOTIFY_JID, ROOM_INVITE_NOTIFY_JID or OWNER.
ADMIN_REPORT_JID = ''

# Admin report time.
ADMIN_REPORT_TIME = '08:00'

# Empty uses TIMEZONE.
ADMIN_REPORT_TIMEZONE = ''

# Optionally extract the newest backup into a temporary directory and run an SQLite
# integrity check on the contained bot.db while building the report.
ADMIN_REPORT_BACKUP_SMOKE_TEST = False


# ================= MESSAGE CACHE =================

# Number of recent messages retained per room or private conversation. The cache is
# shared by all plugins, stored in SQLite and restored on restart. Message bodies are
# therefore persisted in the bot database and included in normal database backups.
# Lower this value if less retained history is wanted.
# Startup-only: restart envsbot after changing this value.
MESSAGE_CACHE_SIZE = 100

# Remove cached messages older than this many days. Set 0 to disable age pruning.
# Startup-only: restart envsbot after changing this value.
MESSAGE_CACHE_MAX_AGE_DAYS = 30


# ================= USER TRACKING =================

# Maximum number of clean user rows kept in the read-through cache. Dirty entries are
# never evicted.
# Startup-only: restart envsbot after changing this value.
USER_CACHE_MAX_ENTRIES = 5000

# Maximum number of clean per-user runtime JSON blobs kept in memory. Dirty entries
# and the global plugin runtime blob are never evicted.
# Startup-only: restart envsbot after changing this value.
USER_RUNTIME_CACHE_MAX_ENTRIES = 5000

# Evict clean user/runtime cache entries that have not been accessed for this many
# seconds. 0 disables TTL eviction.
# Startup-only: restart envsbot after changing this value.
USER_CACHE_TTL_SECONDS = 86400

# Minimum interval between automatic cache-prune passes.
# Startup-only: restart envsbot after changing this value.
USER_CACHE_PRUNE_INTERVAL_SECONDS = 300

# Users.
USERS = {
    # Maximum remembered nicknames per room for one tracked user.
    'max_room_nicks': 5,
}


# ================= COMMAND RATE LIMITS =================

# Protect the bot from command spam. Limits are in-memory and reset on restart.
COMMAND_RATE_LIMIT_ENABLED = True

# Command rate limit capacity.
COMMAND_RATE_LIMIT_CAPACITY = 4

# Command rate limit refill amount.
COMMAND_RATE_LIMIT_REFILL_AMOUNT = 1

# Command rate limit refill interval seconds.
COMMAND_RATE_LIMIT_REFILL_INTERVAL_SECONDS = 0.5

# Command rate limit deny window seconds.
COMMAND_RATE_LIMIT_DENY_WINDOW_SECONDS = 10.0

# Command rate limit deny threshold.
COMMAND_RATE_LIMIT_DENY_THRESHOLD = 6

# Command rate limit base block seconds.
COMMAND_RATE_LIMIT_BASE_BLOCK_SECONDS = 30.0

# Command rate limit backoff multiplier.
COMMAND_RATE_LIMIT_BACKOFF_MULTIPLIER = 2.0

# Command rate limit max block seconds.
COMMAND_RATE_LIMIT_MAX_BLOCK_SECONDS = 3600.0

# Command rate limit notify cooldown seconds.
COMMAND_RATE_LIMIT_NOTIFY_COOLDOWN_SECONDS = 10.0

# Prune inactive command rate-limit client state after this many seconds. Set 0 to
# disable TTL pruning; the hard client limit still applies.
COMMAND_RATE_LIMIT_IDLE_TTL_SECONDS = 3600

# Minimum interval between opportunistic command rate-limit idle-prune passes.
COMMAND_RATE_LIMIT_PRUNE_INTERVAL_SECONDS = 60

# Users with this role or better bypass command rate limits. Use one of: owner,
# superadmin, admin, moderator, trusted, user, new, none.
COMMAND_RATE_LIMIT_BYPASS_ROLE = 'moderator'


# ================= HTTP DEFAULTS =================

# Generic HTTP timeout used by plugins unless a plugin-specific value is set below.
HTTP_TIMEOUT_SECONDS = 8

# Http max redirects.
HTTP_MAX_REDIRECTS = 5

# Http max read bytes.
HTTP_MAX_READ_BYTES = 1048576

# Default HTTP User-Agent. The {version} token is expanded automatically to the
# running envsbot version, so operators do not need to update it for each release.
HTTP_USER_AGENT = 'envsbot/{version} (https://github.com/envs-net/envsbot)'

# Safety guard for user-supplied URLs fetched by RSS and URL title checks. Keep False
# for normal public bots. Set True only for trusted/private rooms.
ALLOW_PRIVATE_FETCH_URLS = False


# ================= VCARD / AVATAR =================

# Bot avatar. Set AVATAR_PATH = None to disable avatar publishing. The default avatar
# is bundled with envsbot; put custom avatars below data/.
AVATAR_PATH = 'avatar.jpg'

# Avatar type.
AVATAR_TYPE = 'image/jpeg'

# Timeout for vCard fetches made by vcard, weather and birthday helpers.
VCARD_FETCH_TIMEOUT_SECONDS = 10


# ================= RELEASE UPDATE CHECK =================

# Manual ,checkupdate works even when periodic checks are disabled.
VERSION_CHECK_ENABLED = False

# Version check interval.
VERSION_CHECK_INTERVAL = 3600

# Version check url.
VERSION_CHECK_URL = 'https://github.com/envs-net/envsbot/releases/latest'

# Empty = notify OWNER. If this is a MUC room, the bot joins it before sending.
VERSION_CHECK_NOTIFY_JID = ''

# Updatecheck timeout seconds.
UPDATECHECK_TIMEOUT_SECONDS = 15


# ================= ROOM INVITES =================

# When enabled, incoming MUC invites are stored as pending room invites and announced
# to ROOM_INVITE_NOTIFY_JID, VERSION_CHECK_NOTIFY_JID, or OWNER. The bot does not join
# the invited room until an admin accepts the invite.
ROOM_INVITES_ENABLED = True

# Room invite notify jid.
ROOM_INVITE_NOTIFY_JID = ''

# Pending room invites older than this many days are expired automatically. Set to 0
# to keep pending invites until accepted/declined/cleanup.
ROOM_INVITE_MAX_AGE_DAYS = 30


# ================= ROOM PLUGIN DEFAULTS =================

# Default room feature state used for newly added rooms and for ,rooms
# set_plugin_defaults. Missing keys keep their internal fallback. Unknown keys are
# ignored with a warning. Per-room changes are still stored in the database and can be
# managed with ,rooms enable/disable.
ROOM_PLUGIN_DEFAULTS = {'birthday_notify': False,
 'dice': True,
 'ducks': False,
 'help': False,
 'information': True,
 'karma': False,
 'idlerpg': False,
 'pin': True,
 'poll': False,
 'presence': True,
 'reminder': True,
 'sed': True,
 'tell': True,
 'tools': True,
 'translate': True,
 'urlcheck': True,
 'vcard': True,
 'weather': True,
 'xkcd': False,
 'xmpp': True}


# ================= URL CHECK =================

# Suppress repeated output for the same URL in the same room for this many seconds.
URLCHECK_WAIT_SECONDS = 120

# URL fetch limits for title/description extraction and YouTube metadata.
URLCHECK_FETCH_TIMEOUT_SECONDS = 8

# Urlcheck max redirects.
URLCHECK_MAX_REDIRECTS = 5

# Urlcheck max read bytes.
URLCHECK_MAX_READ_BYTES = 65536

# URL-check User-Agent. The {version} token is expanded automatically; set a custom
# value only when required.
URLCHECK_USER_AGENT = 'envsbot/{version} (https://github.com/envs-net/envsbot)'

# YouTube Data API key for richer URL metadata lookups. None disables YouTube API data
# but regular URL title checks still work.
YOUTUBE_API_KEY = None


# ================= RSS / ATOM =================

# Default global feed check interval in seconds.
RSS_GLOBAL_QUERY_INTERVAL = 1200

# Number of existing entries to show when a feed is newly added. Set to 0 to suppress
# the initial history replay while still starting from the feed snapshot seen when the
# subscription is created.
MAX_NEW_FEED_ENTRIES = 5

# Maximum personal DM subscriptions for trusted users. Moderators and higher are
# unlimited. Set to 0 to disable trusted-user DM subscriptions.
RSS_TRUSTED_MAX_FEEDS = 10

# Number of entries shown on one paginated RSS list page.
RSS_LIST_PAGE_SIZE = 10

# Maximum number of new entries posted per regular feed poll. If a very active feed
# publishes more than this between two checks, older unseen entries are skipped and
# the newest item is remembered as seen.
RSS_MAX_ENTRIES_PER_POLL = 10

# Retry/backoff behavior for failing feeds. First failure retries after 5 minutes,
# second after 10 minutes, then grows exponentially up to the maximum delay.
RSS_RETRY_INITIAL_DELAY = 300

# Rss retry backoff multiplier.
RSS_RETRY_BACKOFF_MULTIPLIER = 2.0

# Rss max backoff time.
RSS_MAX_BACKOFF_TIME = 3600

# A feed is considered broken in ,rss broken after this many consecutive errors.
RSS_BROKEN_ERROR_THRESHOLD = 3

# Duplicate title/description detection threshold, 0 < value <= 1.
RSS_SIMILARITY_THRESHOLD = 0.8

# RSS User-Agent. The {version} token is expanded automatically; set a custom value
# only when required.
RSS_USER_AGENT = 'envsbot/{version} (https://github.com/envs-net/envsbot)'

# Explicit RSS HTTP fetch limits.
RSS_FETCH_TIMEOUT_SECONDS = 8

# Spread initial requests to the same host across a few seconds after startup. This
# avoids a burst when many feeds are hosted by one slower service.
RSS_STARTUP_STAGGER_SECONDS = 2.0

# Rss max redirects.
RSS_MAX_REDIRECTS = 5

# Rss max read bytes.
RSS_MAX_READ_BYTES = 1048576

# Maximum length of an RSS message template configured with ,rss template.
RSS_TEMPLATE_MAX_LENGTH = 1000


# ================= BIRTHDAY NOTIFY =================

# Cache positive and negative vCard BDAY results for this many seconds.
BIRTHDAY_CACHE_TTL_SECONDS = 43200

# Delay first scan after startup so room joins and presence can settle.
BIRTHDAY_INITIAL_SCAN_DELAY_SECONDS = 10

# Periodic loop interval in seconds. The expensive full scan still only runs once per
# day.
BIRTHDAY_CHECK_INTERVAL_SECONDS = 3600


# ================= REMINDERS =================

# Reminder enabled.
REMINDER_ENABLED = True

# Reminder max age days.
REMINDER_MAX_AGE_DAYS = 365

# Fallback timezone for absolute reminder dates when the user has no TIMEZONE set in
# their bot profile. Explicit command timezones such as CEST, CET, UTC, Europe/Berlin
# or +02:00 override this per reminder. Use an IANA timezone such as Europe/Berlin
# when you want automatic DST handling; CET/CEST are treated as explicit fixed
# offsets.
REMINDER_DEFAULT_TIMEZONE = 'UTC'


# ================= DUCK GAME =================

# Global defaults for rooms with the Ducks plugin enabled. Room owners/admins and bot
# moderators can override gameplay pacing for one room through a MUC private chat with
# `,duck config`; see docs/plugins/ducks.md for examples.
DUCKS = {
    # Minimum room messages before duck spawning becomes eligible.
    'min_messages': 150,
    # Maximum room-message threshold before a duck spawn roll.
    'max_messages': 500,
    # Chance denominator/weight used when an eligible duck spawn is rolled.
    'spawn_chance': 20,
    # Maximum ducks spawned per room and day.
    'max_ducks_per_day': 3,
    # Seconds before an uncaught duck expires; zero keeps the configured no-timeout
    # behavior.
    'timeout': 0,
    # Whether bot commands count toward duck spawn message thresholds.
    'count_commands': False,
    # Persist duck state after this many relevant state updates.
    'state_save_every': 1,
}


# ================= IDLERPG =================

# Classic IRC-style IdleRPG adapted for XMPP MUCs. Players level up by staying online
# and idle. Normal room messages add penalty time to the player's timer. See
# docs/idlerpg.md for details.
IDLERPG = {
    # Game loop interval in seconds.
    'tick_seconds': 60,
    # Base value for the IdleRPG level timer formula.
    'rp_base': 600,
    # Exponent step used by the IdleRPG level timer formula.
    'rp_step': 1.16,
    # Exponent step used to scale message/logout penalties by level.
    'penalty_step': 1.14,
    # Base multiplier for normal-message penalties.
    'message_penalty': 1,
    # Base logout penalty.
    'logout_penalty': 20,
    # Reconnect grace period before applying a logout penalty.
    'logout_grace_seconds': 300,
    # Maximum accumulated penalty; zero keeps the existing no-cap behavior.
    'max_penalty': 604800,
    # Whether bot command messages also count as IdleRPG activity penalties.
    'count_command_messages': False,
    # Default page size for IdleRPG list commands.
    'page_size': 10,
    # IdleRPG map width.
    'map_x': 500,
    # IdleRPG map height.
    'map_y': 500,
    # Grid movement steps per simulated second.
    'map_step_per_second': 1,
    # Legacy alias for map_step_per_second.
    'map_step_per_tick': 1,
    # Enable battles triggered by players sharing a map grid position.
    'grid_battle_enabled': True,
    # Seconds between directed map steps for grid-quest participants.
    'quest_grid_step_seconds': 30,
    # Minimum character level for automatic quest selection.
    'quest_min_level': 40,
    # Minimum online time required for automatic quest selection.
    'quest_min_online_seconds': 36000,
    # Delay between automatic quest opportunities.
    'quest_interval': 21600,
    # Maximum automatically started quests per UTC day; zero means unlimited.
    'quest_max_per_day': 2,
    # Minimum grid-quest deadline.
    'quest_min_duration': 43200,
    # Maximum grid-quest deadline.
    'quest_max_duration': 86400,
    # Enable grid-route quests.
    'quest_grid_enabled': True,
    # Relative selection weight for grid quests.
    'quest_grid_weight': 0.5,
    # Minimum route points for a grid quest.
    'quest_grid_min_points': 2,
    # Maximum route points for a grid quest.
    'quest_grid_max_points': 3,
    # Enable time-survival quests.
    'quest_time_enabled': True,
    # Relative selection weight for time quests.
    'quest_time_weight': 0.5,
    # Minimum time-quest duration.
    'quest_time_min_duration': 43200,
    # Maximum time-quest duration.
    'quest_time_max_duration': 86400,
    # Chance of a random IdleRPG event on each eligible tick.
    'event_chance': 0.01,
    # Relative random-event weight for ordinary item events.
    'item_chance': 0.2,
    # Relative random-event weight for battles.
    'battle_event_weight': 0.55,
    # Relative random-event weight for team battles.
    'team_battle_event_weight': 0.08,
    # Relative random-event weight for boss battles.
    'boss_event_weight': 0.06,
    # Relative random-event weight for item upgrades.
    'item_event_weight': 0.15,
    # Relative random-event weight for item damage.
    'item_damage_event_weight': 0.08,
    # Relative random-event weight for item stealing.
    'item_steal_event_weight': 0.04,
    # Relative random-event weight for alignment events.
    'alignment_event_weight': 0.1,
    # Critical-strike chance for neutral players.
    'critical_strike_chance': 0.02857142857142857,
    # Critical-strike chance for good players.
    'critical_strike_chance_good': 0.02,
    # Critical-strike chance for evil players.
    'critical_strike_chance_evil': 0.05,
    # Chance of an item being stolen/dropped in an eligible battle.
    'item_drop_chance': 0.02,
    # Level-up battle chance below level 25.
    'level_battle_chance_below_25': 0.25,
    # Level-up battle chance from level 25 onward.
    'level_battle_chance_at_25': 1.0,
    # Minimum TTL reduction percentage for a battle win.
    'battle_win_min_percent': 7,
    # Minimum TTL penalty percentage for a battle loss.
    'battle_loss_min_percent': 7,
    # Minimum critical-strike percentage.
    'critical_min_percent': 5,
    # Maximum critical-strike percentage.
    'critical_max_percent': 25,
    # Minimum godsend percentage.
    'godsend_min_percent': 5,
    # Maximum godsend percentage.
    'godsend_max_percent': 12,
    # Minimum calamity percentage.
    'calamity_min_percent': 5,
    # Maximum calamity percentage.
    'calamity_max_percent': 12,
    # Alignment-based bonus percentage.
    'alignment_bonus_percent': 7,
    # Quest reward percentage.
    'quest_reward_percent': 25,
    # Team-battle reward/penalty percentage.
    'team_battle_percent': 20,
    # Minimum players selected for a boss encounter.
    'boss_min_players': 3,
    # Maximum players selected for a boss encounter.
    'boss_max_players': 5,
    # Minimum level for boss participants.
    'boss_min_level': 10,
    # Boss victory reward percentage.
    'boss_reward_percent': 12,
    # Boss defeat penalty percentage.
    'boss_loss_percent': 4,
    # Minimum boss power multiplier.
    'boss_power_min_factor': 0.75,
    # Maximum boss power multiplier.
    'boss_power_max_factor': 1.25,
    # Maximum map distance for a manual duel.
    'manual_duel_max_distance': 10,
    # Cooldown applied to both manual duelists.
    'manual_duel_cooldown_seconds': 3600,
    # Enable unique themed IdleRPG items.
    'unique_items_enabled': True,
    # Minimum level for unique items.
    'unique_item_min_level': 25,
    # Chance of awarding an eligible unique item.
    'unique_item_chance': 0.025,
    # Announce player logins in the game room.
    'announce_login': True,
    # Interval between automatic top-player announcements.
    'announce_top_interval': 21600,
    # Number of players included in top-player announcements.
    'announce_top_limit': 5,
    # Allow IdleRPG to update the MUC subject/topic.
    'update_room_topic': False,
    # Minimum interval between IdleRPG topic updates.
    'topic_update_interval': 14400,
    # Optional custom prefix for IdleRPG room topics.
    'topic_custom_text': '',
    # Minimum level for level-gated reward badges.
    'level_reward_min_level': 50,
    # Gate long-term achievements by season age.
    'season_achievement_gates_enabled': True,
    # Number of recent events retained in the in-memory room cache.
    'event_log_limit': 200,
    # Database event-retention age used by maintenance.
    'event_retention_days': 90,
    # Number of recent events exported in the compact website feed.
    'export_event_limit': 50,
    # Export the complete active-season event history from SQLite.
    'export_full_season_events': False,
    # Maximum events per append-friendly full-season export chunk.
    'export_season_event_chunk_size': 1000,
    # Enable public IdleRPG JSON exports.
    'export_enabled': True,
    # Minimum interval between automatic public exports; zero exports after every state
    # change.
    'export_interval_seconds': 300,
    # Filesystem path for public IdleRPG JSON exports.
    'export_path': 'data/idlerpg',
    # Public URL corresponding to the exported JSON data.
    'export_public_base_url': '',
    # Human-facing IdleRPG website root; may be derived from the export URL.
    'website_public_base_url': '',
    # Maximum leaderboard entries in public exports.
    'export_top_limit': 50,
    # Enable automatic season timing/rollover.
    'season_enabled': False,
    # Automatic season duration in days; zero means manual/endless.
    'season_duration_days': 90,
    # Reset player progression when an automatic season rolls over.
    'season_reset_on_rollover': False,
    # Number of completed seasons retained in the Hall of Fame.
    'season_hof_size': 10,
}


# ================= SED CORRECTIONS =================

# Sed regex timeout.
SED_REGEX_TIMEOUT = 1.0

# Sed max pattern length.
SED_MAX_PATTERN_LENGTH = 256

# Sed max replacement length.
SED_MAX_REPLACEMENT_LENGTH = 1000

# Sed max input length.
SED_MAX_INPUT_LENGTH = 5000

# Sed max output length.
SED_MAX_OUTPUT_LENGTH = 8000


# ================= POLLS =================

# Poll max options.
POLL_MAX_OPTIONS = 10

# Poll max question len.
POLL_MAX_QUESTION_LEN = 200

# Poll max option len.
POLL_MAX_OPTION_LEN = 100

# Poll max history per room.
POLL_MAX_HISTORY_PER_ROOM = 50

# Poll default multi max choices.
POLL_DEFAULT_MULTI_MAX_CHOICES = 3


# ================= PINS =================

# Pin page size.
PIN_PAGE_SIZE = 10


# ================= TRANSLATE =================

# Translate uses the same public Google Translate endpoint as translate. No API key is
# required, but the endpoint is unofficial and may change. Set TRANSLATE_TO to a
# language code such as "de" to allow `,tr` for replies and `,tr text` for direct
# text. None keeps the target argument mandatory.
TRANSLATE_FROM = 'auto'

# Translate to.
TRANSLATE_TO = None

# Translate timeout seconds.
TRANSLATE_TIMEOUT_SECONDS = 8

# Translate max input length.
TRANSLATE_MAX_INPUT_LENGTH = 2000

# Translate max output length.
TRANSLATE_MAX_OUTPUT_LENGTH = 6000

# Translate max response bytes.
TRANSLATE_MAX_RESPONSE_BYTES = 262144


# ================= KARMA / TELL =================

# Karma delay seconds.
KARMA_DELAY_SECONDS = 60

# Tell delivery delay seconds.
TELL_DELIVERY_DELAY_SECONDS = 5


# ================= XKCD =================

# Xkcd check interval.
XKCD_CHECK_INTERVAL = 3600

# Xkcd index start delay seconds.
XKCD_INDEX_START_DELAY_SECONDS = 30

# Xkcd index request delay seconds.
XKCD_INDEX_REQUEST_DELAY_SECONDS = 0.15

# Xkcd http timeout.
XKCD_HTTP_TIMEOUT = 10
