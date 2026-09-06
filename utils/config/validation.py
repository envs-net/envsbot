"""Split module for utils/config.py: validation."""

from __future__ import annotations

import sys
from pathlib import Path

import slixmpp
from envs_xmpp_core.config.schema import (
    expected_type_name,
    is_config_int,
    matches_expected_type,
)

from utils.bundled_assets import resolve_bundled_asset
from utils.time_utils import is_timezone_name

from .defaults import BASE_DIR, OPTIONAL_CONFIG_TYPES, REQUIRED_CONFIG_KEYS
from .errors import ConfigError
from .spec import CONFIG_FIELDS, NESTED_CONFIG_FIELDS


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
    """Validate declarative min/max/choice constraints plus pagination syntax."""
    default_pagination = cfg.get("default_pagination")
    if default_pagination is not None:
        if str(default_pagination).strip().lower() != "all":
            if isinstance(default_pagination, bool):
                errors.append("default_pagination: expected 'all' or positive integer")
            else:
                try:
                    parsed = int(str(default_pagination).strip())
                except (TypeError, ValueError):
                    parsed = 0
                if parsed <= 0:
                    errors.append("default_pagination: expected 'all' or positive integer")

    for key, field in CONFIG_FIELDS.items():
        value = cfg.get(key)
        if value is None or isinstance(value, bool):
            continue
        if field.choices and isinstance(value, str) and value not in field.choices:
            errors.append(f"{key}: expected one of {', '.join(field.choices)}")
            continue
        if not isinstance(value, (int, float)):
            continue
        if field.minimum is not None and field.maximum is not None:
            if field.minimum_exclusive:
                invalid = value <= field.minimum or value > field.maximum
                if invalid:
                    errors.append(
                        f"{key}: must be greater than {field.minimum} and at most {field.maximum}"
                    )
            elif value < field.minimum or value > field.maximum:
                errors.append(
                    f"{key}: must be between {field.minimum} and {field.maximum}"
                )
            continue
        if field.minimum is not None:
            invalid = value <= field.minimum if field.minimum_exclusive else value < field.minimum
            if invalid:
                if field.minimum_exclusive:
                    errors.append(f"{key}: must be greater than {field.minimum}")
                elif field.minimum == 0:
                    errors.append(f"{key}: must be 0 or greater")
                else:
                    errors.append(f"{key}: must be at least {field.minimum}")
        if field.maximum is not None and value > field.maximum:
            errors.append(f"{key}: must be at most {field.maximum}")


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

        if not is_timezone_name(timezone):
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
    if isinstance(timezone_name, str) and timezone_name and not is_timezone_name(timezone_name):
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
        avatar_path = resolve_bundled_asset(avatar, base_dir=BASE_DIR)

        if not avatar_path.exists():
            warnings.append(f"avatar: file does not exist: {avatar_path}")


def _validate_translate_rate_limit(cfg, errors):
    initial = cfg.get("translate_rate_limit_initial_seconds")
    maximum = cfg.get("translate_rate_limit_max_seconds")
    if (
        isinstance(initial, (int, float))
        and not isinstance(initial, bool)
        and isinstance(maximum, (int, float))
        and not isinstance(maximum, bool)
        and maximum < initial
    ):
        errors.append(
            "translate_rate_limit_max_seconds: must be greater than or equal to "
            "translate_rate_limit_initial_seconds"
        )


def _validate_backup_schedule(cfg, warnings):
    """Warn when periodic backup cadence cannot satisfy the age alert."""
    interval = cfg.get("backup_interval_hours")
    max_age = cfg.get("admin_alert_backup_max_age_hours")
    if (
        is_config_int(interval)
        and interval > 0
        and is_config_int(max_age)
        and max_age > 0
        and interval >= max_age
    ):
        warnings.append(
            "backup_interval_hours: should be lower than "
            "admin_alert_backup_max_age_hours so scheduled backups complete "
            "before the stale-backup alert threshold"
        )


def collect_config_warnings(cfg):
    """Return non-fatal config warnings."""
    warnings: list[str] = []

    if not isinstance(cfg, dict):
        return warnings

    _validate_avatar(cfg, [], warnings)
    _validate_backup_schedule(cfg, warnings)
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
                f"{key}: expected {expected_type_name(expected_type)}, "
                f"got {type(cfg[key]).__name__}"
            )
    return errors


def check_optional_keys(cfg):
    errors: list[str] = []
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
                allow_empty=bool(CONFIG_FIELDS.get(key) and CONFIG_FIELDS[key].allow_empty),
            )
            continue

        expected_types = (
            expected_type if isinstance(expected_type, tuple) else (expected_type,)
        )
        if not matches_expected_type(value, expected_types):
            expected_names = " or ".join(t.__name__ for t in expected_types)
            errors.append(
                f"{key}: expected {expected_names}, "
                f"got {type(value).__name__}"
            )
    return errors


def _validate_nested_config(cfg: dict[str, object], errors: list[str]) -> None:
    """Validate declared options inside structured configuration groups."""
    for group_name, fields in NESTED_CONFIG_FIELDS.items():
        group = cfg.get(group_name)
        if group is None or not isinstance(group, dict):
            continue

        for key, value in group.items():
            field = fields.get(key)
            dotted_key = f"{group_name}.{key}"
            if field is None:
                errors.append(f"{dotted_key}: unknown setting")
                continue
            if value is None:
                continue
            if field.accepted_type is str:
                _validate_string(
                    value,
                    dotted_key,
                    errors,
                    allow_empty=field.allow_empty,
                )
                continue
            if not matches_expected_type(value, field.accepted_type):
                errors.append(
                    f"{dotted_key}: expected "
                    f"{expected_type_name(field.accepted_type)}, "
                    f"got {type(value).__name__}"
                )


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
    _validate_translate_rate_limit(cfg, errors)
    _validate_room_plugin_defaults(cfg, errors)
    _validate_nested_config(cfg, errors)

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
