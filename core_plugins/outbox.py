"""Administrative commands for the persistent outbound queue."""

from __future__ import annotations

from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand

PLUGIN_META = {
    "name": "outbox",
    "version": "1.0.0",
    "description": "Inspect and retry durable outbound messages.",
    "category": "core",
}


@command(
    "outbox",
    role=Role.ADMIN,
    short="Inspect pending and failed durable message deliveries.",
    usage="{prefix}outbox <status|dead|retry>",
    subcommands=[
        help_subcommand(
            "status",
            "status",
            "Show queue counts and worker state.",
            examples=[help_example("{prefix}outbox status", "Inspect pending delivery state.")],
        ),
        help_subcommand(
            "dead",
            "dead",
            "List dead-letter messages without bodies.",
            examples=[help_example("{prefix}outbox dead", "List permanently failed deliveries.")],
        ),
        help_subcommand(
            "retry",
            "retry [category]",
            "Retry dead letters.",
            examples=[help_example("{prefix}outbox retry rss", "Retry failed RSS deliveries.")],
        ),
    ],
    examples=[
        help_example("{prefix}outbox status", "Inspect the durable queue."),
        help_example("{prefix}outbox retry rss", "Retry failed RSS deliveries."),
    ],
    category="Admin",
    context="private chat / MUC PM",
)
async def outbox_command(bot, sender, nick, args, msg, is_room):
    del sender, nick, is_room
    runtime = getattr(bot, "outbox", None)
    store = getattr(getattr(bot, "db", None), "outbox", None)
    if runtime is None or store is None:
        bot.reply_error(msg, "Persistent outbox is not available.")
        return
    subcommand = str(args[0]).lower() if args else "status"
    if subcommand == "status":
        state = await runtime.runtime_state()
        bot.reply(
            msg,
            [
                "📮 Persistent outbox",
                f"• worker: {'running' if state['worker_running'] else 'stopped'}",
                f"• pending: {state['pending']}",
                f"• inflight: {state['inflight']}",
                f"• dead: {state['dead']}",
                f"• oldest pending: {state['oldest_pending_age_seconds']}s",
                f"• delivered since start: {state['delivered_since_start']}",
                f"• failed attempts since start: {state['failed_attempts_since_start']}",
                f"• last error: {state['last_error'] or '-'}",
            ],
        )
        return
    if subcommand == "dead":
        rows = await store.dead_letters(limit=50)
        lines = [f"📮 Dead letters ({len(rows)} shown)"]
        lines.extend(
            f"• #{row['id']} {row['category']} → {row['destination']} "
            f"({row['attempts']}/{row['max_attempts']}): {row['last_error'] or '-'}"
            for row in rows
        )
        if not rows:
            lines.append("No dead letters.")
        bot.reply(msg, lines)
        return
    if subcommand == "retry":
        category = str(args[1]).strip() if len(args) > 1 else None
        count = await store.retry_dead(category=category)
        runtime.wakeup.set()
        bot.reply_ok(msg, f"Queued {count} dead-letter message(s) for retry.")
        return
    bot.reply_usage(msg, f"{bot.prefix}outbox <status|dead|retry> [category]")


async def get_runtime_state(bot, room_jid=None):
    del room_jid
    runtime = getattr(bot, "outbox", None)
    if runtime is None:
        return {"available": False}
    return {"available": True, **(await runtime.runtime_state())}


async def doctor(bot, room_jid=None):
    state = await get_runtime_state(bot, room_jid)
    if not state.get("available"):
        return {"ok": False, "summary": "persistent outbox unavailable"}
    ok = bool(state.get("worker_running")) and int(state.get("dead", 0)) == 0
    return {
        "ok": ok,
        "summary": (
            f"pending={state.get('pending', 0)}, dead={state.get('dead', 0)}, "
            f"worker={'running' if state.get('worker_running') else 'stopped'}"
        ),
    }
