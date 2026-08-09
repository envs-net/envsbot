from types import SimpleNamespace

import pytest

import utils.runtime_watchdog as watchdog


def test_systemd_watchdog_interval_uses_half_watchdog_period(monkeypatch):
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    assert watchdog.systemd_watchdog_interval(20) == 20
    assert watchdog.systemd_watchdog_interval(40) == 30


def test_sd_notify_without_socket_is_noop(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert watchdog.sd_notify("READY=1") is False


@pytest.mark.asyncio
async def test_watchdog_disabled_still_sends_ready(monkeypatch):
    notifications = []
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    monkeypatch.setattr(watchdog, "sd_notify", lambda payload: notifications.append(payload) or False)
    runtime = watchdog.RuntimeWatchdog(SimpleNamespace(config={"watchdog_enabled": False}))

    await runtime.start()

    assert runtime.task is None
    assert runtime.state.enabled is False
    assert notifications == []

    assert runtime.notify_ready() is False
    assert notifications == ["READY=1\nSTATUS=EnvsBot startup complete"]


@pytest.mark.asyncio
async def test_systemd_watchdog_forces_worker_when_unit_requires_it(monkeypatch):
    notifications = []
    monkeypatch.setenv("NOTIFY_SOCKET", "/tmp/notify")
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    monkeypatch.setattr(watchdog, "sd_notify", lambda payload: notifications.append(payload) or True)
    runtime = watchdog.RuntimeWatchdog(
        SimpleNamespace(config={"watchdog_enabled": False}, tasks=None)
    )

    await runtime.start()
    try:
        assert runtime.state.enabled is True
        assert runtime.state.systemd_active is True
        assert runtime.task is not None
        assert notifications == []
        assert runtime.notify_ready() is True
        assert notifications == [
            "READY=1\nSTATUS=EnvsBot started and monitoring event-loop health"
        ]
    finally:
        await runtime.stop()

@pytest.mark.asyncio
async def test_watchdog_uses_resilient_service_supervision(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    monkeypatch.setattr(watchdog, "sd_notify", lambda _payload: False)
    supervisor = SimpleNamespace(create_resilient=MagicMock(return_value=MagicMock()))
    runtime = watchdog.RuntimeWatchdog(
        SimpleNamespace(config={"watchdog_enabled": True}, tasks=supervisor)
    )

    await runtime.start()

    supervisor.create_resilient.assert_called_once_with(
        "_runtime",
        runtime._run,
        name="runtime-watchdog",
        service=True,
    )
