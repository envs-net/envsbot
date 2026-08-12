"""Small bounded in-process latency counters for operator diagnostics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

_MAX_GROUP_KEYS = 256
_ROLLING_WINDOW_SIZE = 256


def _percentile(values: tuple[float, ...], fraction: float) -> float:
    """Return a linearly interpolated percentile from a small bounded sample."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(1.0, max(0.0, fraction))
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


@dataclass
class TimingStats:
    """Lifetime aggregates plus a bounded rolling latency window."""

    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    last_ms: float = 0.0
    samples_ms: deque[float] = field(
        default_factory=lambda: deque(maxlen=_ROLLING_WINDOW_SIZE),
        repr=False,
    )

    def add(self, duration_seconds: float) -> None:
        value = max(0.0, float(duration_seconds) * 1000.0)
        self.count += 1
        self.total_ms += value
        self.max_ms = max(self.max_ms, value)
        self.last_ms = value
        self.samples_ms.append(value)

    def snapshot(self) -> dict[str, float | int]:
        samples = tuple(self.samples_ms)
        return {
            "count": self.count,
            "total_ms": self.total_ms,
            "max_ms": self.max_ms,
            "last_ms": self.last_ms,
            "avg_ms": self.total_ms / self.count if self.count else 0.0,
            "window_count": len(samples),
            "window_size": _ROLLING_WINDOW_SIZE,
            "p50_ms": _percentile(samples, 0.50),
            "p95_ms": _percentile(samples, 0.95),
            "p99_ms": _percentile(samples, 0.99),
        }


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


def snapshot() -> dict[str, Any]:
    """Return a detached diagnostics snapshot."""
    with _LOCK:
        return {
            "window_size": _ROLLING_WINDOW_SIZE,
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
