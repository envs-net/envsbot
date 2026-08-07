from __future__ import annotations

from utils import performance


def setup_function():
    performance.reset()


def test_performance_observations_report_average_and_maximum():
    performance.observe("db_lock_wait", 0.010)
    performance.observe("db_lock_wait", 0.030)

    stats = performance.snapshot()["timings"]["db_lock_wait"]

    assert stats["count"] == 2
    assert stats["avg_ms"] == 20.0
    assert stats["max_ms"] == 30.0
    assert stats["last_ms"] == 30.0


def test_grouped_performance_keeps_per_key_statistics():
    performance.observe_group("commands", "doctor", 0.050)
    performance.observe_group("commands", "doctor", 0.150)
    performance.observe_group("commands", "status", 0.010)

    commands = performance.snapshot()["groups"]["commands"]

    assert commands["doctor"]["count"] == 2
    assert commands["doctor"]["avg_ms"] == 100.0
    assert commands["doctor"]["max_ms"] == 150.0
    assert commands["status"]["count"] == 1
