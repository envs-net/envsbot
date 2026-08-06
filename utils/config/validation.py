"""Split module for utils/config.py: validation."""

from __future__ import annotations
import sys
from pathlib import Path
from zoneinfo import available_timezones
import slixmpp

from .defaults import BASE_DIR, OPTIONAL_CONFIG_TYPES, REQUIRED_CONFIG_KEYS
from .errors import ConfigError


AVAILABLE_TIMEZONES = available_timezones()


def _is_config_int(value: object) -> bool:
    """Return True for real integers, but not bool values."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_config_number(value: object) -> bool:
    """Return True for int/float config values, but not bool values."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _matches_expected_type(value: object, expected_type: object) -> bool:
    expected_types = (
        expected_type if isinstance(expected_type, tuple) else (expected_type,)
    )

    for typ in expected_types:
        if typ is int and _is_config_int(value):
            return True
        if typ is float and isinstance(value, float) and not isinstance(value, bool):
            return True
        if typ is bool and isinstance(value, bool):
            return True
        if typ not in {int, float, bool} and isinstance(value, typ):
            return True

    return False


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
    positive_integer_keys = {
        "backup_keep",
        "command_usage_retention_days",
        "database_maintenance_interval_seconds",
        "outbox_batch_size",
        "outbox_inflight_timeout_seconds",
        "outbox_max_attempts",
        "outbox_retry_initial_seconds",
        "outbox_retry_max_seconds",
        "task_restart_max_attempts",
        "birthday_cache_ttl_seconds",
        "birthday_check_interval_seconds",
        "birthday_initial_scan_delay_seconds",
        "karma_delay_seconds",
        "message_cache_size",
        "pin_page_size",
        "poll_max_history_per_room",
        "poll_max_option_len",
        "poll_max_options",
        "poll_max_question_len",
        "reminder_max_age_days",
        "rss_global_query_interval",
        "rss_broken_error_threshold",
        "rss_list_page_size",
        "rss_max_backoff_time",
        "rss_max_entries_per_poll",
        "rss_max_read_bytes",
        "rss_template_max_length",
        "rss_max_redirects",
        "rss_retry_initial_delay",
        "sed_max_input_length",
        "sed_max_output_length",
        "sed_max_pattern_length",
        "sed_max_replacement_length",
        "tell_delivery_delay_seconds",
        "urlcheck_max_read_bytes",
        "urlcheck_max_redirects",
        "urlcheck_wait_seconds",
        "xkcd_check_interval",
        "xkcd_index_start_delay_seconds",
    }
    positive_number_keys = {
        "http_timeout_seconds",
        "outbox_poll_seconds",
        "task_restart_initial_seconds",
        "task_restart_max_seconds",
        "task_restart_reset_seconds",
        "watchdog_interval_seconds",
        "watchdog_lag_failure_seconds",
        "watchdog_lag_warning_seconds",
        "rss_fetch_timeout_seconds",
        "rss_retry_backoff_multiplier",
        "sed_regex_timeout",
        "stop_cmd_timeout_seconds",
        "updatecheck_timeout_seconds",
        "urlcheck_fetch_timeout_seconds",
        "vcard_fetch_timeout_seconds",
        "xmpp_query_timeout_seconds",
        "xkcd_http_timeout",
        "xkcd_index_request_delay_seconds",
    }
    zero_or_greater_integer_keys = {
        "max_new_feed_entries",
        "message_cache_max_age_days",
        "rss_trusted_max_feeds",
    }
    zero_or_greater_number_keys = {
        "rss_startup_stagger_seconds",
    }
    default_pagination = cfg.get("default_pagination")
    if default_pagination is not None:
        if str(default_pagination).strip().lower() != "all":
            if isinstance(default_pagination, bool):
                errors.append("default_pagination: expected 'all' or positive integer")
            else:
                try:
                    parsed_default_pagination = int(str(default_pagination).strip())
                except (TypeError, ValueError):
                    parsed_default_pagination = 0
                if parsed_default_pagination <= 0:
                    errors.append("default_pagination: expected 'all' or positive integer")
    range_integer_keys = {"port": (1, 65535)}
    min_integer_keys = {"version_check_interval": 60}
    range_number_keys = {"rss_similarity_threshold": (0, 1)}

    for key in positive_integer_keys:
        value = cfg.get(key)
        if _is_config_int(value) and value <= 0:
            errors.append(f"{key}: must be greater than 0")

    for key in positive_number_keys:
        value = cfg.get(key)
        if _is_config_number(value) and value <= 0:
            errors.append(f"{key}: must be greater than 0")

    for key in zero_or_greater_integer_keys:
        value = cfg.get(key)
        if _is_config_int(value) and value < 0:
            errors.append(f"{key}: must be 0 or greater")

    for key in zero_or_greater_number_keys:
        value = cfg.get(key)
        if _is_config_number(value) and value < 0:
            errors.append(f"{key}: must be 0 or greater")

    for key, (minimum, maximum) in range_integer_keys.items():
        value = cfg.get(key)
        if _is_config_int(value) and not (minimum <= value <= maximum):
            errors.append(f"{key}: must be between {minimum} and {maximum}")

    for key, minimum in min_integer_keys.items():
        value = cfg.get(key)
        if _is_config_int(value) and value < minimum:
            errors.append(f"{key}: must be at least {minimum}")

    for key, (minimum, maximum) in range_number_keys.items():
        value = cfg.get(key)
        if _is_config_number(value) and not (minimum < value <= maximum):
            errors.append(
                f"{key}: must be greater than {minimum} and at most {maximum}"
            )


def _validate_timezone(cfg, errors):
    timezone_keys = ("timezone", "reminder_default_timezone")
    for key in timezone_keys:
        if key not in cfg:
            continue

        timezone = cfg[key]
        if timezone is None:
            continue
        if not isinstance(timezone, str):
            continue

        if timezone not in AVAILABLE_TIMEZONES:
            errors.append(
                f"{key}: must be a valid IANA timezone, e.g. Europe/Berlin")


def _validate_admin_report(cfg, errors):
    value = cfg.get("admin_report_time")
    if value is not None and isinstance(value, str):
        try:
            hour_text, minute_text = value.split(":", 1)
            hour = int(hour_text)
            minute = int(minute_text)
        except (TypeError, ValueError):
            errors.append("admin_report_time: expected HH:MM")
        else:
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                errors.append("admin_report_time: expected a valid 24-hour HH:MM time")
    timezone_name = cfg.get("admin_report_timezone")
    if isinstance(timezone_name, str) and timezone_name and timezone_name not in AVAILABLE_TIMEZONES:
        errors.append("admin_report_timezone: must be a valid IANA timezone")
    destination = cfg.get("admin_report_jid")
    if isinstance(destination, str) and destination.strip():
        _validate_jid(destination, "admin_report_jid", errors)


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
                    "admin_report_jid",
                    "admin_report_timezone",
                },
            )
            continue

        expected_types = (
            expected_type if isinstance(expected_type, tuple) else (expected_type,)
        )
        if not _matches_expected_type(value, expected_types):
            expected_names = " or ".join(t.__name__ for t in expected_types)
            errors.append(
                f"{key}: expected {expected_names}, "
                f"got {type(value).__name__}"
            )
    return errors


def _validate_room_plugin_defaults(cfg, errors):
    defaults = cfg.get("room_plugin_defaults")
    if defaults is None:
        return
    if not isinstance(defaults, dict):
        return

    for plugin, enabled in defaults.items():
        if not isinstance(plugin, str) or not plugin.strip():
            errors.append("room_plugin_defaults: plugin names must be non-empty strings")
            continue
        if not isinstance(enabled, bool):
            errors.append(
                f"room_plugin_defaults.{plugin}: expected bool, "
                f"got {type(enabled).__name__}"
            )


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
    _validate_admin_report(cfg, errors)
    _validate_avatar(cfg, errors, [])
    _validate_numeric_ranges(cfg, errors)
    _validate_room_plugin_defaults(cfg, errors)

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


def validate_startup_config(cfg):
    """
    Validate the effective runtime config before starting the bot.

    This should be called by envsbot.py before Bot() is constructed so
    configuration mistakes produce a clear error instead of a restart loop.
    """
    validate_config(cfg, require_required_keys=True)

    for warning in collect_config_warnings(cfg):
        print(f"[CONFIG] Warning: {warning}", file=sys.stderr)
