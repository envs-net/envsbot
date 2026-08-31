from __future__ import annotations

import pytest

from bot import lifecycle


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (
            "1.8.3",
            "1.8.4",
            "⬆️ EnvsBot updated successfully: v1.8.3 → v1.8.4",
        ),
        (
            "1.8.4",
            "1.8.3",
            "⬇️ EnvsBot downgraded successfully: v1.8.4 → v1.8.3",
        ),
    ],
)
def test_version_change_message_distinguishes_upgrade_and_downgrade(
    previous,
    current,
    expected,
):
    assert lifecycle._version_change_message(previous, current) == expected


def test_pending_version_change_extends_from_earliest_undelivered_version():
    assert lifecycle._merge_pending_version_change(
        "1.8.3",
        "1.8.4",
        {"from": "1.8.2", "to": "1.8.3"},
    ) == {"from": "1.8.2", "to": "1.8.4"}


def test_pending_version_change_is_kept_on_same_version_restart():
    pending = {"from": "1.8.2", "to": "1.8.3"}

    assert lifecycle._merge_pending_version_change(
        "1.8.3",
        "1.8.3",
        pending,
    ) == pending


def test_pending_version_change_clears_when_version_returns_to_original():
    assert lifecycle._merge_pending_version_change(
        "1.8.3",
        "1.8.2",
        {"from": "1.8.2", "to": "1.8.3"},
    ) is None


def test_stale_pending_version_change_is_not_chained():
    assert lifecycle._merge_pending_version_change(
        "1.8.3",
        "1.8.4",
        {"from": "1.7.9", "to": "1.8.1"},
    ) == {"from": "1.8.3", "to": "1.8.4"}


@pytest.mark.parametrize(
    ("previous", "current", "pending"),
    [
        ("", "1.8.4", None),
        ("unknown", "1.8.4", None),
        ("1.8.4", "unknown", None),
    ],
)
def test_pending_version_change_ignores_unknown_baselines(previous, current, pending):
    assert lifecycle._merge_pending_version_change(previous, current, pending) is None


@pytest.mark.asyncio
async def test_finalize_version_state_extends_existing_pending_chain(
    monkeypatch,
    tmp_path,
):
    state_path = tmp_path / "envsbot_version_state.json"
    lifecycle._write_version_state(
        state_path,
        {
            "version": "1.8.3",
            "pending_announcement": {"from": "1.8.2", "to": "1.8.3"},
        },
    )
    monkeypatch.setattr(
        lifecycle,
        "_version_state_path",
        lambda config_obj: state_path,
    )
    scheduled = []

    def fake_create_plugin_task(owner, plugin, coro, *, name=None):
        scheduled.append((owner, plugin, name))
        coro.close()
        return None

    monkeypatch.setattr(
        "utils.task_supervisor.create_plugin_task",
        fake_create_plugin_task,
    )

    class Bot(lifecycle.LifecycleMixin):
        config = {}
        version = "1.8.4"
        _restart_version_change_announced = None

    bot = Bot()
    await bot._finalize_successful_startup_version()

    assert lifecycle._read_version_state(state_path) == {
        "version": "1.8.4",
        "pending_announcement": {"from": "1.8.2", "to": "1.8.4"},
    }
    assert scheduled == [(bot, "_runtime", "version-change-announcement")]
