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
