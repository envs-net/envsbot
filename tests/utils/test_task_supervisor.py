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
    ts._asyncio_create_task_supports_name.cache_clear()
    assert ts._asyncio_create_task_supports_name() is True

    def signature_without_name(_obj):
        return SimpleNamespace(parameters={})

    monkeypatch.setattr(ts.inspect, "signature", signature_without_name)
    ts._asyncio_create_task_supports_name.cache_clear()
    assert ts._asyncio_create_task_supports_name() is False
    ts._asyncio_create_task_supports_name.cache_clear()


def test_asyncio_create_task_supports_name_signature_failures(monkeypatch):
    def raise_type_error(_obj):
        raise TypeError("no signature")

    monkeypatch.setattr(ts.inspect, "signature", raise_type_error)
    ts._asyncio_create_task_supports_name.cache_clear()
    assert ts._asyncio_create_task_supports_name() is True

    def raise_value_error(_obj):
        raise ValueError("no signature")

    monkeypatch.setattr(ts.inspect, "signature", raise_value_error)
    ts._asyncio_create_task_supports_name.cache_clear()
    assert ts._asyncio_create_task_supports_name() is True

    def raise_runtime_error(_obj):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(ts.inspect, "signature", raise_runtime_error)
    ts._asyncio_create_task_supports_name.cache_clear()
    with pytest.raises(RuntimeError, match="unexpected failure"):
        ts._asyncio_create_task_supports_name()
    ts._asyncio_create_task_supports_name.cache_clear()


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
async def test_create_plugin_task_closes_coroutine_when_creator_fails():
    created_coroutines = []

    class Manager:
        def create_task(self, _plugin_name, coro, *, name=None):
            created_coroutines.append(coro)
            raise RuntimeError("task creation failed")

    async def marker():
        return "unused"

    with pytest.raises(RuntimeError, match="task creation failed"):
        create_plugin_task(
            SimpleNamespace(bot_plugins=Manager()),
            "example",
            marker(),
            name="example-task",
        )

    assert len(created_coroutines) == 1
    assert created_coroutines[0].cr_frame is None


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
async def test_cancel_plugin_prunes_tasks_cancelled_by_plugin_hook():
    supervisor = TaskSupervisor()

    async def sleeper():
        while True:
            await asyncio.sleep(60)

    task = supervisor.create("example", sleeper(), name="hook-cancelled")
    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    await asyncio.sleep(0)

    assert supervisor.snapshot(include_done=True)[0].status == "cancelled"
    assert await supervisor.cancel_plugin("example", timeout=1.0) == 0
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
async def test_cancel_task_keeps_timed_out_task_tracked(caplog):
    caplog.set_level("WARNING", logger="utils.task_supervisor")
    supervisor = TaskSupervisor()
    release = asyncio.Event()

    async def stubborn():
        while not release.is_set():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                continue

    task = supervisor.create("example", stubborn(), name="stubborn")
    await asyncio.sleep(0)

    assert await supervisor.cancel_task(task, timeout=0.01) is True
    snapshot = supervisor.snapshot(include_done=False)
    assert [item.name for item in snapshot] == ["stubborn"]
    assert snapshot[0].status == "running"
    assert "Plugin task did not stop in time: stubborn" in caplog.text

    release.set()
    task.cancel()
    done, pending = await asyncio.wait({task}, timeout=1.0)
    assert task in done
    assert not pending
    supervisor._prune_task_unless_failed(task)
    assert supervisor.snapshot(include_done=True) == []


@pytest.mark.asyncio
async def test_cancel_plugin_uses_wait_and_keeps_pending_tasks(caplog):
    caplog.set_level("WARNING", logger="utils.task_supervisor")
    supervisor = TaskSupervisor()
    release = asyncio.Event()

    async def stubborn():
        while not release.is_set():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                continue

    async def sleeper():
        while True:
            await asyncio.sleep(60)

    stubborn_task = supervisor.create("example", stubborn(), name="stubborn")
    supervisor.create("example", sleeper(), name="normal")
    await asyncio.sleep(0)

    assert await supervisor.cancel_plugin("example", timeout=0.01) == 2
    snapshot = supervisor.snapshot(include_done=True)
    assert [item.name for item in snapshot] == ["stubborn"]
    assert snapshot[0].status == "running"
    assert "Plugin task did not stop in time: stubborn" in caplog.text

    release.set()
    stubborn_task.cancel()
    done, pending = await asyncio.wait({stubborn_task}, timeout=1.0)
    assert stubborn_task in done
    assert not pending
    supervisor._prune_task_unless_failed(stubborn_task)
    assert supervisor.snapshot(include_done=True) == []

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
async def test_snapshot_without_done_keeps_failed_tasks_only():
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
    assert "cancelled" not in statuses
    assert statuses == {"failure": "failed"}


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


@pytest.mark.asyncio
async def test_prune_task_unless_failed_removes_success_and_cancelled_tasks():
    supervisor = TaskSupervisor()

    async def marker():
        return "ok"

    async def sleeper():
        while True:
            await asyncio.sleep(60)

    success_task = supervisor.create("example", marker(), name="success")
    assert await success_task == "ok"
    await asyncio.sleep(0)

    supervisor._prune_task_unless_failed(success_task)
    assert success_task not in supervisor._tasks
    assert "example" not in supervisor._by_plugin

    cancelled_task = supervisor.create("example", sleeper(), name="cancelled")
    cancelled_task.cancel()
    cancelled_result = await asyncio.gather(cancelled_task, return_exceptions=True)
    assert isinstance(cancelled_result[0], asyncio.CancelledError)
    await asyncio.sleep(0)

    supervisor._prune_task_unless_failed(cancelled_task)
    assert cancelled_task not in supervisor._tasks
    assert "example" not in supervisor._by_plugin


@pytest.mark.asyncio
async def test_prune_task_unless_failed_keeps_failed_tasks_for_diagnostics():
    supervisor = TaskSupervisor()

    async def failing():
        raise RuntimeError("boom")

    failed_task = supervisor.create("example", failing(), name="failure")
    failed_result = await asyncio.gather(failed_task, return_exceptions=True)
    assert isinstance(failed_result[0], RuntimeError)
    await asyncio.sleep(0)

    supervisor._prune_task_unless_failed(failed_task)

    assert failed_task in supervisor._tasks
    assert supervisor._tasks[failed_task]["last_error"] == "RuntimeError: boom"
    snapshot = supervisor.snapshot(include_done=False)
    assert len(snapshot) == 1
    assert snapshot[0].name == "failure"
    assert snapshot[0].status == "failed"


@pytest.mark.asyncio
async def test_prune_task_unless_failed_ignores_unknown_tasks():
    supervisor = TaskSupervisor()

    async def marker():
        return "ok"

    unknown_task = asyncio.create_task(marker(), name="unknown")
    assert await unknown_task == "ok"

    supervisor._prune_task_unless_failed(unknown_task)
    assert supervisor.snapshot() == []

@pytest.mark.asyncio
async def test_heartbeat_touch_and_stale_task_edges(monkeypatch):
    supervisor = TaskSupervisor()

    async def sleeper():
        while True:
            await asyncio.sleep(60)

    task = supervisor.create("alpha", sleeper(), name="main")
    initial_snapshot = supervisor.snapshot(include_done=False)[0]
    assert initial_snapshot.heartbeat_at is None
    assert supervisor.stale_tasks(max_age_seconds=0) == []

    assert supervisor.heartbeat("alpha", name="main") is True
    assert supervisor.heartbeat("alpha", name="missing") is False
    assert supervisor.heartbeat("missing") is False

    first_snapshot = supervisor.snapshot(include_done=False)[0]
    assert first_snapshot.plugin == "alpha"
    assert first_snapshot.name == "main"
    assert first_snapshot.heartbeat_at is not None

    # Force a stale heartbeat and verify it is reported for aware datetimes.
    supervisor._tasks[task]["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
    stale = supervisor.stale_tasks(max_age_seconds=1)
    assert [item.name for item in stale] == ["main"]

    assert supervisor.touch(task) is True
    assert supervisor.stale_tasks(max_age_seconds=3600) == []

    # Malformed heartbeat timestamps are treated as stale rather than crashing.
    supervisor._tasks[task]["heartbeat_at"] = "not-a-date"
    assert [item.name for item in supervisor.stale_tasks(max_age_seconds=3600)] == ["main"]

    assert await supervisor.cancel_task(task, timeout=1.0) is True
    assert supervisor.touch(task) is False


@pytest.mark.asyncio
async def test_stale_tasks_ignores_done_tasks_and_missing_heartbeats():
    supervisor = TaskSupervisor()

    async def quick():
        return "ok"

    async def sleeper():
        while True:
            await asyncio.sleep(60)

    done_task = supervisor.create("alpha", quick(), name="done")
    assert await done_task == "ok"
    running_without_heartbeat = supervisor.create("alpha", sleeper(), name="no-heartbeat")
    supervisor._tasks[running_without_heartbeat]["heartbeat_at"] = None

    assert supervisor.stale_tasks(max_age_seconds=0) == []
    await supervisor.cancel_task(running_without_heartbeat, timeout=1.0)
