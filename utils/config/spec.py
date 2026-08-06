"""Declarative configuration fields for cross-cutting runtime services.

The older plugin settings predate this specification and remain compatible.
New operational services use one source of truth for defaults, Python config
names, accepted types and restart requirements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigField:
    default: Any
    python_key: str
    accepted_type: type | tuple[type, ...]
    startup_only: bool = False


OPERATIONAL_CONFIG_FIELDS: dict[str, ConfigField] = {
    "database_maintenance_interval_seconds": ConfigField(21600, "DATABASE_MAINTENANCE_INTERVAL_SECONDS", int, True),
    "command_usage_retention_days": ConfigField(365, "COMMAND_USAGE_RETENTION_DAYS", int),
    "outbox_enabled": ConfigField(True, "OUTBOX_ENABLED", bool, True),
    "outbox_poll_seconds": ConfigField(5.0, "OUTBOX_POLL_SECONDS", (int, float), True),
    "outbox_batch_size": ConfigField(20, "OUTBOX_BATCH_SIZE", int, True),
    "outbox_max_attempts": ConfigField(12, "OUTBOX_MAX_ATTEMPTS", int, True),
    "outbox_retry_initial_seconds": ConfigField(30, "OUTBOX_RETRY_INITIAL_SECONDS", int, True),
    "outbox_retry_max_seconds": ConfigField(1800, "OUTBOX_RETRY_MAX_SECONDS", int, True),
    "outbox_inflight_timeout_seconds": ConfigField(300, "OUTBOX_INFLIGHT_TIMEOUT_SECONDS", int, True),
    "watchdog_enabled": ConfigField(True, "WATCHDOG_ENABLED", bool, True),
    "watchdog_interval_seconds": ConfigField(20.0, "WATCHDOG_INTERVAL_SECONDS", (int, float), True),
    "watchdog_lag_warning_seconds": ConfigField(2.0, "WATCHDOG_LAG_WARNING_SECONDS", (int, float), True),
    "watchdog_lag_failure_seconds": ConfigField(30.0, "WATCHDOG_LAG_FAILURE_SECONDS", (int, float), True),
    "task_restart_max_attempts": ConfigField(5, "TASK_RESTART_MAX_ATTEMPTS", int, True),
    "task_restart_initial_seconds": ConfigField(5.0, "TASK_RESTART_INITIAL_SECONDS", (int, float), True),
    "task_restart_max_seconds": ConfigField(300.0, "TASK_RESTART_MAX_SECONDS", (int, float), True),
    "task_restart_reset_seconds": ConfigField(900.0, "TASK_RESTART_RESET_SECONDS", (int, float), True),
    "admin_report_enabled": ConfigField(False, "ADMIN_REPORT_ENABLED", bool),
    "admin_report_jid": ConfigField("", "ADMIN_REPORT_JID", str),
    "admin_report_time": ConfigField("08:00", "ADMIN_REPORT_TIME", str),
    "admin_report_timezone": ConfigField("", "ADMIN_REPORT_TIMEZONE", str),
    "admin_report_backup_smoke_test": ConfigField(False, "ADMIN_REPORT_BACKUP_SMOKE_TEST", bool),
}


def operational_defaults() -> dict[str, Any]:
    return {name: field.default for name, field in OPERATIONAL_CONFIG_FIELDS.items()}


def operational_types() -> dict[str, type | tuple[type, ...]]:
    return {name: field.accepted_type for name, field in OPERATIONAL_CONFIG_FIELDS.items()}


def operational_python_key_map() -> dict[str, str]:
    return {field.python_key: name for name, field in OPERATIONAL_CONFIG_FIELDS.items()}


def operational_startup_only_keys() -> set[str]:
    return {name for name, field in OPERATIONAL_CONFIG_FIELDS.items() if field.startup_only}
