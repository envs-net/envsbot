"""Configuration loading and validation for EnvsBot.

Runtime configuration is read from ``config.py`` in the repository root.  The
file follows the same simple Python assignment style as muc_banbot: operators
copy ``config_sample.py`` to ``config.py`` and edit uppercase settings such as
``JID``, ``PASSWORD`` and ``COMMAND_PREFIX``.

The rest of the bot still consumes a dictionary named ``config`` for backwards
compatibility.  Loader aliases convert uppercase Python settings to the historic
lowercase keys used by plugins.  A legacy ``config.json`` loader remains as a
migration fallback when no ``config.py`` exists.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import available_timezones

import slixmpp


# project root
BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILENAME = "config.py"
LEGACY_CONFIG_FILENAME = "config.json"

DEFAULT_CONFIG = {
    "prefix": ",",
    "loglevel": "INFO",
    "db": "bot.db",
    "resource": None,
    "host": None,
    "port": 5222,
    "direct_tls": False,
    "restart_notification_file": "/tmp/envsbot_restart_notification.json",
    "backup_dir": "data/backups",
    "backup_keep": 15,
    "backup_on_start": True,
    "http_timeout_seconds": 8,
    "http_user_agent": "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)",
    "xmpp_query_timeout_seconds": 8,
    "vcard_fetch_timeout_seconds": 10,
    "updatecheck_timeout_seconds": 15,
    "version_check_enabled": False,
    "version_check_interval": 3600,
    "version_check_url": "https://github.com/envs-net/envsbot/releases/latest",
    "room_invites_enabled": True,
    "room_invite_notify_jid": "",
    "room_invite_max_age_days": 30,
    "urlcheck_wait_seconds": 120,
    "urlcheck_fetch_timeout_seconds": 8,
    "urlcheck_max_redirects": 5,
    "urlcheck_max_read_bytes": 65536,
    "urlcheck_user_agent": "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)",
    "rss_global_query_interval": 1200,
    "max_new_feed_entries": 5,
    "rss_max_backoff_time": 86400,
    "rss_backoff_increment_multiplier": 60,
    "rss_similarity_threshold": 0.8,
    "rss_user_agent": "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)",
    "birthday_cache_ttl_seconds": 43200,
    "birthday_initial_scan_delay_seconds": 10,
    "birthday_check_interval_seconds": 3600,
    "sed_regex_timeout": 1.0,
    "sed_max_pattern_length": 256,
    "sed_max_replacement_length": 1000,
    "sed_max_input_length": 5000,
    "sed_max_output_length": 8000,
    "sed_cache_size": 10,
    "poll_max_options": 10,
    "poll_max_question_len": 200,
    "poll_max_option_len": 100,
    "poll_max_history_per_room": 50,
    "pin_page_size": 10,
    "pin_recent_cache_size": 80,
    "karma_delay_seconds": 60,
    "tell_delivery_delay_seconds": 5,
    "xkcd_check_interval": 3600,
    "xkcd_index_start_delay_seconds": 30,
    "xkcd_index_request_delay_seconds": 0.15,
    "xkcd_http_timeout": 10,
}

REQUIRED_CONFIG_KEYS = {
    "jid": str,
    "password": str,
    "owner": str,
    "nick": str,
}

OPTIONAL_CONFIG_TYPES = {
    "prefix": str,
    "loglevel": str,
    "db": str,
    "resource": str,
    "restart_notification_file": str,
    "backup_dir": str,
    "backup_keep": int,
    "backup_on_start": bool,
    "stop_cmd": list,
    "admins": list,
    "avatar": str,
    "avatar_type": str,
    "timezone": str,
    "host": str,
    "port": int,
    "direct_tls": bool,
    "http_timeout_seconds": (int, float),
    "http_user_agent": str,
    "xmpp_query_timeout_seconds": (int, float),
    "vcard_fetch_timeout_seconds": (int, float),
    "updatecheck_timeout_seconds": (int, float),
    "rss_global_query_interval": int,
    "max_new_feed_entries": int,
    "rss_max_backoff_time": int,
    "rss_backoff_increment_multiplier": int,
    "rss_similarity_threshold": (int, float),
    "rss_user_agent": str,
    "urlcheck_wait_seconds": int,
    "urlcheck_fetch_timeout_seconds": (int, float),
    "urlcheck_max_redirects": int,
    "urlcheck_max_read_bytes": int,
    "urlcheck_user_agent": str,
    "birthday_cache_ttl_seconds": int,
    "birthday_initial_scan_delay_seconds": int,
    "birthday_check_interval_seconds": int,
    "sed_regex_timeout": (int, float),
    "sed_max_pattern_length": int,
    "sed_max_replacement_length": int,
    "sed_max_input_length": int,
    "sed_max_output_length": int,
    "sed_cache_size": int,
    "poll_max_options": int,
    "poll_max_question_len": int,
    "poll_max_option_len": int,
    "poll_max_history_per_room": int,
    "pin_page_size": int,
    "pin_recent_cache_size": int,
    "karma_delay_seconds": int,
    "tell_delivery_delay_seconds": int,
    "xkcd_check_interval": int,
    "xkcd_index_start_delay_seconds": int,
    "xkcd_index_request_delay_seconds": (int, float),
    "xkcd_http_timeout": (int, float),
    "youtube_api_key": str,
    "reminder_enabled": bool,
    "reminder_max_age_days": int,
    "version_check_enabled": bool,
    "version_check_interval": int,
    "version_check_url": str,
    "version_check_notify_jid": str,
    "room_invites_enabled": bool,
    "room_invite_notify_jid": str,
    "room_invite_max_age_days": int,
    "ducks": dict,
    "users": dict,
}

PYTHON_CONFIG_KEY_MAP = {
    "JID": "jid",
    "PASSWORD": "password",
    "NICK": "nick",
    "RESOURCE": "resource",
    "OWNER": "owner",
    "ADMINS": "admins",
    "COMMAND_PREFIX": "prefix",
    "LOG_LEVEL": "loglevel",
    "DB_FILE": "db",
    "RESTART_NOTIFICATION_FILE": "restart_notification_file",
    "BACKUP_DIR": "backup_dir",
    "BACKUP_KEEP": "backup_keep",
    "BACKUP_ON_START": "backup_on_start",
    "STOP_CMD": "stop_cmd",
    "AVATAR_PATH": "avatar",
    "AVATAR_TYPE": "avatar_type",
    "TIMEZONE": "timezone",
    "CONNECT_HOST": "host",
    "CONNECT_PORT": "port",
    "CONNECT_DIRECT_TLS": "direct_tls",
    "HTTP_TIMEOUT_SECONDS": "http_timeout_seconds",
    "HTTP_USER_AGENT": "http_user_agent",
    "XMPP_QUERY_TIMEOUT_SECONDS": "xmpp_query_timeout_seconds",
    "VCARD_FETCH_TIMEOUT_SECONDS": "vcard_fetch_timeout_seconds",
    "UPDATECHECK_TIMEOUT_SECONDS": "updatecheck_timeout_seconds",
    "YOUTUBE_API_KEY": "youtube_api_key",
    "REMINDER_ENABLED": "reminder_enabled",
    "REMINDER_MAX_AGE_DAYS": "reminder_max_age_days",
    "RSS_GLOBAL_QUERY_INTERVAL": "rss_global_query_interval",
    "MAX_NEW_FEED_ENTRIES": "max_new_feed_entries",
    "RSS_MAX_BACKOFF_TIME": "rss_max_backoff_time",
    "RSS_BACKOFF_INCREMENT_MULTIPLIER": "rss_backoff_increment_multiplier",
    "RSS_SIMILARITY_THRESHOLD": "rss_similarity_threshold",
    "RSS_USER_AGENT": "rss_user_agent",
    "URLCHECK_WAIT_SECONDS": "urlcheck_wait_seconds",
    "URLCHECK_FETCH_TIMEOUT_SECONDS": "urlcheck_fetch_timeout_seconds",
    "URLCHECK_MAX_REDIRECTS": "urlcheck_max_redirects",
    "URLCHECK_MAX_READ_BYTES": "urlcheck_max_read_bytes",
    "URLCHECK_USER_AGENT": "urlcheck_user_agent",
    "BIRTHDAY_CACHE_TTL_SECONDS": "birthday_cache_ttl_seconds",
    "BIRTHDAY_INITIAL_SCAN_DELAY_SECONDS": "birthday_initial_scan_delay_seconds",
    "BIRTHDAY_CHECK_INTERVAL_SECONDS": "birthday_check_interval_seconds",
    "SED_REGEX_TIMEOUT": "sed_regex_timeout",
    "SED_MAX_PATTERN_LENGTH": "sed_max_pattern_length",
    "SED_MAX_REPLACEMENT_LENGTH": "sed_max_replacement_length",
    "SED_MAX_INPUT_LENGTH": "sed_max_input_length",
    "SED_MAX_OUTPUT_LENGTH": "sed_max_output_length",
    "SED_CACHE_SIZE": "sed_cache_size",
    "POLL_MAX_OPTIONS": "poll_max_options",
    "POLL_MAX_QUESTION_LEN": "poll_max_question_len",
    "POLL_MAX_OPTION_LEN": "poll_max_option_len",
    "POLL_MAX_HISTORY_PER_ROOM": "poll_max_history_per_room",
    "PIN_PAGE_SIZE": "pin_page_size",
    "PIN_RECENT_CACHE_SIZE": "pin_recent_cache_size",
    "KARMA_DELAY_SECONDS": "karma_delay_seconds",
    "TELL_DELIVERY_DELAY_SECONDS": "tell_delivery_delay_seconds",
    "XKCD_CHECK_INTERVAL": "xkcd_check_interval",
    "XKCD_INDEX_START_DELAY_SECONDS": "xkcd_index_start_delay_seconds",
    "XKCD_INDEX_REQUEST_DELAY_SECONDS": "xkcd_index_request_delay_seconds",
    "XKCD_HTTP_TIMEOUT": "xkcd_http_timeout",
    "VERSION_CHECK_ENABLED": "version_check_enabled",
    "VERSION_CHECK_INTERVAL": "version_check_interval",
    "VERSION_CHECK_URL": "version_check_url",
    "VERSION_CHECK_NOTIFY_JID": "version_check_notify_jid",
    "ROOM_INVITES_ENABLED": "room_invites_enabled",
    "ROOM_INVITE_NOTIFY_JID": "room_invite_notify_jid",
    "ROOM_INVITE_MAX_AGE_DAYS": "room_invite_max_age_days",
    "DUCKS": "ducks",
    "USERS": "users",
}

NORMALIZED_CONFIG_KEYS = (
    set(DEFAULT_CONFIG)
    | set(REQUIRED_CONFIG_KEYS)
    | set(OPTIONAL_CONFIG_TYPES)
    | set(PYTHON_CONFIG_KEY_MAP.values())
)

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
        ),
    ),
    (
        "Backups",
        ("BACKUP_DIR", "BACKUP_KEEP", "BACKUP_ON_START"),
    ),
    (
        "HTTP Defaults",
        ("HTTP_TIMEOUT_SECONDS", "HTTP_USER_AGENT"),
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
            "RSS_MAX_BACKOFF_TIME",
            "RSS_BACKOFF_INCREMENT_MULTIPLIER",
            "RSS_SIMILARITY_THRESHOLD",
            "RSS_USER_AGENT",
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
        ("REMINDER_ENABLED", "REMINDER_MAX_AGE_DAYS"),
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
        "Sed Corrections",
        (
            "SED_REGEX_TIMEOUT",
            "SED_MAX_PATTERN_LENGTH",
            "SED_MAX_REPLACEMENT_LENGTH",
            "SED_MAX_INPUT_LENGTH",
            "SED_MAX_OUTPUT_LENGTH",
            "SED_CACHE_SIZE",
        ),
    ),
    (
        "Polls",
        (
            "POLL_MAX_OPTIONS",
            "POLL_MAX_QUESTION_LEN",
            "POLL_MAX_OPTION_LEN",
            "POLL_MAX_HISTORY_PER_ROOM",
        ),
    ),
    (
        "Pins",
        ("PIN_PAGE_SIZE", "PIN_RECENT_CACHE_SIZE"),
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

_LOWER_TO_PYTHON_CONFIG_KEY = {
    normalized_key: python_key
    for python_key, normalized_key in PYTHON_CONFIG_KEY_MAP.items()
}


def get_config_display_sections(cfg: dict) -> list[tuple[str, list[tuple[str, object]]]]:
    """Return config items grouped like config_sample.py for bot output."""
    seen = set()
    sections = []

    for title, python_keys in CONFIG_DISPLAY_SECTIONS:
        entries = []
        for python_key in python_keys:
            normalized_key = PYTHON_CONFIG_KEY_MAP[python_key]
            if normalized_key not in cfg:
                continue
            entries.append((python_key, cfg[normalized_key]))
            seen.add(normalized_key)
        if entries:
            sections.append((title, entries))

    extra_entries = []
    for key in sorted(k for k in cfg if k not in seen):
        display_key = _LOWER_TO_PYTHON_CONFIG_KEY.get(key, key.upper())
        extra_entries.append((display_key, cfg[key]))
    if extra_entries:
        sections.append(("Other", extra_entries))

    return sections


def _sample_config_path() -> Path:
    return BASE_DIR / "config_sample.py"


def load_default_config_for_diff() -> dict:
    """Return documented defaults used by ``config diff``.

    ``config_sample.py`` is the operator-facing source of truth for defaults.
    We merge it onto ``DEFAULT_CONFIG`` so legacy/internal fallback keys still
    have stable comparison values, then validate only optional types because
    sample credentials are placeholders by design.
    """
    defaults = DEFAULT_CONFIG.copy()
    sample_path = _sample_config_path()
    if sample_path.exists():
        defaults.update(_load_python_config(sample_path))
    validate_config(defaults, require_required_keys=False)
    return defaults


def _flatten_config_value(name: str, value: object) -> list[tuple[str, object]]:
    if not isinstance(value, dict):
        return [(name, value)]

    flattened = []
    for key in sorted(value):
        flattened.append((f"{name}.{key}", value[key]))
    return flattened


def get_config_diff_sections(
    current_cfg: dict | None = None,
    default_cfg: dict | None = None,
) -> list[tuple[str, list[tuple[str, object, object]]]]:
    """Return config values that differ from documented defaults.

    The result mirrors ``get_config_display_sections`` but entries are
    ``(display_name, current_value, default_value)`` tuples. Nested dictionaries
    are compared one level deep as dotted keys such as ``DUCKS.spawn_chance``.
    """
    current = config if current_cfg is None else current_cfg
    defaults = load_default_config_for_diff() if default_cfg is None else default_cfg
    sections = []
    seen = set()

    for title, python_keys in CONFIG_DISPLAY_SECTIONS:
        entries = []
        for python_key in python_keys:
            normalized_key = PYTHON_CONFIG_KEY_MAP[python_key]
            if normalized_key not in current:
                continue

            current_value = current.get(normalized_key)
            default_value = defaults.get(normalized_key)
            seen.add(normalized_key)

            current_items = dict(_flatten_config_value(python_key, current_value))
            default_items = dict(_flatten_config_value(python_key, default_value))
            for display_name in sorted(set(current_items) | set(default_items)):
                current_item = current_items.get(display_name)
                default_item = default_items.get(display_name)
                if current_item != default_item:
                    entries.append((display_name, current_item, default_item))

        if entries:
            sections.append((title, entries))

    extra_entries = []
    for key in sorted(k for k in current if k not in seen):
        display_key = _LOWER_TO_PYTHON_CONFIG_KEY.get(key, key.upper())
        current_value = current.get(key)
        default_value = defaults.get(key)
        if current_value != default_value:
            extra_entries.append((display_key, current_value, default_value))
    if extra_entries:
        sections.append(("Other", extra_entries))

    return sections


class ConfigError(Exception):
    """Raised when EnvsBot configuration is invalid or incomplete."""


def _config_path_from_env() -> Path | None:
    configured = os.environ.get("ENVSBOT_CONFIG")
    if not configured:
        return None

    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _default_config_path() -> Path:
    return BASE_DIR / CONFIG_FILENAME


def _legacy_config_path() -> Path:
    return BASE_DIR / LEGACY_CONFIG_FILENAME


def get_runtime_config_path() -> Path:
    """Return the config file path currently used by envsbot.

    ``config.py`` is preferred.  A custom ``ENVSBOT_CONFIG`` path is returned
    when set.  The legacy JSON path is returned only as a migration fallback.
    """
    configured_path = _config_path_from_env()
    if configured_path is not None:
        return configured_path

    config_path = _default_config_path()
    if config_path.exists():
        return config_path

    legacy_path = _legacy_config_path()
    if legacy_path.exists():
        return legacy_path

    return config_path


def _format_json_error(error: json.JSONDecodeError, path: Path) -> str:
    return (
        f"Failed to parse {path.name} at "
        f"line {error.lineno}, column {error.colno}: {error.msg}"
    )


def _format_python_error(error: SyntaxError, path: Path) -> str:
    line = error.lineno or "?"
    column = error.offset or "?"
    return f"Failed to parse {path.name} at line {line}, column {column}: {error.msg}"


def _load_python_config(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")

    module_name = "_envsbot_runtime_config"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ConfigError(f"Failed to load {path.name}: no import loader available")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except SyntaxError as e:
        raise ConfigError(_format_python_error(e, path)) from e
    except ConfigError:
        raise
    except Exception as e:
        raise ConfigError(f"Failed to load {path.name}: {e}") from e

    loaded = {}
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue

        if name in PYTHON_CONFIG_KEY_MAP:
            loaded[PYTHON_CONFIG_KEY_MAP[name]] = value
            continue

        # Allow already-normalized lowercase keys for tests and small local
        # overrides, but keep the documented operator format uppercase.
        if name in NORMALIZED_CONFIG_KEYS:
            loaded[name] = value
            continue

        if name.isupper():
            loaded[name.lower()] = value

    return loaded


def _load_legacy_json_config(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(_format_json_error(e, path)) from e
    except Exception as e:
        raise ConfigError(f"Failed to load {path.name}: {e}") from e

    if not isinstance(loaded, dict):
        raise ConfigError(f"{path.name} must contain a JSON object at top level")

    return {k: v for k, v in loaded.items() if not str(k).startswith("_comment")}


def _validate_string(value, key, errors, allow_empty=False):
    if not isinstance(value, str):
        errors.append(f"{key}: expected string, got {type(value).__name__}")
        return

    if not allow_empty and not value.strip():
        errors.append(f"{key}: must not be empty")


def _validate_jid(value, key, errors):
    """Validate a config value as a user JID with username and domain."""
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key}: must be a non-empty JID string")
        return

    try:
        jid = slixmpp.JID(value)
    except Exception as e:
        errors.append(f"{key}: invalid JID ({e})")
        return

    if not jid.user or not jid.domain:
        errors.append(
            f"{key}: must include username and domain, e.g. user@example.org")


def _validate_numeric_ranges(cfg, errors):
    if "rss_global_query_interval" in cfg:
        value = cfg["rss_global_query_interval"]
        if isinstance(value, int) and value <= 0:
            errors.append("rss_global_query_interval: must be greater than 0")

    if "max_new_feed_entries" in cfg:
        value = cfg["max_new_feed_entries"]
        if isinstance(value, int) and value < 0:
            errors.append("max_new_feed_entries: must be 0 or greater")

    if "port" in cfg:
        value = cfg["port"]
        if isinstance(value, int) and not (1 <= value <= 65535):
            errors.append("port: must be between 1 and 65535")

    if "reminder_max_age_days" in cfg:
        value = cfg["reminder_max_age_days"]
        if isinstance(value, int) and value <= 0:
            errors.append("reminder_max_age_days: must be greater than 0")

    if "version_check_interval" in cfg:
        value = cfg["version_check_interval"]
        if isinstance(value, int) and value < 60:
            errors.append("version_check_interval: must be at least 60")

    positive_number_keys = {
        "http_timeout_seconds",
        "xmpp_query_timeout_seconds",
        "vcard_fetch_timeout_seconds",
        "updatecheck_timeout_seconds",
        "urlcheck_fetch_timeout_seconds",
        "rss_similarity_threshold",
        "sed_regex_timeout",
        "xkcd_index_request_delay_seconds",
        "xkcd_http_timeout",
    }
    positive_int_keys = {
        "urlcheck_wait_seconds",
        "urlcheck_max_redirects",
        "urlcheck_max_read_bytes",
        "rss_max_backoff_time",
        "rss_backoff_increment_multiplier",
        "birthday_cache_ttl_seconds",
        "birthday_initial_scan_delay_seconds",
        "birthday_check_interval_seconds",
        "sed_max_pattern_length",
        "sed_max_replacement_length",
        "sed_max_input_length",
        "sed_max_output_length",
        "sed_cache_size",
        "poll_max_options",
        "poll_max_question_len",
        "poll_max_option_len",
        "poll_max_history_per_room",
        "pin_page_size",
        "pin_recent_cache_size",
        "karma_delay_seconds",
        "tell_delivery_delay_seconds",
        "xkcd_check_interval",
        "xkcd_index_start_delay_seconds",
        "backup_keep",
    }

    for key in positive_number_keys:
        value = cfg.get(key)
        if isinstance(value, (int, float)) and value <= 0:
            errors.append(f"{key}: must be greater than 0")

    for key in positive_int_keys:
        value = cfg.get(key)
        if isinstance(value, int) and value <= 0:
            errors.append(f"{key}: must be greater than 0")

    similarity = cfg.get("rss_similarity_threshold")
    if isinstance(similarity, (int, float)) and not (0 < similarity <= 1):
        errors.append("rss_similarity_threshold: must be greater than 0 and at most 1")


def _validate_timezone(cfg, errors):
    if "timezone" not in cfg:
        return

    timezone = cfg["timezone"]
    if timezone is None:
        return
    if not isinstance(timezone, str):
        return

    if timezone not in available_timezones():
        errors.append(
            "timezone: must be a valid IANA timezone, e.g. Europe/Berlin")


def _validate_avatar(cfg, errors, warnings):
    avatar = cfg.get("avatar")
    avatar_type = cfg.get("avatar_type")

    if avatar_type and avatar_type not in ("image/png", "image/jpeg"):
        errors.append("avatar_type: must be image/png or image/jpeg")

    if avatar and avatar_type:
        suffix = Path(avatar).suffix.lower()

        if avatar_type == "image/png" and suffix != ".png":
            warnings.append(
                "avatar: file extension does not match avatar_type image/png")

        if avatar_type == "image/jpeg" and suffix not in (".jpg", ".jpeg"):
            warnings.append(
                "avatar: file extension does not match avatar_type image/jpeg")

    if avatar:
        avatar_path = Path(avatar)
        if not avatar_path.is_absolute():
            avatar_path = BASE_DIR / avatar_path

        if not avatar_path.exists():
            warnings.append(f"avatar: file does not exist: {avatar_path}")


def collect_config_warnings(cfg):
    """Return non-fatal config warnings."""
    warnings = []

    if not isinstance(cfg, dict):
        return warnings

    _validate_avatar(cfg, [], warnings)
    return warnings


def check_required_keys(cfg):
    errors = []
    for key, expected_type in REQUIRED_CONFIG_KEYS.items():
        if key not in cfg:
            errors.append(f"Missing required key: {key}")
            continue

        if expected_type is str:
            _validate_string(cfg[key], key, errors)
        elif not isinstance(cfg[key], expected_type):
            errors.append(
                f"{key}: expected {expected_type.__name__}, "
                f"got {type(cfg[key]).__name__}"
            )
    return errors


def check_optional_keys(cfg):
    errors = []
    for key, expected_type in OPTIONAL_CONFIG_TYPES.items():
        if key not in cfg:
            continue

        value = cfg[key]
        if value is None:
            continue

        if expected_type is str:
            _validate_string(
                value,
                key,
                errors,
                allow_empty=key in {
                    "version_check_notify_jid",
                    "room_invite_notify_jid",
                },
            )
            continue

        expected_types = (
            expected_type if isinstance(expected_type, tuple) else (expected_type,)
        )
        if not isinstance(value, expected_types):
            expected_names = " or ".join(t.__name__ for t in expected_types)
            errors.append(
                f"{key}: expected {expected_names}, "
                f"got {type(value).__name__}"
            )
    return errors


def validate_config(cfg, require_required_keys=False):
    """
    Validate envsbot configuration.

    Parameters
    ----------
    cfg : dict
        Configuration dictionary to validate.
    require_required_keys : bool
        If True, require runtime keys such as jid/password/owner/nick.
        Tests and helper imports may keep this False, while the real bot
        startup should use True.

    Raises
    ------
    ConfigError
        If the configuration is invalid.
    """
    errors = []

    if not isinstance(cfg, dict):
        raise ConfigError("config must be a dictionary")

    if require_required_keys:
        errors = check_required_keys(cfg)

        if "jid" in cfg:
            _validate_jid(cfg["jid"], "jid", errors)

        if "owner" in cfg:
            _validate_jid(cfg["owner"], "owner", errors)

    errors.extend(check_optional_keys(cfg))

    if ("prefix" in cfg and isinstance(cfg["prefix"], str) and
            not cfg["prefix"]):
        errors.append("prefix: must not be empty")

    if "loglevel" in cfg and isinstance(cfg["loglevel"], str):
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if cfg["loglevel"].upper() not in valid_levels:
            errors.append(
                "loglevel: must be one of "
                f"{', '.join(sorted(valid_levels))}"
            )

    if "admins" in cfg and isinstance(cfg["admins"], list):
        for idx, admin in enumerate(cfg["admins"]):
            if not isinstance(admin, str) or not admin.strip():
                errors.append(f"admins[{idx}]: must be a non-empty string")
                continue

            _validate_jid(admin, f"admins[{idx}]", errors)

    _validate_timezone(cfg, errors)
    _validate_avatar(cfg, errors, [])
    _validate_numeric_ranges(cfg, errors)

    if cfg.get("version_check_enabled") and not str(
        cfg.get("version_check_url", "")
    ).strip():
        errors.append(
            "version_check_url: must not be empty "
            "when version_check_enabled is true"
        )

    if errors:
        raise ConfigError(
            "Invalid configuration:\n- " + "\n- ".join(errors)
        )


def load_config(require_required_keys=False):
    """
    Load config.py and validate it.

    ``config.py`` is the primary format.  If ``ENVSBOT_CONFIG`` is set, that
    exact file is used and may be either ``.py`` or legacy ``.json``.  If no
    ``config.py`` exists, a legacy ``config.json`` is still accepted as a
    migration fallback.
    """
    cfg = DEFAULT_CONFIG.copy()

    configured_path = _config_path_from_env()
    if configured_path is not None:
        config_path = configured_path
        loaded = (
            _load_legacy_json_config(config_path)
            if config_path.suffix.lower() == ".json"
            else _load_python_config(config_path)
        )
    else:
        config_path = _default_config_path()
        if config_path.exists():
            loaded = _load_python_config(config_path)
        else:
            legacy_path = _legacy_config_path()
            if not legacy_path.exists():
                if require_required_keys:
                    raise ConfigError(f"Missing config file: {config_path}")

                validate_config(cfg, require_required_keys=False)
                return cfg
            loaded = _load_legacy_json_config(legacy_path)

    cfg.update(loaded)
    validate_config(cfg, require_required_keys=require_required_keys)
    return cfg


def validate_startup_config(cfg):
    """
    Validate the effective runtime config before starting the bot.

    This should be called by envsbot.py before Bot() is constructed so
    configuration mistakes produce a clear error instead of a restart loop.
    """
    validate_config(cfg, require_required_keys=True)

    for warning in collect_config_warnings(cfg):
        print(f"[CONFIG] Warning: {warning}", file=sys.stderr)


def exit_on_config_error(error):
    """Print a readable config error and terminate startup."""
    print(f"[CONFIG] {error}", file=sys.stderr)
    raise SystemExit(1) from error


# global config object (backwards compatible)
try:
    config = load_config(require_required_keys=False)
except ConfigError as e:
    exit_on_config_error(e)


def setup_logging(log_dir: Path | str = "logs"):
    """
    Initialize the logging system.

    ``log_dir`` is injectable for tests so mutation tools can keep a stable
    project working directory while still verifying log-file creation.
    """
    log_level = getattr(logging, config.get(
        "loglevel", "INFO").upper(), logging.INFO)

    log_dir = Path(log_dir)
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / "envsbot.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=2_000_000,  # 2 MB
        backupCount=5,
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=log_level,
        handlers=[console, file_handler],
    )


if __name__ == "__main__":
    try:
        validate_startup_config(config)
    except ConfigError as e:
        exit_on_config_error(e)

    print("[CONFIG] config.py is valid")
