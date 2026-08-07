"""Background task inspection commands."""

from __future__ import annotations

from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand
from utils.config import config
from utils.formatting import PageRequest, format_page, parse_page_args, status_icon
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


def _summary_line(tasks: list[TaskInfo]) -> str:
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


def _compact_task_line(task: TaskInfo) -> str:
    """Return one compact task line."""
    heartbeat = f" | heartbeat={task.heartbeat_at}" if task.heartbeat_at and task.status == "running" else ""
    circuit = ""
    if task.circuit_state != "closed":
        circuit = f" | circuit={task.circuit_state}"
    if task.next_restart_at:
        circuit += f" | restart_at={task.next_restart_at}"
    extra = f" | error={task.last_error}" if task.last_error else ""
    kind = f" | kind={task.kind}"
    return f"• {task.plugin}/{task.name} — {status_icon(task.status)} {task.status}{kind}{heartbeat}{circuit}{extra}"


def _full_task_lines(task: TaskInfo) -> list[str]:
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


@command(
    "tasks",
    role=Role.ADMIN,
    aliases=["bot tasks"],
    short="Show supervised background task status.",
    usage="{prefix}tasks [full] [plugin <name>] [running|failed|cancelled|done] [all|page|last] | {prefix}tasks restart <plugin>",
    subcommands=[
        help_subcommand(
            "<list>",
            "{prefix}tasks [full] [plugin <name>] [running|failed|cancelled|done] [all|page|last]",
            "List supervised tasks with optional detail, plugin and status filters.",
            examples=[
                help_example("{prefix}tasks", "Show a compact overview of supervised tasks."),
                help_example("{prefix}tasks plugin rss", "Show only tasks owned by the RSS plugin."),
                help_example("{prefix}tasks failed", "Show only failed background tasks."),
            ],
        ),
        help_subcommand(
            "restart",
            "{prefix}tasks restart <plugin>",
            "Cancel and restart supervised tasks owned by one plugin.",
            examples=[help_example("{prefix}tasks restart rss", "Restart the RSS plugin's supervised tasks.")],
        ),
    ],
    examples=[
        "{prefix}tasks",
        "{prefix}tasks full",
        "{prefix}tasks plugin rss",
        "{prefix}tasks failed",
        "{prefix}tasks restart rss",
    ],
    category="admin",
    context="private chat / MUC PM",
)
async def tasks_command(bot, sender, nick, args, msg, is_room):
    """Show supervised background task status."""
    if args and args[0].lower() == "restart":
        if len(args) != 2:
            bot.reply_usage(msg, f"{_prefix()}tasks restart <plugin>")
            return
        manager = getattr(bot, "bot_plugins", None)
        restarter = getattr(manager, "restart_tasks", None)
        if not callable(restarter):
            bot.reply_warn(msg, "Plugin task restart support is not available.")
            return
        success, text, cancelled = await restarter(args[1].lower())
        prefix = "✅" if success else "🔴"
        bot.reply(msg, f"{prefix} {text}. Cancelled before restart: {cancelled}")
        return

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


@command(
    "tasks list",
    role=Role.ADMIN,
    aliases=["task list"],
    short="Show supervised background tasks.",
    usage="{prefix}tasks list [all|page|last]",
    examples=[
        "{prefix}tasks list",
        "{prefix}tasks list all",
    ],
    category="admin",
    context="private recommended",
)
async def tasks_list_command(bot, sender, nick, args, msg, is_room):
    """Show supervised background tasks."""
    await tasks_command(bot, sender, nick, args, msg, is_room)


@command(
    "tasks failed",
    role=Role.ADMIN,
    aliases=["task failed", "tasks errors"],
    short="Show failed supervised background tasks.",
    usage="{prefix}tasks failed [all|page|last]",
    examples=["{prefix}tasks failed"],
    category="admin",
    context="private recommended",
)
async def tasks_failed_command(bot, sender, nick, args, msg, is_room):
    """Show failed supervised background tasks."""
    await tasks_command(bot, sender, nick, ["failed", *(args or [])], msg, is_room)


@command(
    "tasks stale",
    role=Role.ADMIN,
    aliases=["task stale"],
    short="Show supervised tasks with stale heartbeats.",
    usage="{prefix}tasks stale [all|page|last]",
    examples=["{prefix}tasks stale"],
    category="admin",
    context="private recommended",
)
async def tasks_stale_command(bot, sender, nick, args, msg, is_room):
    """Show supervised tasks with stale heartbeats."""
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        bot.reply_warn(msg, "Task supervisor is not available.")
        return
    stale_getter = getattr(supervisor, "stale_tasks", None)
    if not callable(stale_getter):
        bot.reply_warn(msg, "Task stale detection is not available.")
        return
    try:
        max_age = float(config.get("task_stale_after_seconds", 3600) or 3600)
    except Exception:
        max_age = 3600.0
    stale = stale_getter(max_age_seconds=max_age)
    page_request = parse_page_args(args or [])
    lines = _render_tasks(list(stale), full=False)
    reply = format_page(
        f"🧵 Stale background tasks (> {int(max_age)}s)",
        lines,
        page_request=page_request,
        page_size=12,
        command_hint=f"{_prefix()}tasks stale",
    )
    bot.reply(msg, reply)
