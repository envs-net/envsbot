"""Operator-facing formatting helpers for supervised task output."""

from __future__ import annotations

from envs_xmpp_core.presentation import (
    TaskView,
    normalize_tasks,
    render_task_entry,
    render_task_summary,
    summarize_tasks,
)

from utils.task_supervisor import TaskInfo


def task_views(
    tasks: list[TaskInfo],
    *,
    stale_ids: set[tuple[str, str]] | None = None,
) -> list[TaskView]:
    """Normalize envsbot task facades for the shared presentation layer."""
    return normalize_tasks(tasks, stale_ids=stale_ids)


def task_summary_line(tasks: list[TaskInfo]) -> str:
    """Return a compact lifecycle summary for compatibility callers."""
    summary = summarize_tasks(task_views(tasks))
    parts = [
        f"✅ {summary.services_running} services running",
        f"{summary.one_shots_running} one-shots running",
        f"☑️ {summary.one_shots_completed} one-shots completed",
        f"❌ {summary.failed} failed",
    ]
    if summary.services_finished:
        parts.append(f"⚠️ {summary.services_finished} services finished")
    if summary.cancelled:
        parts.append(f"{summary.cancelled} cancelled")
    return "Summary: " + " · ".join(parts)


def compact_task_line(task: TaskInfo) -> str:
    """Return one compact task block using the shared renderer."""
    return render_task_entry(task_views([task])[0], full=False)


def full_task_lines(task: TaskInfo) -> list[str]:
    """Return detailed lines for one task for compatibility callers."""
    return render_task_entry(task_views([task])[0], full=True).splitlines()


def render_task_lines(tasks: list[TaskInfo], *, full: bool) -> list[str]:
    """Format task entries consistently for task and status commands."""
    views = task_views(tasks)
    if not views:
        return ["No supervised tasks found."]
    lines = render_task_summary(views)
    lines.append("")
    lines.extend(render_task_entry(view, full=full) for view in views)
    return lines
