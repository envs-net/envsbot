"""
Plugin management commands.

This plugin exposes administrative commands for managing plugins at runtime,
like loading, unloading, reloading and listing plugins.

All commands rely on the async PluginManager API.
"""

import logging
from utils.command import command, Role
from utils.config import config
from utils.formatting import format_page, parse_page_args, status_icon
from utils.audit import audit_event

log = logging.getLogger(__name__)


PLUGIN_META = {
    "name": "plugins",
    "version": "0.2.0",
    "description": "Runtime plugin management",
    "category": "core",
}
prefix = config.get("prefix", ",")


def _plugin_health_status_from_lines(lines: list[str]) -> str:
    """Return a compact health status derived from plugin doctor lines."""
    if any(str(line).startswith("🔴") for line in lines):
        return "failed"
    if any(str(line).startswith(("⚠️", "🟡", "🟡️")) for line in lines):
        return "warning"
    if any(str(line).startswith("✅") for line in lines):
        return "ok"
    if any("error" in str(line).lower() or "failed" in str(line).lower() for line in lines):
        return "failed"
    if any("warning" in str(line).lower() or "stale" in str(line).lower() for line in lines):
        return "warning"
    return "info"


async def _plugin_health_summary(bot, loaded_names: set[str]) -> dict[str, str]:
    """Return a best-effort health status per loaded plugin."""
    manager = getattr(bot, "bot_plugins", None)
    doctor = getattr(manager, "plugin_doctor", None)
    if not callable(doctor):
        return {name: "info" for name in loaded_names}

    summary: dict[str, str] = {}
    for name in sorted(loaded_names):
        try:
            lines = [str(line) for line in await doctor(name)]
            summary[name] = _plugin_health_status_from_lines(lines)
        except Exception:
            log.debug("[PLUGIN] health summary failed for %s", name, exc_info=True)
            summary[name] = "failed"
    return summary


def _plugin_health_summary_line(health: dict[str, str]) -> str:
    """Return an aggregate plugin health summary line."""
    counts = {"ok": 0, "warning": 0, "failed": 0, "info": 0}
    for status in health.values():
        counts[status if status in counts else "info"] += 1
    return (
        "Health: "
        f"{status_icon('ok')} {counts['ok']} ok, "
        f"{status_icon('warning')} {counts['warning']} warning, "
        f"{status_icon('failed')} {counts['failed']} failed, "
        f"{status_icon('info')} {counts['info']} unknown"
    )


def _format_state_lines(state: dict) -> list[str]:
    """Format a plugin state dict as stable diagnostic lines."""
    if not state:
        return ["State: no runtime state reported"]
    lines = []
    for key in sorted(state):
        value = state[key]
        if isinstance(value, (list, tuple, set)):
            value = ", ".join(str(item) for item in value) or "none"
        lines.append(f"{key}: {value}")
    return lines


def _plugin_command_names(name: str) -> list[str]:
    """Return registered command names for one plugin."""
    try:
        from utils.command import COMMANDS

        tokens = COMMANDS.by_plugin.get(name, set())
        return sorted(" ".join(item) for item in tokens)
    except Exception:
        log.debug("[PLUGIN] Could not inspect command registry", exc_info=True)
        return []


@command(
    "plugin list",
    role=Role.ADMIN,
    aliases=["plugins", "plugins list"],
    short="List loaded and available core/optional plugins.",
    usage="{prefix}plugin list [all|page|last]",
    examples=[
        "{prefix}plugins",
        "{prefix}plugins all",
        "{prefix}plugins list",
    ],
    category="core",
    context="private chat / MUC PM",
)
async def plugin_list(bot, sender, nick, args, msg, is_room):
    """List all plugins grouped by category and health."""
    categories = await bot.bot_plugins.list_detailed()
    page = parse_page_args(args)

    labels = {"core": "Core plugins", "plugins": "Optional plugins"}
    order = ["core", "plugins"] + sorted(k for k in categories if k not in {"core", "plugins"})
    loaded_names = {
        str(name)
        for block in categories.values()
        for name in block.get("loaded", [])
    }
    health = await _plugin_health_summary(bot, loaded_names)

    entries = []
    if loaded_names:
        entries.extend([_plugin_health_summary_line(health), ""])
    for category in order:
        if category not in categories:
            continue
        block = categories[category]
        entries.append(f"[{labels.get(category, category.title())}]")
        for name in sorted(block["loaded"]):
            status = health.get(str(name), "info")
            entries.append(f"[loaded] {name} — {status_icon(status)} {status}")
        for name in sorted(block["available"]):
            entries.append(f"[not loaded] {name}")
        entries.append("")

    if entries and entries[-1] == "":
        entries.pop()

    bot.reply(
        msg,
        format_page(
            "📦 Plugin status",
            entries,
            page_request=page,
            page_size=14,
            command_hint=f"{bot.prefix}plugins",
        ),
    )


@command(
    "plugin info",
    role=Role.ADMIN,
    aliases=["plugins info"],
    short="Show metadata and source information for one plugin.",
    usage="{prefix}plugin info <plugin>",
    examples=["{prefix}plugin info rooms"],
    category="core",
    context="private chat / MUC PM",
)
async def plugin_info(bot, sender, nick, args, msg, is_room):
    """
    Shows metadata of a plugin, like name, version, description and requires.

    Usage:
        {prefix}plugin info <plugin>
    """
    if not args:
        bot.reply(msg, f"Usage: {prefix}plugin info <plugin>")
        return

    name = args[0].lower()
    meta = await bot.bot_plugins.get_plugin_info(name)

    if not meta:
        bot.reply(msg, f"Plugin '{name}' not found.")
        return

    lines = [
        f"Plugin: {meta.get('name', name)}",
        f"Version: {meta.get('version', 'unknown')}",
        f"Source: {meta.get('source', 'plugins')}",
        f"Category: {meta.get('category', 'other')}",
        f"Description: {meta.get('description', 'no description')}",
    ]

    if meta.get("requires"):
        lines.append("Requires: " + ", ".join(meta["requires"]))

    bot.reply(msg, "\n".join(lines))


@command(
    "plugin diagnose",
    role=Role.ADMIN,
    aliases=["plugins diagnose"],
    short="Show diagnostics for one plugin, including hooks, commands and tasks.",
    usage="{prefix}plugin diagnose <plugin>",
    examples=["{prefix}plugin diagnose rss"],
    category="admin",
    context="private chat / MUC PM",
)
async def plugin_diagnose(bot, sender, nick, args, msg, is_room):
    """Show diagnostics for one plugin."""
    if len(args) != 1:
        bot.reply_usage(msg, f"{bot.prefix}plugin diagnose <plugin>")
        return

    name = args[0].lower()
    meta = await bot.bot_plugins.get_plugin_info(name)
    if not meta:
        bot.reply_error(msg, f"Plugin '{name}' not found.")
        return

    loaded = name in getattr(bot.bot_plugins, "plugins", {})
    commands = _plugin_command_names(name)
    tasks = []
    supervisor = getattr(bot, "tasks", None)
    if supervisor is not None:
        tasks = [
            task for task in supervisor.snapshot(include_done=True)
            if task.plugin == name
        ]

    module = getattr(bot.bot_plugins, "plugins", {}).get(name)
    lines = [
        f"🔎 Plugin diagnostics: {name}",
        f"Loaded: {'yes' if loaded else 'no'}",
        f"Source: {meta.get('source', 'plugins')}",
        f"Category: {meta.get('category', 'other')}",
        f"Description: {meta.get('description', 'no description')}",
        f"Requires: {', '.join(meta.get('requires', [])) if meta.get('requires') else 'none'}",
        f"Commands: {len(commands)}",
        f"Supervised tasks: {len(tasks)}",
        f"cleanup_room_state hook: {'yes' if callable(getattr(module, 'cleanup_room_state', None)) else 'no'}",
        f"runtime state hook: {'yes' if callable(getattr(module, 'get_runtime_state', None)) else 'no'}",
    ]
    if tasks:
        lines.append("Tasks:")
        lines.extend(f"• {task.name}: {task.status}" for task in tasks)
    if commands:
        lines.append("Commands:")
        lines.extend(f"• {command_name}" for command_name in commands[:12])
        if len(commands) > 12:
            lines.append(f"• … {len(commands) - 12} more")

    bot.reply(msg, lines)


@command(
    "plugin state",
    role=Role.ADMIN,
    aliases=["plugins state"],
    short="Show plugin-provided runtime state counters.",
    usage="{prefix}plugin state <plugin> [room_jid]",
    examples=[
        "{prefix}plugin state rss",
        "{prefix}plugin state poll room@conference.example.org",
    ],
    category="admin",
    context="private chat / MUC PM",
)
async def plugin_state(bot, sender, nick, args, msg, is_room):
    """Show plugin-provided runtime state."""
    if len(args) not in (1, 2):
        bot.reply_usage(msg, f"{bot.prefix}plugin state <plugin> [room_jid]")
        return

    name = args[0].lower()
    room_jid = args[1].lower() if len(args) == 2 else None
    if name not in getattr(bot.bot_plugins, "plugins", {}):
        bot.reply_error(msg, f"Plugin '{name}' is not loaded.")
        return

    state = await bot.bot_plugins.plugin_state(name, room_jid=room_jid)
    title = f"📦 Plugin state: {name}"
    if room_jid:
        title += f" ({room_jid})"
    bot.reply(msg, [title, *_format_state_lines(state)])


@command(
    "plugin load",
    role=Role.ADMIN,
    aliases=["plugins load"],
    short="Load one plugin or all plugins.",
    usage="{prefix}plugin load <plugin|all>",
    examples=["{prefix}plugin load weather"],
    category="core",
    context="private chat / MUC PM",
)
async def plugin_load(bot, sender, nick, args, msg, is_room):
    """
    Load a plugin or all plugins. Only if it's not already loaded.

    Usage:
        {prefix}plugin load <plugin>
        {prefix}plugin load all
    """
    if not args:
        bot.reply(msg, f"Usage: {prefix}plugin load <plugin|all>")
        return

    target = args[0].lower()

    if target == "all":
        await bot.bot_plugins.load_all()
        await audit_event(bot, "plugins_load_all", actor=sender, target="plugins")
        bot.reply(msg, "All plugins loaded (in dependency order).")
        return

    try:
        await bot.bot_plugins.load(target)
        await audit_event(bot, "plugin_loaded", actor=sender, target=target)
        bot.reply(msg, f"Plugin '{target}' loaded.")
    except Exception as e:
        bot.reply(msg, f"Error loading '{target}': {e}")


@command(
    "plugin unload",
    role=Role.ADMIN,
    aliases=["plugins unload"],
    short="Unload one optional plugin; core plugins are protected.",
    usage="{prefix}plugin unload <plugin> [force]",
    examples=["{prefix}plugin unload weather"],
    category="core",
    context="private chat / MUC PM",
)
async def plugin_unload(bot, sender, nick, args, msg, is_room):
    """
    Unload a plugin.

    Usage:
        {prefix}plugin unload <plugin>
        {prefix}plugin unload <plugin> force
    """
    if not args:
        bot.reply(msg, f"Usage: {prefix}plugin unload <plugin> [force]")
        return

    name = args[0].lower()
    force = len(args) > 1 and args[1].lower() == "force"

    success, message = await bot.bot_plugins.unload(name, force=force)
    if success:
        await audit_event(
            bot,
            "plugin_unloaded",
            actor=sender,
            target=name,
            details={"force": force},
        )

    bot.reply(msg, message)


@command(
    "plugin reload",
    role=Role.ADMIN,
    aliases=["plugins reload"],
    short="Reload one plugin or all plugins.",
    usage="{prefix}plugin reload <plugin|all> [auto]",
    examples=[
        "{prefix}plugin reload help",
        "{prefix}plugin reload all auto",
    ],
    category="core",
    context="private chat / MUC PM",
)
async def plugin_reload(bot, sender_jid, nick, args, msg, is_room):
    """
    Reload a plugin or all plugins that are currently loaded.

    Respects plugin dependencies. If other plugins depend on the target,
    use 'auto' flag to reload them automatically.

    Usage:
        {prefix}plugin reload <plugin>
        {prefix}plugin reload <plugin> auto
        {prefix}plugin reload all
        {prefix}plugin reload all auto
    """
    if not args:
        bot.reply(msg, f"Usage: {prefix}plugin reload <plugin> [auto]")
        return

    target = args[0].lower()
    auto = len(args) > 1 and args[1].lower() == "auto"

    if target == "all":
        # Reload all plugins
        plugins_to_reload = [
            p for p in bot.bot_plugins.list() if p != "plugins"]

        errors = []
        successful = []

        for name in plugins_to_reload:
            # With auto flag: attempt reload with auto
            success, message = await bot.bot_plugins.reload(name, auto=auto)
            if success:
                successful.append(name)
                log.info("[PLUGIN] reload successful: %s", name)
            else:
                errors.append(f"- {name}: {message}")
                log.warning("[PLUGIN] reload failed: %s", name)

        # Reload plugins manager last
        success, message = await bot.bot_plugins.reload("plugins", auto=False)
        if success:
            successful.append("plugins")
        else:
            errors.append(f"- plugins: {message}")

        await audit_event(
            bot,
            "plugins_reloaded",
            actor=sender_jid,
            target="all",
            details={"auto": auto, "successful": len(successful), "errors": len(errors)},
        )
        if errors:
            error_text = "\n".join(errors)
            if auto:
                bot.reply(
                    msg,
                    f"⚠️ All plugins reloaded with some errors:\n{error_text}")
            else:
                bot.reply(
                    msg, f"⚠️ All plugins reloaded with errors:\n{error_text}")
        else:
            bot.reply(msg, f"✅ All {len(successful)
                                    } plugins reloaded successfully.")
        return

    success, message = await bot.bot_plugins.reload(target, auto=auto)
    if success:
        await audit_event(
            bot,
            "plugin_reloaded",
            actor=sender_jid,
            target=target,
            details={"auto": auto},
        )
    bot.reply(msg, message)
