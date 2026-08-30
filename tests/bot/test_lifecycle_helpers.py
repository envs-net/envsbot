"""Focused tests for lifecycle helper semantics."""

import pytest

from bot import lifecycle


@pytest.mark.parametrize(
    ("config_obj", "expected"),
    [
        (
            {"restart_notification_file": "/srv/state/restart.json"},
            [
                "/srv/state/restart.json",
                "data/envsbot_restart_notification.json",
                "/tmp/envsbot_restart_notification.json",
            ],
        ),
        (
            {},
            [
                "data/envsbot_restart_notification.json",
                "/tmp/envsbot_restart_notification.json",
            ],
        ),
        (
            {"restart_notification_file": None},
            [
                "data/envsbot_restart_notification.json",
                "/tmp/envsbot_restart_notification.json",
            ],
        ),
        (
            {"restart_notification_file": ""},
            [
                "data/envsbot_restart_notification.json",
                "/tmp/envsbot_restart_notification.json",
            ],
        ),
        (
            {
                "restart_notification_file": "data/envsbot_restart_notification.json",
            },
            [
                "data/envsbot_restart_notification.json",
                "/tmp/envsbot_restart_notification.json",
            ],
        ),
        (
            {
                "restart_notification_file": "/tmp/envsbot_restart_notification.json",
            },
            [
                "/tmp/envsbot_restart_notification.json",
                "data/envsbot_restart_notification.json",
            ],
        ),
        (
            object(),
            [
                "data/envsbot_restart_notification.json",
                "/tmp/envsbot_restart_notification.json",
            ],
        ),
    ],
)
def test_restart_notification_paths_are_ordered_and_deduplicated(config_obj, expected):
    assert lifecycle._restart_notification_paths(config_obj) == expected


def test_version_state_round_trip(tmp_path):
    path = tmp_path / "envsbot_version_state.json"
    lifecycle._write_version_state(
        path,
        {
            "version": "v1.8.2",
            "pending_announcement": {"from": "v1.8.1", "to": "v1.8.2"},
        },
    )

    assert lifecycle._read_version_state(path) == {
        "version": "1.8.2",
        "pending_announcement": {"from": "1.8.1", "to": "1.8.2"},
    }


def test_version_state_missing_file_is_empty(tmp_path):
    assert lifecycle._read_version_state(tmp_path / "missing.json") == {}


@pytest.mark.parametrize(
    ("config_obj", "expected"),
    [
        ({"version_check_notify_jid": "admin@conf.test", "owner": "owner@test"}, "admin@conf.test"),
        ({"version_check_notify_jid": "", "owner": "owner@test"}, "owner@test"),
        ({"owner": " owner@test "}, "owner@test"),
        ({}, ""),
        (object(), ""),
    ],
)
def test_version_notification_target(config_obj, expected):
    assert lifecycle._version_notification_target(config_obj) == expected
