"""Split module for utils/config.py: validation."""

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

    if "rss_max_entries_per_poll" in cfg:
        value = cfg["rss_max_entries_per_poll"]
        if isinstance(value, int) and value <= 0:
            errors.append("rss_max_entries_per_poll: must be greater than 0")

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
        "rss_fetch_timeout_seconds",
        "xmpp_query_timeout_seconds",
        "vcard_fetch_timeout_seconds",
        "updatecheck_timeout_seconds",
        "urlcheck_fetch_timeout_seconds",
        "rss_retry_backoff_multiplier",
        "rss_similarity_threshold",
        "sed_regex_timeout",
        "xkcd_index_request_delay_seconds",
        "xkcd_http_timeout",
    }
    positive_int_keys = {
        "urlcheck_wait_seconds",
        "urlcheck_max_redirects",
        "urlcheck_max_read_bytes",
        "rss_max_redirects",
        "rss_max_read_bytes",
        "rss_retry_initial_delay",
        "rss_max_backoff_time",
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
