"""Small in-process performance counters for operator diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock

_MAX_GROUP_KEYS = 256


@dataclass
class TimingStats:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    last_ms: float = 0.0

    def add(self, duration_seconds: float) -> None:
        value = max(0.0, float(duration_seconds) * 1000.0)
        self.count += 1
        self.total_ms += value
        self.max_ms = max(self.max_ms, value)
        self.last_ms = value

    def snapshot(self) -> dict[str, float | int]:
        data = asdict(self)
        data["avg_ms"] = self.total_ms / self.count if self.count else 0.0
        return data


_LOCK = Lock()
_TIMINGS: dict[str, TimingStats] = {}
_GROUPED: dict[str, dict[str, TimingStats]] = {}


def observe(name: str, duration_seconds: float) -> None:
    """Record one duration under a stable metric name."""
    key = str(name).strip()
    if not key:
        return
    with _LOCK:
        _TIMINGS.setdefault(key, TimingStats()).add(duration_seconds)


def observe_group(group: str, key: str, duration_seconds: float) -> None:
    """Record one bounded per-key duration, e.g. command or RSS host."""
    group_name = str(group).strip()
    item = str(key).strip() or "unknown"
    if not group_name:
        return
    with _LOCK:
        values = _GROUPED.setdefault(group_name, {})
        if item not in values and len(values) >= _MAX_GROUP_KEYS:
            item = "other"
        values.setdefault(item, TimingStats()).add(duration_seconds)


def snapshot() -> dict[str, dict]:
    """Return a detached diagnostics snapshot."""
    with _LOCK:
        return {
            "timings": {name: stats.snapshot() for name, stats in _TIMINGS.items()},
            "groups": {
                group: {key: stats.snapshot() for key, stats in values.items()}
                for group, values in _GROUPED.items()
            },
        }


def reset() -> None:
    """Clear counters; intended for tests and controlled diagnostics."""
    with _LOCK:
        _TIMINGS.clear()
        _GROUPED.clear()
