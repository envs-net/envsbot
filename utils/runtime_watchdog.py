"""envsbot compatibility facade for the shared runtime watchdog."""
from __future__ import annotations

from typing import Any

from envs_xmpp_core.runtime.systemd import sd_notify as _core_sd_notify
from envs_xmpp_core.runtime.systemd import systemd_watchdog_interval
from envs_xmpp_core.runtime.watchdog import (
    RuntimeWatchdog as CoreRuntimeWatchdog,
)
from envs_xmpp_core.runtime.watchdog import (
    WatchdogOptions,
    WatchdogState,
)

__all__ = ["RuntimeWatchdog", "WatchdogState", "sd_notify", "systemd_watchdog_interval"]


def sd_notify(payload: str) -> bool:
    return _core_sd_notify(payload)


def _notify(payload: str) -> bool:
    """Resolve the public notifier lazily so monkeypatching remains supported."""
    return sd_notify(payload)


class RuntimeWatchdog(CoreRuntimeWatchdog):
    """Preserve envsbot's bot-object constructor over the neutral core."""

    def __init__(self, bot: Any):
        self.bot = bot
        config = getattr(bot, "config", {}) or {}
        alerts = getattr(bot, "alerts", None)
        on_lag = getattr(alerts, "report_event_loop_lag", None)
        super().__init__(
            service_name="EnvsBot",
            options=WatchdogOptions(
                enabled=bool(config.get("watchdog_enabled", True)),
                interval_seconds=float(config.get("watchdog_interval_seconds", 20) or 20),
                lag_warning_seconds=float(config.get("watchdog_lag_warning_seconds", 2.0) or 2.0),
                lag_failure_seconds=float(config.get("watchdog_lag_failure_seconds", 30.0) or 30.0),
            ),
            supervisor=getattr(bot, "tasks", None),
            ready_event=getattr(bot, "runtime_ready", None),
            on_lag=on_lag if callable(on_lag) else None,
            notifier=_notify,
        )
