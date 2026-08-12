from __future__ import annotations

import pytest

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


def test_rolling_percentiles_use_bounded_recent_window():
    for value_ms in range(1, 301):
        performance.observe("commands", value_ms / 1000.0)

    stats = performance.snapshot()["timings"]["commands"]

    assert stats["count"] == 300
    assert stats["window_count"] == 256
    assert stats["window_size"] == 256
    # The retained window is 45..300 ms, so recent percentiles must not be
    # dragged down by the first 44 lifetime samples.
    assert 171.0 <= stats["p50_ms"] <= 174.0
    assert 286.0 <= stats["p95_ms"] <= 289.0
    assert 297.0 <= stats["p99_ms"] <= 299.0


def test_grouped_percentiles_are_reported_per_key():
    for value in (0.010, 0.020, 0.030, 0.040):
        performance.observe_group("commands", "doctor", value)

    stats = performance.snapshot()["groups"]["commands"]["doctor"]

    assert stats["p50_ms"] == 25.0
    assert stats["p95_ms"] == 38.5
    assert stats["p99_ms"] == pytest.approx(39.7)
