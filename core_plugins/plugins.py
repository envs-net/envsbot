"""
Plugin management commands.

This plugin exposes administrative commands for managing plugins at runtime,
like loading, unloading, reloading and listing plugins.

All commands rely on the async PluginManager API.
"""

import logging
from utils.command import command, Role
from utils.config import config
from utils.formatting import format_page, parse_page_args
from utils.audit import audit_event

log = logging.getLogger(__name__)


PLUGIN_META = {
    "name": "plugins",
    "version": "0.2.0",
    "description": "Runtime plugin management",
    "category": "core",
}
prefix = config.get("prefix", ",")


@command("plugin list", role=Role.ADMIN, aliases=["plugins list"])
async def plugin_list(bot, sender, nick, args, msg, is_room):
    """List all plugins grouped by category."""
    categories = await bot.bot_plugins.list_detailed()
    page = parse_page_args(args)

    labels = {"core": "Core plugins", "plugins": "Optional plugins"}
    order = ["core", "plugins"] + sorted(k for k in categories if k not in {"core", "plugins"})

    entries = []
    for category in order:
        if category not in categories:
            continue
        block = categories[category]
        entries.append(f"[{labels.get(category, category.title())}]")
        for name in sorted(block["loaded"]):
            entries.append(f"[loaded] {name}")
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
            command_hint=f"{bot.prefix}plugins list",
        ),
    )


@command("plugin info", role=Role.ADMIN, aliases=["plugins info"])
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


@command("plugin load", role=Role.ADMIN, aliases=["plugins load"])
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


@command("plugin unload", role=Role.ADMIN, aliases=["plugins unload"])
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


@command("plugin reload", role=Role.ADMIN, aliases=["plugins reload"])
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
