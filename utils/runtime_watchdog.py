"""systemd watchdog integration and event-loop lag diagnostics."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from dataclasses import dataclass, asdict
from typing import Any

log = logging.getLogger(__name__)


def sd_notify(payload: str) -> bool:
    """Send one notification to systemd without requiring python-systemd."""
    address = os.environ.get("NOTIFY_SOCKET", "")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(address)
        sock.sendall(payload.encode("utf-8"))
        return True
    except OSError:
        log.debug("[WATCHDOG] sd_notify failed", exc_info=True)
        return False
    finally:
        sock.close()


def systemd_watchdog_interval(default: float) -> float:
    """Return a safe heartbeat interval derived from WATCHDOG_USEC."""
    try:
        watchdog_usec = int(os.environ.get("WATCHDOG_USEC", "0") or 0)
    except (TypeError, ValueError):
        watchdog_usec = 0
    if watchdog_usec <= 0:
        return max(1.0, float(default))
    return max(1.0, min(float(default), watchdog_usec / 2_000_000.0))


@dataclass
class WatchdogState:
    enabled: bool = False
    systemd_active: bool = False
    worker_running: bool = False
    heartbeats: int = 0
    last_heartbeat_at: int = 0
    last_lag_seconds: float = 0.0
    max_lag_seconds: float = 0.0
    lag_warnings: int = 0
    heartbeat_suppressed: int = 0
    last_error: str | None = None


class RuntimeWatchdog:
    """Monitor event-loop responsiveness and feed systemd's watchdog."""

    def __init__(self, bot: Any):
        self.bot = bot
        self.task: asyncio.Task[Any] | None = None
        self.stop_event = asyncio.Event()
        self.state = WatchdogState()

    async def start(self) -> None:
        config = getattr(self.bot, "config", {}) or {}
        configured = bool(config.get("watchdog_enabled", True))
        self.state.systemd_active = bool(
            os.environ.get("NOTIFY_SOCKET") and os.environ.get("WATCHDOG_USEC")
        )
        # A unit with WatchdogSec requires heartbeats. Keep it active even when
        # the application setting was disabled, otherwise systemd would restart
        # a healthy process forever. Disable WatchdogSec in the unit as well to
        # turn monitoring off completely.
        self.state.enabled = configured or self.state.systemd_active
        sd_notify("READY=1\nSTATUS=EnvsBot startup complete")
        if not self.state.enabled or self.task is not None:
            return
        self.stop_event = asyncio.Event()
        supervisor = getattr(self.bot, "tasks", None)
        if supervisor is not None:
            self.task = supervisor.create(
                "_runtime",
                self._run(),
                name="runtime-watchdog",
            )
        else:
            self.task = asyncio.create_task(self._run(), name="runtime-watchdog")
        self.state.worker_running = True
        sd_notify("READY=1\nSTATUS=EnvsBot started and monitoring event-loop health")

    async def stop(self) -> None:
        self.stop_event.set()
        task = self.task
        self.task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.state.worker_running = False
        sd_notify("STOPPING=1\nSTATUS=EnvsBot shutting down")

    async def _run(self) -> None:
        config = getattr(self.bot, "config", {}) or {}
        configured_interval = max(
            1.0,
            float(config.get("watchdog_interval_seconds", 20) or 20),
        )
        interval = systemd_watchdog_interval(configured_interval)
        warning_threshold = max(
            0.1,
            float(config.get("watchdog_lag_warning_seconds", 2.0) or 2.0),
        )
        failure_threshold = max(
            warning_threshold,
            float(config.get("watchdog_lag_failure_seconds", 30.0) or 30.0),
        )
        loop = asyncio.get_running_loop()
        expected = loop.time() + interval
        try:
            while not self.stop_event.is_set():
                stop_requested = True
                try:
                    await asyncio.wait_for(
                        self.stop_event.wait(),
                        timeout=interval,
                    )
                except asyncio.TimeoutError:
                    stop_requested = False
                if stop_requested:
                    break

                now = loop.time()
                lag = max(0.0, now - expected)
                expected = now + interval
                self.state.last_lag_seconds = lag
                self.state.max_lag_seconds = max(self.state.max_lag_seconds, lag)
                if lag >= warning_threshold:
                    self.state.lag_warnings += 1
                    log.warning(
                        "[WATCHDOG] Event-loop lag %.3fs exceeds %.3fs",
                        lag,
                        warning_threshold,
                    )

                if lag >= failure_threshold:
                    self.state.heartbeat_suppressed += 1
                    sd_notify(
                        "STATUS=EnvsBot unhealthy: "
                        f"event-loop lag {lag:.3f}s; watchdog heartbeat suppressed"
                    )
                    continue

                payload = (
                    "WATCHDOG=1\n"
                    f"STATUS=EnvsBot healthy; event-loop lag {lag:.3f}s"
                )
                if sd_notify(payload):
                    self.state.heartbeats += 1
                    self.state.last_heartbeat_at = int(time.time())
                self.state.last_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.last_error = f"{type(exc).__name__}: {exc}"
            log.exception("[WATCHDOG] Runtime watchdog failed")
            raise
        finally:
            self.state.worker_running = False

    def runtime_state(self) -> dict[str, Any]:
        return asdict(self.state)
