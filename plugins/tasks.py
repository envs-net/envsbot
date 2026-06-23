"""Background task inspection commands."""

from __future__ import annotations

from collections.abc import Iterable

from utils.command import Role, command
from utils.config import config
from utils.formatting import PageRequest, format_page, parse_page_args
from utils.task_supervisor import TaskInfo

PLUGIN_META = {
    "name": "tasks",
    "version": "0.1.0",
    "description": "Inspect supervised background tasks.",
    "category": "core",
}

_STATUS_ORDER = {
    "running": 0,
    "failed": 1,
    "cancelled": 2,
    "done": 3,
}
_STATUS_ALIASES = {
    "run": "running",
    "running": "running",
    "failed": "failed",
    "fail": "failed",
    "error": "failed",
    "errors": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "done": "done",
    "finished": "done",
}


def _prefix() -> str:
    return str(config.get("prefix", ",") or ",")


def _task_sort_key(task: TaskInfo) -> tuple[int, str, str]:
    """Return a stable display sort key for task entries."""
    return (_STATUS_ORDER.get(task.status, 99), task.plugin, task.name)


def _status_counts(tasks: Iterable[TaskInfo]) -> dict[str, int]:
    """Count task states for a concise summary line."""
    counts = {"running": 0, "failed": 0, "cancelled": 0, "done": 0}
    for task in tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    return counts


def _summary_line(tasks: list[TaskInfo]) -> str:
    """Return a readable task state summary."""
    counts = _status_counts(tasks)
    return (
        f"Summary: {counts.get('running', 0)} running, "
        f"{counts.get('failed', 0)} failed, "
        f"{counts.get('cancelled', 0)} cancelled, "
        f"{counts.get('done', 0)} done"
    )


def _compact_task_line(task: TaskInfo) -> str:
    """Return one compact task line."""
    extra = f" | error={task.last_error}" if task.last_error else ""
    return f"• {task.plugin}/{task.name} — {task.status}{extra}"


def _full_task_lines(task: TaskInfo) -> list[str]:
    """Return detailed lines for one task."""
    lines = [
        f"• {task.plugin}/{task.name}",
        f"  status = {task.status}",
        f"  created_at = {task.created_at}",
        f"  done_at = {task.done_at or '-'}",
        f"  cancelled = {task.cancelled}",
    ]
    if task.last_error:
        lines.append(f"  last_error = {task.last_error}")
    return lines


def _render_tasks(tasks: list[TaskInfo], *, full: bool) -> list[str]:
    """Format task entries for command output."""
    if not tasks:
        return ["No supervised tasks found."]

    lines: list[str] = [_summary_line(tasks), ""]
    for task in sorted(tasks, key=_task_sort_key):
        if full:
            lines.extend(_full_task_lines(task))
        else:
            lines.append(_compact_task_line(task))
    return lines


def _filter_tasks(tasks: list[TaskInfo], *, plugin: str | None, status: str | None) -> list[TaskInfo]:
    """Filter tasks by plugin and/or status."""
    filtered = tasks
    if plugin:
        needle = plugin.lower()
        filtered = [task for task in filtered if task.plugin.lower() == needle]
    if status:
        filtered = [task for task in filtered if task.status == status]
    return filtered


def _parse_task_args(args: list[str]) -> tuple[bool, str | None, str | None, PageRequest, str | None]:
    """Parse tasks command arguments.

    Returns ``(full, plugin, status, page_request, error)``.
    """
    remaining = list(args)
    full = False
    plugin = None
    status = None

    if remaining and remaining[0].lower() in {"full", "details", "all-details"}:
        full = True
        remaining.pop(0)

    if remaining and remaining[0].lower() == "plugin":
        remaining.pop(0)
        if not remaining:
            return full, plugin, status, PageRequest(), "missing plugin name"
        plugin = remaining.pop(0)

    if remaining and remaining[0].lower() in _STATUS_ALIASES:
        status = _STATUS_ALIASES[remaining.pop(0).lower()]

    page_request = parse_page_args(remaining)
    return full, plugin, status, page_request, None


@command("tasks", role=Role.ADMIN, aliases=["bot tasks"])
async def tasks_command(bot, sender, nick, args, msg, is_room):
    """Show supervised background task status."""
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        bot.reply_warn(msg, "Task supervisor is not available.")
        return

    full, plugin, status, page_request, error = _parse_task_args(args)
    if error:
        bot.reply_usage(msg, f"{_prefix()}tasks [full] [plugin <name>] [running|failed|cancelled|done] [all|page|last]")
        return

    tasks = supervisor.snapshot(include_done=True)
    filtered = _filter_tasks(tasks, plugin=plugin, status=status)
    title_parts = ["🧵 Background tasks"]
    if plugin:
        title_parts.append(f"plugin={plugin}")
    if status:
        title_parts.append(f"status={status}")

    lines = _render_tasks(filtered, full=full)
    page_size = 20 if full else 12
    reply = format_page(
        " — ".join(title_parts),
        lines,
        page_request=page_request,
        page_size=page_size,
        command_hint=f"{_prefix()}tasks",
    )
    bot.reply(msg, reply)
