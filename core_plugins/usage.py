"""Command usage statistics for administrators."""

from __future__ import annotations

import time

from utils.command import COMMANDS, Role, command
from utils.command_metadata import help_example, help_subcommand

PLUGIN_META = {
    "name": "usage",
    "version": "1.0.0",
    "description": "Inspect aggregate command usage and find unused commands.",
    "category": "core",
}


def _registered_command_names() -> set[str]:
    return {str(getattr(cmd, "name", "")).strip() for _, cmd in COMMANDS.items() if getattr(cmd, "name", "")}


def _age(value: int) -> str:
    seconds = max(0, int(time.time()) - int(value or 0))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


@command(
    "commandstats",
    role=Role.ADMIN,
    aliases=["cmdstats", "usage"],
    short="Show aggregate command usage and commands that have never been used.",
    usage="{prefix}commandstats [top|rare|unused] [days]",
    subcommands=[
        help_subcommand(
            "top",
            "top [days]",
            "Show the most-used commands.",
            examples=[help_example("{prefix}commandstats top 30", "Show the last 30 days.")],
        ),
        help_subcommand(
            "rare",
            "rare [days]",
            "Show the least-used commands in the period.",
            examples=[help_example("{prefix}commandstats rare 90", "Find rarely used commands.")],
        ),
        help_subcommand(
            "unused",
            "unused",
            "Show registered commands never recorded.",
            examples=[help_example("{prefix}commandstats unused", "Find never-used commands.")],
        ),
    ],
    examples=[
        help_example("{prefix}commandstats top 30", "Show usage from the last 30 days."),
        help_example("{prefix}commandstats unused", "Find commands with no recorded use."),
    ],
    category="Admin",
    context="private chat / MUC PM",
)
async def commandstats(bot, sender, nick, args, msg, is_room):
    del sender, nick, is_room
    store = getattr(getattr(bot, "db", None), "command_usage", None)
    if store is None:
        bot.reply_error(msg, "Command usage storage is not available.")
        return

    mode = str(args[0]).lower() if args else "top"
    if mode not in {"top", "rare", "unused"}:
        bot.reply_usage(msg, f"{bot.prefix}commandstats [top|rare|unused] [days]")
        return

    if mode == "unused":
        used = await store.all_time_commands()
        unused = sorted(_registered_command_names() - used)
        lines = [f"📊 Never used commands ({len(unused)}):"]
        lines.extend(f"• {name}" for name in unused[:100])
        if len(unused) > 100:
            lines.append(f"… and {len(unused) - 100} more")
        bot.reply(msg, lines)
        return

    try:
        days = max(1, min(3650, int(args[1] if len(args) > 1 else 30)))
    except (TypeError, ValueError):
        bot.reply_usage(msg, f"{bot.prefix}commandstats {mode} [days]")
        return

    rows = await store.summary(days=days, limit=200)
    if mode == "rare":
        rows = sorted(rows, key=lambda row: (int(row.get("uses", 0)), str(row.get("command_name", ""))))
    else:
        rows = rows[:30]
    rows = rows[:30]
    lines = [f"📊 Command usage — {mode}, last {days} day(s)"]
    if not rows:
        lines.append("No command usage recorded in this period.")
    for row in rows:
        uses = int(row.get("uses", 0))
        failures = int(row.get("failures", 0))
        average = int(row.get("total_duration_ms", 0)) // max(1, uses)
        lines.append(
            f"• {row.get('command_name')} — {uses} use(s), "
            f"{failures} failed, avg {average}ms, last {_age(int(row.get('last_used_at', 0)))} ago"
        )
    bot.reply(msg, lines)


async def get_runtime_state(bot, room_jid=None):
    del room_jid
    store = getattr(getattr(bot, "db", None), "command_usage", None)
    if store is None:
        return {"available": False, "registered_commands": len(_registered_command_names())}
    used = await store.all_time_commands()
    registered = _registered_command_names()
    return {
        "available": True,
        "registered_commands": len(registered),
        "used_commands": len(used),
        "unused_commands": len(registered - used),
    }


async def doctor(bot, room_jid=None):
    state = await get_runtime_state(bot, room_jid)
    return {
        "ok": bool(state.get("available")),
        "summary": (
            f"used={state.get('used_commands', 0)}, "
            f"unused={state.get('unused_commands', state.get('registered_commands', 0))}"
        ),
    }
