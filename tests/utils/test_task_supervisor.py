import asyncio
from types import SimpleNamespace

from unittest.mock import Mock

import pytest

from utils import task_supervisor as ts
from utils.task_supervisor import TaskSupervisor, create_plugin_task


def test_asyncio_create_task_supports_name_branches(monkeypatch):
    def signature_with_name(_obj):
        return SimpleNamespace(parameters={"name": object()})

    monkeypatch.setattr(ts.inspect, "signature", signature_with_name)
    assert ts._asyncio_create_task_supports_name() is True

    def signature_without_name(_obj):
        return SimpleNamespace(parameters={})

    monkeypatch.setattr(ts.inspect, "signature", signature_without_name)
    assert ts._asyncio_create_task_supports_name() is False


def test_asyncio_create_task_supports_name_signature_failures(monkeypatch):
    def raise_type_error(_obj):
        raise TypeError("no signature")

    monkeypatch.setattr(ts.inspect, "signature", raise_type_error)
    assert ts._asyncio_create_task_supports_name() is True

    def raise_value_error(_obj):
        raise ValueError("no signature")

    monkeypatch.setattr(ts.inspect, "signature", raise_value_error)
    assert ts._asyncio_create_task_supports_name() is True

    def raise_runtime_error(_obj):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(ts.inspect, "signature", raise_runtime_error)
    with pytest.raises(RuntimeError, match="unexpected failure"):
        ts._asyncio_create_task_supports_name()


@pytest.mark.asyncio
async def test_create_plugin_task_uses_valid_manager_creator():
    calls = []

    class Manager:
        def create_task(self, plugin_name, coro, *, name=None):
            calls.append((plugin_name, name))
            return create_plugin_task(SimpleNamespace(), plugin_name, coro, name=name)

    async def marker():
        return "ok"

    task = create_plugin_task(
        SimpleNamespace(bot_plugins=Manager()),
        "example",
        marker(),
        name="example-task",
    )

    assert await task == "ok"
    assert calls == [("example", "example-task")]


@pytest.mark.asyncio
async def test_create_plugin_task_ignores_mock_creator():
    creator = Mock()

    async def marker():
        return "ok"

    task = create_plugin_task(
        SimpleNamespace(bot_plugins=SimpleNamespace(create_task=creator)),
        "example",
        marker(),
        name="example-task",
    )

    assert await task == "ok"
    creator.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_plugin_removes_cancelled_tasks_from_tracking():
    supervisor = TaskSupervisor()

    async def sleeper():
        while True:
            await asyncio.sleep(60)

    supervisor.create("example", sleeper(), name="example-sleeper")

    assert await supervisor.cancel_plugin("example", timeout=1.0) == 1
    assert supervisor.snapshot(include_done=True) == []
    assert supervisor.summary() == (0, 0, 0)


@pytest.mark.asyncio
async def test_cancel_task_removes_single_cancelled_task_from_tracking():
    supervisor = TaskSupervisor()

    async def sleeper():
        while True:
            await asyncio.sleep(60)

    alpha = supervisor.create("example", sleeper(), name="alpha")
    beta = supervisor.create("example", sleeper(), name="beta")

    assert await supervisor.cancel_task(alpha, timeout=1.0) is True

    snapshot = supervisor.snapshot(include_done=True)
    assert [item.name for item in snapshot] == ["beta"]
    assert snapshot[0].status == "running"

    await supervisor.cancel_task(beta, timeout=1.0)

@pytest.mark.asyncio
async def test_snapshot_includes_completed_tasks_by_default():
    supervisor = TaskSupervisor()

    async def marker():
        return "ok"

    task = supervisor.create("example", marker(), name="example-task")
    assert await task == "ok"

    items = supervisor.snapshot()
    assert len(items) == 1
    assert items[0].status == "done"

@pytest.mark.asyncio
async def test_snapshot_without_done_keeps_cancelled_and_failed_tasks():
    supervisor = TaskSupervisor()

    async def quick_success():
        return "ok"

    async def quick_failure():
        raise RuntimeError("boom")

    async def sleeper():
        while True:
            await asyncio.sleep(60)

    success_task = supervisor.create("example", quick_success(), name="success")
    failure_task = supervisor.create("example", quick_failure(), name="failure")
    cancelled_task = supervisor.create("example", sleeper(), name="cancelled")

    assert await success_task == "ok"

    failure_result = await asyncio.gather(failure_task, return_exceptions=True)
    assert isinstance(failure_result[0], RuntimeError)

    cancelled_task.cancel()
    cancelled_result = await asyncio.gather(cancelled_task, return_exceptions=True)
    assert isinstance(cancelled_result[0], asyncio.CancelledError)

    items = supervisor.snapshot(include_done=False)
    statuses = {item.name: item.status for item in items}

    assert "success" not in statuses
    assert statuses == {"cancelled": "cancelled", "failure": "failed"}


@pytest.mark.asyncio
async def test_task_supervisor_failure_summary_and_cancel_all():
    supervisor = TaskSupervisor()

    async def failing():
        raise RuntimeError("boom")

    async def sleeper():
        while True:
            await asyncio.sleep(60)

    failed_task = supervisor.create("alpha", failing(), name="boom-task")
    beta_task = supervisor.create("beta", sleeper(), name="sleep-task")

    result = await asyncio.gather(failed_task, return_exceptions=True)
    assert isinstance(result[0], RuntimeError)

    snapshot = supervisor.snapshot(include_done=True)
    failed = [item for item in snapshot if item.name == "boom-task"][0]
    assert failed.status == "failed"
    assert failed.last_error == "RuntimeError: boom"
    assert supervisor.summary()[1] == 1

    cancelled = await supervisor.cancel_all(timeout=1.0)
    assert cancelled == 1
    assert beta_task.cancelled()
    remaining = supervisor.snapshot(include_done=False)
    assert [item.name for item in remaining] == ["boom-task"]


@pytest.mark.asyncio
async def test_task_supervisor_ignores_untracked_done_task_and_creator_shapes(caplog):
    caplog.set_level("DEBUG", logger="utils.task_supervisor")

    async def marker():
        return "ok"

    task = asyncio.create_task(marker(), name="orphan")
    assert await task == "ok"
    supervisor = TaskSupervisor()
    supervisor._on_task_done(task)
    assert "untracked task" in caplog.text

    def no_name(plugin, coro):
        return coro

    assert ts._is_plugin_task_creator(no_name) is False
    assert ts._is_plugin_task_creator(object()) is False

    class CallableNoSignature:
        __signature__ = "broken"

        def __call__(self, *args, **kwargs):
            return None

    assert ts._is_plugin_task_creator(CallableNoSignature()) is False
