"""Background task inspection commands."""

from __future__ import annotations

from envs_xmpp_core.presentation import (
    TaskListRequest,
    filter_task_views,
    normalize_tasks,
    parse_task_list_request,
    render_task_entry,
    render_task_summary,
    render_watchdog_lines,
)

from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand
from utils.config import config
from utils.formatting import format_page

PLUGIN_META = {
    "name": "tasks",
    "version": "0.2.0",
    "description": "Inspect supervised background tasks.",
    "category": "core",
}


def _prefix() -> str:
    return str(config.get("prefix", ",") or ",")


def _stale_after() -> float:
    try:
        return float(config.get("task_stale_after_seconds", 3600) or 3600)
    except (TypeError, ValueError):
        return 3600.0


def _stale_ids(supervisor) -> set[tuple[str, str]]:
    stale_getter = getattr(supervisor, "stale_tasks", None)
    if not callable(stale_getter):
        return set()
    return {
        (task.plugin, task.name)
        for task in stale_getter(max_age_seconds=_stale_after())
    }


def _task_title(request: TaskListRequest) -> str:
    parts = ["🧵 Background Tasks"]
    if request.scope:
        parts.append(f"scope={request.scope}")
    if request.mode not in {"overview", "inventory"}:
        parts.append(request.mode)
    if request.full:
        parts.append("full")
    return " — ".join(parts)


@command(
    "tasks",
    role=Role.ADMIN,
    aliases=["bot tasks"],
    short="Show supervised background task status.",
    usage=(
        "{prefix}tasks [all|full|failed|stale|restarting|restarted|problems|running|done|cancelled] "
        "[scope|plugin <name>] [<page>|last] | {prefix}tasks show <scope>/<task> | "
        "{prefix}tasks restart <plugin>"
    ),
    subcommands=[
        help_subcommand(
            "<list>",
            "{prefix}tasks [all|full|failed|stale|restarting|restarted|problems] [scope <name>] [<page>|last]",
            "Show a health overview or filtered supervised-task inventory.",
            examples=[
                help_example("{prefix}tasks", "Show task health, scopes and watchdog state."),
                help_example("{prefix}tasks all", "Show the complete compact task inventory."),
                help_example("{prefix}tasks problems", "Show only tasks needing attention."),
                help_example("{prefix}tasks scope rss", "Show tasks owned by the RSS scope."),
                help_example("{prefix}tasks show rss/feed-checker", "Show full detail for one task."),
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
        "{prefix}tasks all",
        "{prefix}tasks full",
        "{prefix}tasks problems",
        "{prefix}tasks scope rss",
        "{prefix}tasks show rss/feed-checker",
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

    request = parse_task_list_request(args or [])
    if request.error:
        bot.reply_usage(
            msg,
            f"{_prefix()}tasks [all|full|failed|stale|restarting|restarted|problems|running|done|cancelled] "
            "[scope|plugin <name>] [<page>|last]",
        )
        return

    stale_ids = _stale_ids(supervisor)
    if request.mode == "stale":
        stale_getter = getattr(supervisor, "stale_tasks", None)
        stale_tasks = list(stale_getter(max_age_seconds=_stale_after())) if callable(stale_getter) else []
        views = normalize_tasks(
            stale_tasks,
            stale_ids={(task.plugin, task.name) for task in stale_tasks},
        )
    else:
        tasks = list(supervisor.snapshot(include_done=True))
        views = normalize_tasks(tasks, stale_ids=stale_ids)

    if request.mode == "overview":
        lines = [_task_title(request), "", *render_task_summary(views)]
        problems = filter_task_views(views, TaskListRequest(mode="problems"))
        if problems:
            lines.extend(["", "⚠️ Problems"])
            lines.extend(render_task_entry(view, full=False) for view in problems[:5])
        watchdog = getattr(bot, "watchdog", None)
        runtime_state = getattr(watchdog, "runtime_state", None)
        if callable(runtime_state):
            lines.extend(["", "🐕 Runtime Watchdog", *render_watchdog_lines(runtime_state())])
        bot.reply(msg, lines)
        return

    filtered = filter_task_views(views, request)
    if request.mode == "show" and not filtered:
        bot.reply_warn(msg, f"Task not found: {request.show}")
        return

    entries = [render_task_entry(view, full=request.full or request.mode == "show") for view in filtered]
    if not entries:
        entries = [
            "✅ No background tasks match this view."
            if request.mode in {"failed", "stale", "restarting", "problems"}
            else "No supervised tasks found."
        ]

    bot.reply(
        msg,
        format_page(
            _task_title(request),
            entries,
            page_request=request.page,
            page_size=5 if request.full else 10,
            command_hint=f"{_prefix()}tasks",
        ),
    )


@command(
    "tasks list",
    role=Role.ADMIN,
    aliases=["task list"],
    short="Show supervised background tasks.",
    usage="{prefix}tasks list [all|page|last]",
    examples=["{prefix}tasks list", "{prefix}tasks list all"],
    category="admin",
    context="private recommended",
)
async def tasks_list_command(bot, sender, nick, args, msg, is_room):
    await tasks_command(bot, sender, nick, ["list", *(args or [])], msg, is_room)


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
    await tasks_command(bot, sender, nick, ["stale", *(args or [])], msg, is_room)
