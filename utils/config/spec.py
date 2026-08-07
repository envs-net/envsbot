"""Declarative configuration schema for envsbot.

Every top-level setting is described here once. Defaults, accepted types, Python
config names and startup/reload behavior are derived from this schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MISSING = object()

@dataclass(frozen=True)
class ConfigField:
    default: Any
    python_key: str
    accepted_type: type | tuple[type, ...]
    startup_only: bool = False
    required: bool = False
    minimum: float | int | None = None
    maximum: float | int | None = None
    minimum_exclusive: bool = False
    choices: tuple[str, ...] = ()
    allow_empty: bool = False
    description: str = ""

CONFIG_FIELDS: dict[str, ConfigField] = {
    'jid': ConfigField(MISSING, 'JID', str, startup_only=True, required=True),
    'password': ConfigField(MISSING, 'PASSWORD', str, startup_only=True, required=True),
    'nick': ConfigField(MISSING, 'NICK', str, required=True),
    'resource': ConfigField(None, 'RESOURCE', str, startup_only=True),
    'owner': ConfigField(MISSING, 'OWNER', str, required=True),
    'admins': ConfigField(MISSING, 'ADMINS', list),
    'prefix': ConfigField(',', 'COMMAND_PREFIX', str),
    'loglevel': ConfigField('INFO', 'LOG_LEVEL', str),
    'db': ConfigField('bot.db', 'DB_FILE', str, startup_only=True),
    'restart_notification_file': ConfigField('data/envsbot_restart_notification.json', 'RESTART_NOTIFICATION_FILE', str),
    'command_timeout_seconds': ConfigField(30, 'COMMAND_TIMEOUT_SECONDS', (int, float)),
    'command_slow_log_seconds': ConfigField(2.0, 'COMMAND_SLOW_LOG_SECONDS', (int, float)),
    'database_busy_timeout_ms': ConfigField(5000, 'DATABASE_BUSY_TIMEOUT_MS', int),
    'database_wal_enabled': ConfigField(False, 'DATABASE_WAL_ENABLED', bool),
    'database_shutdown_timeout_seconds': ConfigField(15.0, 'DATABASE_SHUTDOWN_TIMEOUT_SECONDS', (int, float)),
    'message_cache_size': ConfigField(100, 'MESSAGE_CACHE_SIZE', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'message_cache_max_age_days': ConfigField(30, 'MESSAGE_CACHE_MAX_AGE_DAYS', int, startup_only=True, minimum=0),
    'default_pagination': ConfigField('all', 'DEFAULT_PAGINATION', (str, int)),
    'backup_dir': ConfigField('data/backups', 'BACKUP_DIR', str),
    'backup_keep': ConfigField(15, 'BACKUP_KEEP', int, minimum=0, minimum_exclusive=True),
    'backup_retention_days': ConfigField(0, 'BACKUP_RETENTION_DAYS', int),
    'backup_on_start': ConfigField(True, 'BACKUP_ON_START', bool),
    'command_rate_limit_enabled': ConfigField(True, 'COMMAND_RATE_LIMIT_ENABLED', bool),
    'command_rate_limit_capacity': ConfigField(4, 'COMMAND_RATE_LIMIT_CAPACITY', int),
    'command_rate_limit_refill_amount': ConfigField(1, 'COMMAND_RATE_LIMIT_REFILL_AMOUNT', int),
    'command_rate_limit_refill_interval_seconds': ConfigField(0.5, 'COMMAND_RATE_LIMIT_REFILL_INTERVAL_SECONDS', (int, float)),
    'command_rate_limit_deny_window_seconds': ConfigField(10.0, 'COMMAND_RATE_LIMIT_DENY_WINDOW_SECONDS', (int, float)),
    'command_rate_limit_deny_threshold': ConfigField(6, 'COMMAND_RATE_LIMIT_DENY_THRESHOLD', int),
    'command_rate_limit_base_block_seconds': ConfigField(30.0, 'COMMAND_RATE_LIMIT_BASE_BLOCK_SECONDS', (int, float)),
    'command_rate_limit_backoff_multiplier': ConfigField(2.0, 'COMMAND_RATE_LIMIT_BACKOFF_MULTIPLIER', (int, float)),
    'command_rate_limit_max_block_seconds': ConfigField(3600.0, 'COMMAND_RATE_LIMIT_MAX_BLOCK_SECONDS', (int, float)),
    'command_rate_limit_notify_cooldown_seconds': ConfigField(10.0, 'COMMAND_RATE_LIMIT_NOTIFY_COOLDOWN_SECONDS', (int, float)),
    'command_rate_limit_bypass_role': ConfigField('moderator', 'COMMAND_RATE_LIMIT_BYPASS_ROLE', str),
    'stop_cmd': ConfigField([], 'STOP_CMD', list),
    'stop_cmd_timeout_seconds': ConfigField(10.0, 'STOP_CMD_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True),
    'avatar': ConfigField(MISSING, 'AVATAR_PATH', str),
    'avatar_type': ConfigField(MISSING, 'AVATAR_TYPE', str),
    'timezone': ConfigField(MISSING, 'TIMEZONE', str),
    'host': ConfigField(None, 'CONNECT_HOST', str, startup_only=True),
    'port': ConfigField(5222, 'CONNECT_PORT', int, startup_only=True, minimum=1, maximum=65535),
    'direct_tls': ConfigField(False, 'CONNECT_DIRECT_TLS', bool, startup_only=True),
    'http_timeout_seconds': ConfigField(8, 'HTTP_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True),
    'http_max_redirects': ConfigField(5, 'HTTP_MAX_REDIRECTS', int, minimum=0, minimum_exclusive=True),
    'http_max_read_bytes': ConfigField(1048576, 'HTTP_MAX_READ_BYTES', int, minimum=0, minimum_exclusive=True),
    'http_user_agent': ConfigField('Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)', 'HTTP_USER_AGENT', str),
    'allow_private_fetch_urls': ConfigField(False, 'ALLOW_PRIVATE_FETCH_URLS', bool),
    'xmpp_query_timeout_seconds': ConfigField(8, 'XMPP_QUERY_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True),
    'xmpp_compliance_max_read_bytes': ConfigField(262144, 'XMPP_COMPLIANCE_MAX_READ_BYTES', int),
    'vcard_fetch_timeout_seconds': ConfigField(10, 'VCARD_FETCH_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True),
    'updatecheck_timeout_seconds': ConfigField(15, 'UPDATECHECK_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True),
    'youtube_api_key': ConfigField(MISSING, 'YOUTUBE_API_KEY', str),
    'reminder_enabled': ConfigField(MISSING, 'REMINDER_ENABLED', bool),
    'reminder_max_age_days': ConfigField(MISSING, 'REMINDER_MAX_AGE_DAYS', int, minimum=0, minimum_exclusive=True),
    'reminder_default_timezone': ConfigField('UTC', 'REMINDER_DEFAULT_TIMEZONE', str),
    'rss_global_query_interval': ConfigField(1200, 'RSS_GLOBAL_QUERY_INTERVAL', int, minimum=0, minimum_exclusive=True),
    'max_new_feed_entries': ConfigField(5, 'MAX_NEW_FEED_ENTRIES', int, minimum=0),
    'rss_trusted_max_feeds': ConfigField(10, 'RSS_TRUSTED_MAX_FEEDS', int, minimum=0),
    'rss_list_page_size': ConfigField(10, 'RSS_LIST_PAGE_SIZE', int, minimum=0, minimum_exclusive=True),
    'rss_max_entries_per_poll': ConfigField(10, 'RSS_MAX_ENTRIES_PER_POLL', int, minimum=0, minimum_exclusive=True),
    'rss_retry_initial_delay': ConfigField(300, 'RSS_RETRY_INITIAL_DELAY', int, minimum=0, minimum_exclusive=True),
    'rss_retry_backoff_multiplier': ConfigField(2.0, 'RSS_RETRY_BACKOFF_MULTIPLIER', (int, float), minimum=0, minimum_exclusive=True),
    'rss_max_backoff_time': ConfigField(3600, 'RSS_MAX_BACKOFF_TIME', int, minimum=0, minimum_exclusive=True),
    'rss_broken_error_threshold': ConfigField(3, 'RSS_BROKEN_ERROR_THRESHOLD', int, minimum=0, minimum_exclusive=True),
    'rss_similarity_threshold': ConfigField(0.8, 'RSS_SIMILARITY_THRESHOLD', (int, float), minimum=0, maximum=1, minimum_exclusive=True),
    'rss_user_agent': ConfigField('Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)', 'RSS_USER_AGENT', str),
    'rss_fetch_timeout_seconds': ConfigField(8, 'RSS_FETCH_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True),
    'rss_startup_stagger_seconds': ConfigField(2.0, 'RSS_STARTUP_STAGGER_SECONDS', (int, float), minimum=0),
    'rss_max_redirects': ConfigField(5, 'RSS_MAX_REDIRECTS', int, minimum=0, minimum_exclusive=True),
    'rss_max_read_bytes': ConfigField(1048576, 'RSS_MAX_READ_BYTES', int, minimum=0, minimum_exclusive=True),
    'rss_template_max_length': ConfigField(1000, 'RSS_TEMPLATE_MAX_LENGTH', int, minimum=0, minimum_exclusive=True),
    'urlcheck_wait_seconds': ConfigField(120, 'URLCHECK_WAIT_SECONDS', int, minimum=0, minimum_exclusive=True),
    'urlcheck_fetch_timeout_seconds': ConfigField(8, 'URLCHECK_FETCH_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True),
    'urlcheck_max_redirects': ConfigField(5, 'URLCHECK_MAX_REDIRECTS', int, minimum=0, minimum_exclusive=True),
    'urlcheck_max_read_bytes': ConfigField(65536, 'URLCHECK_MAX_READ_BYTES', int, minimum=0, minimum_exclusive=True),
    'urlcheck_user_agent': ConfigField('Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)', 'URLCHECK_USER_AGENT', str),
    'birthday_cache_ttl_seconds': ConfigField(43200, 'BIRTHDAY_CACHE_TTL_SECONDS', int, minimum=0, minimum_exclusive=True),
    'birthday_initial_scan_delay_seconds': ConfigField(10, 'BIRTHDAY_INITIAL_SCAN_DELAY_SECONDS', int, minimum=0, minimum_exclusive=True),
    'birthday_check_interval_seconds': ConfigField(3600, 'BIRTHDAY_CHECK_INTERVAL_SECONDS', int, minimum=0, minimum_exclusive=True),
    'sed_regex_timeout': ConfigField(1.0, 'SED_REGEX_TIMEOUT', (int, float), minimum=0, minimum_exclusive=True),
    'sed_max_pattern_length': ConfigField(256, 'SED_MAX_PATTERN_LENGTH', int, minimum=0, minimum_exclusive=True),
    'sed_max_replacement_length': ConfigField(1000, 'SED_MAX_REPLACEMENT_LENGTH', int, minimum=0, minimum_exclusive=True),
    'sed_max_input_length': ConfigField(5000, 'SED_MAX_INPUT_LENGTH', int, minimum=0, minimum_exclusive=True),
    'sed_max_output_length': ConfigField(8000, 'SED_MAX_OUTPUT_LENGTH', int, minimum=0, minimum_exclusive=True),
    'poll_max_options': ConfigField(10, 'POLL_MAX_OPTIONS', int, minimum=0, minimum_exclusive=True),
    'poll_max_question_len': ConfigField(200, 'POLL_MAX_QUESTION_LEN', int, minimum=0, minimum_exclusive=True),
    'poll_max_option_len': ConfigField(100, 'POLL_MAX_OPTION_LEN', int, minimum=0, minimum_exclusive=True),
    'poll_max_history_per_room': ConfigField(50, 'POLL_MAX_HISTORY_PER_ROOM', int, minimum=0, minimum_exclusive=True),
    'poll_default_multi_max_choices': ConfigField(3, 'POLL_DEFAULT_MULTI_MAX_CHOICES', int),
    'pin_page_size': ConfigField(10, 'PIN_PAGE_SIZE', int, minimum=0, minimum_exclusive=True),
    'translate_from': ConfigField('auto', 'TRANSLATE_FROM', str),
    'translate_to': ConfigField(None, 'TRANSLATE_TO', str),
    'translate_timeout_seconds': ConfigField(8, 'TRANSLATE_TIMEOUT_SECONDS', (int, float)),
    'translate_max_input_length': ConfigField(2000, 'TRANSLATE_MAX_INPUT_LENGTH', int),
    'translate_max_output_length': ConfigField(6000, 'TRANSLATE_MAX_OUTPUT_LENGTH', int),
    'translate_max_response_bytes': ConfigField(262144, 'TRANSLATE_MAX_RESPONSE_BYTES', int),
    'karma_delay_seconds': ConfigField(60, 'KARMA_DELAY_SECONDS', int, minimum=0, minimum_exclusive=True),
    'tell_delivery_delay_seconds': ConfigField(5, 'TELL_DELIVERY_DELAY_SECONDS', int, minimum=0, minimum_exclusive=True),
    'xkcd_check_interval': ConfigField(3600, 'XKCD_CHECK_INTERVAL', int, minimum=0, minimum_exclusive=True),
    'xkcd_index_start_delay_seconds': ConfigField(30, 'XKCD_INDEX_START_DELAY_SECONDS', int, minimum=0, minimum_exclusive=True),
    'xkcd_index_request_delay_seconds': ConfigField(0.15, 'XKCD_INDEX_REQUEST_DELAY_SECONDS', (int, float), minimum=0, minimum_exclusive=True),
    'xkcd_http_timeout': ConfigField(10, 'XKCD_HTTP_TIMEOUT', (int, float), minimum=0, minimum_exclusive=True),
    'version_check_enabled': ConfigField(False, 'VERSION_CHECK_ENABLED', bool),
    'version_check_interval': ConfigField(3600, 'VERSION_CHECK_INTERVAL', int, minimum=60),
    'version_check_url': ConfigField('https://github.com/envs-net/envsbot/releases/latest', 'VERSION_CHECK_URL', str),
    'version_check_notify_jid': ConfigField(MISSING, 'VERSION_CHECK_NOTIFY_JID', str, allow_empty=True),
    'room_invites_enabled': ConfigField(True, 'ROOM_INVITES_ENABLED', bool),
    'room_invite_notify_jid': ConfigField('', 'ROOM_INVITE_NOTIFY_JID', str, allow_empty=True),
    'room_invite_max_age_days': ConfigField(30, 'ROOM_INVITE_MAX_AGE_DAYS', int),
    'room_plugin_defaults': ConfigField({'birthday_notify': False, 'dice': True, 'ducks': False, 'help': False, 'information': True, 'karma': False, 'idlerpg': False, 'pin': True, 'poll': False, 'presence': True, 'reminder': True, 'sed': True, 'tell': True, 'tools': True, 'translate': True, 'urlcheck': True, 'vcard': True, 'weather': True, 'xkcd': False, 'xmpp': True}, 'ROOM_PLUGIN_DEFAULTS', dict),
    'ducks': ConfigField(MISSING, 'DUCKS', dict),
    'idlerpg': ConfigField(MISSING, 'IDLERPG', dict),
    'users': ConfigField(MISSING, 'USERS', dict),
    'database_maintenance_interval_seconds': ConfigField(21600, 'DATABASE_MAINTENANCE_INTERVAL_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'database_backup_before_migrate': ConfigField(True, 'DATABASE_BACKUP_BEFORE_MIGRATE', bool, startup_only=True),
    'command_usage_retention_days': ConfigField(365, 'COMMAND_USAGE_RETENTION_DAYS', int, minimum=0, minimum_exclusive=True),
    'outbox_enabled': ConfigField(True, 'OUTBOX_ENABLED', bool, startup_only=True),
    'outbox_poll_seconds': ConfigField(5.0, 'OUTBOX_POLL_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True),
    'outbox_batch_size': ConfigField(20, 'OUTBOX_BATCH_SIZE', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'outbox_max_attempts': ConfigField(12, 'OUTBOX_MAX_ATTEMPTS', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'outbox_retry_initial_seconds': ConfigField(30, 'OUTBOX_RETRY_INITIAL_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'outbox_retry_max_seconds': ConfigField(1800, 'OUTBOX_RETRY_MAX_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'outbox_inflight_timeout_seconds': ConfigField(300, 'OUTBOX_INFLIGHT_TIMEOUT_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'outbox_max_pending': ConfigField(10000, 'OUTBOX_MAX_PENDING', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'outbox_max_bytes': ConfigField(52428800, 'OUTBOX_MAX_BYTES', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'outbox_dead_retention_days': ConfigField(30, 'OUTBOX_DEAD_RETENTION_DAYS', int, minimum=0),
    'outbox_max_per_destination': ConfigField(1000, 'OUTBOX_MAX_PER_DESTINATION', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'outbox_max_per_category': ConfigField(5000, 'OUTBOX_MAX_PER_CATEGORY', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'watchdog_enabled': ConfigField(True, 'WATCHDOG_ENABLED', bool, startup_only=True),
    'watchdog_interval_seconds': ConfigField(20.0, 'WATCHDOG_INTERVAL_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True),
    'watchdog_lag_warning_seconds': ConfigField(2.0, 'WATCHDOG_LAG_WARNING_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True),
    'watchdog_lag_failure_seconds': ConfigField(30.0, 'WATCHDOG_LAG_FAILURE_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True),
    'task_restart_max_attempts': ConfigField(5, 'TASK_RESTART_MAX_ATTEMPTS', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'task_restart_initial_seconds': ConfigField(5.0, 'TASK_RESTART_INITIAL_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True),
    'task_restart_max_seconds': ConfigField(300.0, 'TASK_RESTART_MAX_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True),
    'task_restart_reset_seconds': ConfigField(900.0, 'TASK_RESTART_RESET_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True),
    'task_stale_after_seconds': ConfigField(3600.0, 'TASK_STALE_AFTER_SECONDS', (int, float), minimum=0, minimum_exclusive=True),
    'admin_alerts_enabled': ConfigField(True, 'ADMIN_ALERTS_ENABLED', bool, startup_only=True),
    'admin_alert_interval_seconds': ConfigField(60, 'ADMIN_ALERT_INTERVAL_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'admin_alert_cooldown_seconds': ConfigField(3600, 'ADMIN_ALERT_COOLDOWN_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True),
    'admin_alert_outbox_oldest_seconds': ConfigField(1800, 'ADMIN_ALERT_OUTBOX_OLDEST_SECONDS', int, minimum=0, minimum_exclusive=True),
    'admin_alert_room_missing_seconds': ConfigField(1800, 'ADMIN_ALERT_ROOM_MISSING_SECONDS', int, minimum=0, minimum_exclusive=True),
    'admin_alert_backup_max_age_hours': ConfigField(36, 'ADMIN_ALERT_BACKUP_MAX_AGE_HOURS', int, minimum=0, minimum_exclusive=True),
    'admin_alert_idlerpg_export_failures': ConfigField(3, 'ADMIN_ALERT_IDLERPG_EXPORT_FAILURES', int, minimum=0, minimum_exclusive=True),
    'admin_report_enabled': ConfigField(False, 'ADMIN_REPORT_ENABLED', bool),
    'admin_report_mode': ConfigField('daily', 'ADMIN_REPORT_MODE', str, choices=("daily", "problems_only")),
    'admin_report_jid': ConfigField('', 'ADMIN_REPORT_JID', str, allow_empty=True),
    'admin_report_time': ConfigField('08:00', 'ADMIN_REPORT_TIME', str),
    'admin_report_timezone': ConfigField('', 'ADMIN_REPORT_TIMEZONE', str, allow_empty=True),
    'admin_report_backup_smoke_test': ConfigField(False, 'ADMIN_REPORT_BACKUP_SMOKE_TEST', bool),
}

OPERATIONAL_CONFIG_FIELDS = CONFIG_FIELDS


CONFIG_DISPLAY_SECTIONS = (
    (
        "XMPP Account",
        ("JID", "PASSWORD", "NICK", "RESOURCE", "OWNER", "ADMINS"),
    ),
    (
        "Connection",
        (
            "CONNECT_HOST",
            "CONNECT_PORT",
            "CONNECT_DIRECT_TLS",
            "XMPP_QUERY_TIMEOUT_SECONDS",
            "XMPP_COMPLIANCE_MAX_READ_BYTES",
        ),
    ),
    (
        "Bot Runtime",
        (
            "LOG_LEVEL",
            "COMMAND_PREFIX",
            "TIMEZONE",
            "DB_FILE",
            "RESTART_NOTIFICATION_FILE",
            "STOP_CMD",
            "STOP_CMD_TIMEOUT_SECONDS",
            "COMMAND_TIMEOUT_SECONDS",
            "COMMAND_SLOW_LOG_SECONDS",
            "DEFAULT_PAGINATION",
            "DATABASE_BUSY_TIMEOUT_MS",
            "DATABASE_WAL_ENABLED",
            "DATABASE_SHUTDOWN_TIMEOUT_SECONDS",
            "DATABASE_MAINTENANCE_INTERVAL_SECONDS",
            "DATABASE_BACKUP_BEFORE_MIGRATE",
            "COMMAND_USAGE_RETENTION_DAYS",
            "WATCHDOG_ENABLED",
            "WATCHDOG_INTERVAL_SECONDS",
            "WATCHDOG_LAG_WARNING_SECONDS",
            "WATCHDOG_LAG_FAILURE_SECONDS",
            "TASK_RESTART_MAX_ATTEMPTS",
            "TASK_RESTART_INITIAL_SECONDS",
            "TASK_RESTART_MAX_SECONDS",
            "TASK_RESTART_RESET_SECONDS",
            "TASK_STALE_AFTER_SECONDS",
        ),
    ),
    (
        "Persistent Outbox",
        (
            "OUTBOX_ENABLED",
            "OUTBOX_POLL_SECONDS",
            "OUTBOX_BATCH_SIZE",
            "OUTBOX_MAX_ATTEMPTS",
            "OUTBOX_RETRY_INITIAL_SECONDS",
            "OUTBOX_RETRY_MAX_SECONDS",
            "OUTBOX_INFLIGHT_TIMEOUT_SECONDS",
            "OUTBOX_MAX_PENDING",
            "OUTBOX_MAX_BYTES",
            "OUTBOX_MAX_PER_DESTINATION",
            "OUTBOX_MAX_PER_CATEGORY",
            "OUTBOX_DEAD_RETENTION_DAYS",
        ),
    ),
    (
        "Immediate Admin Alerts",
        (
            "ADMIN_ALERTS_ENABLED",
            "ADMIN_ALERT_INTERVAL_SECONDS",
            "ADMIN_ALERT_COOLDOWN_SECONDS",
            "ADMIN_ALERT_OUTBOX_OLDEST_SECONDS",
            "ADMIN_ALERT_ROOM_MISSING_SECONDS",
            "ADMIN_ALERT_BACKUP_MAX_AGE_HOURS",
            "ADMIN_ALERT_IDLERPG_EXPORT_FAILURES",
        ),
    ),
    (
        "Daily Admin Report",
        (
            "ADMIN_REPORT_ENABLED",
            "ADMIN_REPORT_MODE",
            "ADMIN_REPORT_JID",
            "ADMIN_REPORT_TIME",
            "ADMIN_REPORT_TIMEZONE",
            "ADMIN_REPORT_BACKUP_SMOKE_TEST",
        ),
    ),
    (
        "Message Cache",
        ("MESSAGE_CACHE_SIZE", "MESSAGE_CACHE_MAX_AGE_DAYS"),
    ),
    (
        "Backups",
        (
            "BACKUP_DIR",
            "BACKUP_KEEP",
            "BACKUP_RETENTION_DAYS",
            "BACKUP_ON_START",
        ),
    ),
    (
        "Command Rate Limits",
        (
            "COMMAND_RATE_LIMIT_ENABLED",
            "COMMAND_RATE_LIMIT_CAPACITY",
            "COMMAND_RATE_LIMIT_REFILL_AMOUNT",
            "COMMAND_RATE_LIMIT_REFILL_INTERVAL_SECONDS",
            "COMMAND_RATE_LIMIT_DENY_WINDOW_SECONDS",
            "COMMAND_RATE_LIMIT_DENY_THRESHOLD",
            "COMMAND_RATE_LIMIT_BASE_BLOCK_SECONDS",
            "COMMAND_RATE_LIMIT_BACKOFF_MULTIPLIER",
            "COMMAND_RATE_LIMIT_MAX_BLOCK_SECONDS",
            "COMMAND_RATE_LIMIT_NOTIFY_COOLDOWN_SECONDS",
            "COMMAND_RATE_LIMIT_BYPASS_ROLE",
        ),
    ),
    (
        "HTTP Defaults",
        (
            "HTTP_TIMEOUT_SECONDS",
            "HTTP_MAX_REDIRECTS",
            "HTTP_MAX_READ_BYTES",
            "HTTP_USER_AGENT",
            "ALLOW_PRIVATE_FETCH_URLS",
        ),
    ),
    (
        "vCard / Avatar",
        ("AVATAR_PATH", "AVATAR_TYPE", "VCARD_FETCH_TIMEOUT_SECONDS"),
    ),
    (
        "Release Update Check",
        (
            "VERSION_CHECK_ENABLED",
            "VERSION_CHECK_INTERVAL",
            "VERSION_CHECK_URL",
            "VERSION_CHECK_NOTIFY_JID",
            "UPDATECHECK_TIMEOUT_SECONDS",
        ),
    ),
    (
        "Room Invites",
        (
            "ROOM_INVITES_ENABLED",
            "ROOM_INVITE_NOTIFY_JID",
            "ROOM_INVITE_MAX_AGE_DAYS",
        ),
    ),
    (
        "Room Plugin Defaults",
        ("ROOM_PLUGIN_DEFAULTS",),
    ),
    (
        "URL Check",
        (
            "URLCHECK_WAIT_SECONDS",
            "URLCHECK_FETCH_TIMEOUT_SECONDS",
            "URLCHECK_MAX_REDIRECTS",
            "URLCHECK_MAX_READ_BYTES",
            "URLCHECK_USER_AGENT",
            "YOUTUBE_API_KEY",
        ),
    ),
    (
        "RSS / Atom",
        (
            "RSS_GLOBAL_QUERY_INTERVAL",
            "MAX_NEW_FEED_ENTRIES",
            "RSS_TRUSTED_MAX_FEEDS",
            "RSS_LIST_PAGE_SIZE",
            "RSS_MAX_ENTRIES_PER_POLL",
            "RSS_RETRY_INITIAL_DELAY",
            "RSS_RETRY_BACKOFF_MULTIPLIER",
            "RSS_MAX_BACKOFF_TIME",
            "RSS_BROKEN_ERROR_THRESHOLD",
            "RSS_SIMILARITY_THRESHOLD",
            "RSS_USER_AGENT",
            "RSS_FETCH_TIMEOUT_SECONDS",
            "RSS_STARTUP_STAGGER_SECONDS",
            "RSS_MAX_REDIRECTS",
            "RSS_MAX_READ_BYTES",
            "RSS_TEMPLATE_MAX_LENGTH",
        ),
    ),
    (
        "Birthday Notify",
        (
            "BIRTHDAY_CACHE_TTL_SECONDS",
            "BIRTHDAY_INITIAL_SCAN_DELAY_SECONDS",
            "BIRTHDAY_CHECK_INTERVAL_SECONDS",
        ),
    ),
    (
        "Reminders",
        ("REMINDER_ENABLED", "REMINDER_MAX_AGE_DAYS", "REMINDER_DEFAULT_TIMEZONE"),
    ),
    (
        "Duck Game",
        ("DUCKS",),
    ),
    (
        "User Tracking",
        ("USERS",),
    ),
    (
        "IdleRPG",
        ("IDLERPG",),
    ),
    (
        "Sed Corrections",
        (
            "SED_REGEX_TIMEOUT",
            "SED_MAX_PATTERN_LENGTH",
            "SED_MAX_REPLACEMENT_LENGTH",
            "SED_MAX_INPUT_LENGTH",
            "SED_MAX_OUTPUT_LENGTH",
        ),
    ),
    (
        "Polls",
        (
            "POLL_MAX_OPTIONS",
            "POLL_MAX_QUESTION_LEN",
            "POLL_MAX_OPTION_LEN",
            "POLL_MAX_HISTORY_PER_ROOM",
            "POLL_DEFAULT_MULTI_MAX_CHOICES",
        ),
    ),
    (
        "Pins",
        ("PIN_PAGE_SIZE",),
    ),
    (
        "Translate",
        (
            "TRANSLATE_FROM",
            "TRANSLATE_TO",
            "TRANSLATE_TIMEOUT_SECONDS",
            "TRANSLATE_MAX_INPUT_LENGTH",
            "TRANSLATE_MAX_OUTPUT_LENGTH",
            "TRANSLATE_MAX_RESPONSE_BYTES",
        ),
    ),
    (
        "Karma / Tell",
        ("KARMA_DELAY_SECONDS", "TELL_DELIVERY_DELAY_SECONDS"),
    ),
    (
        "XKCD",
        (
            "XKCD_CHECK_INTERVAL",
            "XKCD_INDEX_START_DELAY_SECONDS",
            "XKCD_INDEX_REQUEST_DELAY_SECONDS",
            "XKCD_HTTP_TIMEOUT",
        ),
    ),
)

def config_defaults() -> dict[str, Any]:
    return {name: field.default for name, field in CONFIG_FIELDS.items() if field.default is not MISSING}

def required_config_types() -> dict[str, type | tuple[type, ...]]:
    return {name: field.accepted_type for name, field in CONFIG_FIELDS.items() if field.required}

def optional_config_types() -> dict[str, type | tuple[type, ...]]:
    return {name: field.accepted_type for name, field in CONFIG_FIELDS.items() if not field.required}

def python_config_key_map() -> dict[str, str]:
    return {field.python_key: name for name, field in CONFIG_FIELDS.items()}

def startup_only_keys() -> set[str]:
    return {name for name, field in CONFIG_FIELDS.items() if field.startup_only}

# Compatibility names used by older imports/tests.
operational_defaults = config_defaults
operational_types = optional_config_types
operational_python_key_map = python_config_key_map
operational_startup_only_keys = startup_only_keys
