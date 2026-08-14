"""Background task inspection commands."""

from __future__ import annotations

from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand
from utils.config import config
from utils.formatting import PageRequest, format_page, parse_page_args
from utils.task_display import render_task_lines
from utils.task_supervisor import TaskInfo

PLUGIN_META = {
    "name": "tasks",
    "version": "0.1.0",
    "description": "Inspect supervised background tasks.",
    "category": "core",
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

    lines = render_task_lines(filtered, full=full)
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
    lines = render_task_lines(list(stale), full=False)
    reply = format_page(
        f"🧵 Stale background tasks (> {int(max_age)}s)",
        lines,
        page_request=page_request,
        page_size=12,
        command_hint=f"{_prefix()}tasks stale",
    )
    bot.reply(msg, reply)
