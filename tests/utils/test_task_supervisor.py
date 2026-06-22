import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from utils.task_supervisor import TaskSupervisor, create_plugin_task


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
    with pytest.raises(RuntimeError):
        await failure_task
    cancelled_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_task

    items = supervisor.snapshot(include_done=False)
    statuses = {item.name: item.status for item in items}

    assert statuses == {"cancelled": "cancelled", "failure": "failed"}
