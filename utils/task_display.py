"""Shared formatting helpers for supervised task status output."""

from __future__ import annotations

from utils.formatting import status_icon
from utils.task_supervisor import TaskInfo

_STATUS_ORDER = {
    "running": 0,
    "failed": 1,
    "cancelled": 2,
    "done": 3,
}


def task_sort_key(task: TaskInfo) -> tuple[int, str, str]:
    """Return a stable display sort key for task entries."""
    return (_STATUS_ORDER.get(task.status, 99), task.plugin, task.name)


def task_summary_line(tasks: list[TaskInfo]) -> str:
    """Return a lifecycle-aware task summary."""
    services_running = sum(
        1 for task in tasks if task.kind == "service" and task.status == "running"
    )
    one_shots_running = sum(
        1 for task in tasks if task.kind != "service" and task.status == "running"
    )
    one_shots_completed = sum(
        1 for task in tasks if task.kind != "service" and task.status == "done"
    )
    failed = sum(1 for task in tasks if task.status == "failed")
    cancelled = sum(1 for task in tasks if task.status == "cancelled")
    service_finished = sum(
        1 for task in tasks if task.kind == "service" and task.status == "done"
    )
    parts = [
        f"{status_icon('running')} {services_running} services running",
        f"{one_shots_running} one-shots running",
        f"{status_icon('done')} {one_shots_completed} one-shots completed",
        f"{status_icon('failed')} {failed} failed",
    ]
    if service_finished:
        parts.append(f"⚠️ {service_finished} services finished")
    if cancelled:
        parts.append(f"{cancelled} cancelled")
    return "Summary: " + " · ".join(parts)


def compact_task_line(task: TaskInfo) -> str:
    """Return one compact task line."""
    heartbeat = (
        f" | heartbeat={task.heartbeat_at}"
        if task.heartbeat_at and task.status == "running"
        else ""
    )
    circuit = ""
    if task.circuit_state != "closed":
        circuit = f" | circuit={task.circuit_state}"
    if task.next_restart_at:
        circuit += f" | restart_at={task.next_restart_at}"
    extra = f" | error={task.last_error}" if task.last_error else ""
    kind = f" | kind={task.kind}"
    return (
        f"• {task.plugin}/{task.name} — {status_icon(task.status)} {task.status}"
        f"{kind}{heartbeat}{circuit}{extra}"
    )


def full_task_lines(task: TaskInfo) -> list[str]:
    """Return detailed lines for one task."""
    lines = [
        f"• {task.plugin}/{task.name}",
        f"  status = {task.status}",
        f"  kind = {task.kind}",
        f"  created_at = {task.created_at}",
        f"  done_at = {task.done_at or '-'}",
        f"  cancelled = {task.cancelled}",
        f"  heartbeat_at = {task.heartbeat_at or '-'}",
        f"  restart_count = {task.restart_count}",
        f"  circuit_state = {task.circuit_state}",
        f"  next_restart_at = {task.next_restart_at or '-'}",
    ]
    if task.last_error:
        lines.append(f"  last_error = {task.last_error}")
    return lines


def render_task_lines(tasks: list[TaskInfo], *, full: bool) -> list[str]:
    """Format task entries consistently for task and status commands."""
    if not tasks:
        return ["No supervised tasks found."]

    lines: list[str] = [task_summary_line(tasks), ""]
    for task in sorted(tasks, key=task_sort_key):
        if full:
            lines.extend(full_task_lines(task))
        else:
            lines.append(compact_task_line(task))
    return lines
