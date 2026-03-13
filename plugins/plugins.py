"""
Runtime plugin management commands.

This module provides administrator commands to inspect and manage
plugins while the bot is running. Plugins can be listed, loaded,
reloaded, unloaded, and inspected without restarting the bot.

Plugins are grouped by category based on PLUGIN_META metadata.
"""

import logging
import importlib
from command import command, Role

log = logging.getLogger(__name__)


PLUGIN_META = {
    "name": "plugins",
    "version": "3.2",
    "description": "Runtime plugin management",
    "category": "core",
}


# --------------------------------------------------
# LIST
# --------------------------------------------------


@command("plugin list", role=Role.ADMIN, aliases=["plugins list"])
async def plugin_list(bot, sender, nick, args, msg, is_room):
    """
    List all plugins grouped by category.

    Shows currently loaded plugins and plugins available but not
    loaded.
    """

    loaded = bot.plugins.list()
    available = bot.plugins.available()

    categories = {}

    for name in loaded:

        meta = bot.plugins.meta.get(name, {})
        category = meta.get("category", "other")

        categories.setdefault(category, {"loaded": [], "available": []})
        categories[category]["loaded"].append(name)

    for name in available:

        category = "other"

        try:

            module = importlib.import_module(f"plugins.{name}")
            meta = getattr(module, "PLUGIN_META", {})
            category = meta.get("category", "other")

        except Exception:

            log.warning(
                "[PLUGIN] ⚠️ Failed reading metadata for plugin: %s",
                name,
            )

        categories.setdefault(category, {"loaded": [], "available": []})
        categories[category]["available"].append(name)

    lines = ["Plugin status"]

    for category in sorted(categories):

        block = categories[category]

        lines.append("")
        lines.append(f"[{category.upper()}]")

        loaded_plugins = sorted(block["loaded"])
        available_plugins = sorted(block["available"])

        for name in loaded_plugins:
            lines.append(f"  [loaded] {name}")

        for name in available_plugins:
            lines.append(f"  [not loaded] {name}")

    log.info("[PLUGIN] 📜 Plugin list requested by %s", sender)

    bot.reply(msg, "\n".join(lines))


# --------------------------------------------------
# INFO
# --------------------------------------------------


@command("plugin info", role=Role.ADMIN, aliases=["plugins info"])
async def plugin_info(bot, sender, nick, args, msg, is_room):
    """
    Show metadata for a plugin.

    Usage
    -----
    {prefix}plugin info <plugin>
    """

    if not args:

        bot.reply(msg, "⚠️ Usage: {prefix}plugin info <plugin>")

        return

    plugin = args[0].lower()

    meta = None

    if plugin in bot.plugins.meta:

        meta = bot.plugins.meta.get(plugin)

    else:

        try:

            module = importlib.import_module(f"plugins.{plugin}")
            meta = getattr(module, "PLUGIN_META", {})

        except Exception:

            bot.reply(msg, f"⚠️ Plugin '{plugin}' not found.")

            log.warning(
                "[PLUGIN] ⚠️ Info requested for unknown plugin: %s",
                plugin,
            )

            return

    name = meta.get("name", plugin)
    version = meta.get("version", "unknown")
    desc = meta.get("description", "no description")
    category = meta.get("category", "other")
    requires = meta.get("requires", [])

    lines = [
        f"Plugin: {name}",
        f"Version: {version}",
        f"Category: {category}",
        f"Description: {desc}",
    ]

    if requires:
        lines.append("Requires: " + ", ".join(requires))

    log.info("[PLUGIN] 📜 Plugin info requested by %s: %s",
             sender, plugin)

    bot.reply(msg, "\n".join(lines))


# --------------------------------------------------
# LOAD
# --------------------------------------------------


@command("plugin load", role=Role.ADMIN, aliases=["plugins load"])
async def plugin_load(bot, sender, nick, args, msg, is_room):
    """
    Load a plugin.

    Usage
    -----
    {prefix}plugin load <plugin|all>
    """

    if not args:

        bot.reply(msg, "⚠️ Usage: {prefix}plugin load <plugin|all>")

        return

    target = args[0].lower()

    if target == "all":

        to_load = bot.plugins.available()

        if not to_load:

            bot.reply(msg, "ℹ️ All plugins are already loaded.")

            log.warning("[PLUGIN] ⚠️ All plugins already loaded")

            return

        success = []
        failed = []

        for name in to_load:

            try:

                bot.plugins.load(name)

                success.append(name)

                log.info("[PLUGIN] 📦 Loaded plugin: %s", name)

            except Exception as exc:

                failed.append(f"{name} ({exc})")

                log.exception(
                    "[PLUGIN] ❌ Failed loading plugin: %s",
                    name,
                )

        lines = []

        if success:
            lines.append("Loaded: " + ", ".join(success))

        if failed:
            lines.append("Failed: " + ", ".join(failed))

        bot.reply(msg, "\n".join(lines))

        return

    plugin = target

    if plugin in bot.plugins.list():

        bot.reply(msg, f"⚠️ Plugin '{plugin}' already loaded.")

        log.warning("[PLUGIN] ⚠️ Plugin already loaded: %s", plugin)

        return

    try:

        bot.plugins.load(plugin)

        log.info("[PLUGIN] 📦 Plugin loaded: %s", plugin)

        bot.reply(msg, f"Plugin '{plugin}' loaded.")

    except Exception as exc:

        log.exception("[PLUGIN] ❌ Load failed for plugin: %s", plugin)

        bot.reply(msg, f"Load failed: {exc}")


# --------------------------------------------------
# RELOAD
# --------------------------------------------------


@command("plugin reload", role=Role.ADMIN, aliases=["plugins reload"])
async def plugin_reload(bot, sender, nick, args, msg, is_room):
    """
    Reload a plugin.

    Usage
    -----
    {prefix}plugin reload <plugin|all>
    """

    if not args:

        bot.reply(msg, "⚠️ Usage: {prefix}plugin reload <plugin|all>")

        return

    target = args[0].lower()

    if target == "all":

        plugins = bot.plugins.list()

        success = []
        failed = []

        for name in plugins:

            if name == "plugins":
                continue

            try:

                bot.plugins.reload(name)

                success.append(name)

                log.info("[PLUGIN] 🔁 Reloaded plugin: %s", name)

            except Exception as exc:

                failed.append(f"{name} ({exc})")

                log.exception(
                    "[PLUGIN] ❌ Reload failed for plugin: %s",
                    name,
                )

        try:

            bot.plugins.reload("plugins")

            success.append("plugins")

            log.info("[PLUGIN] 🔁 Reloaded plugin manager")

        except Exception:

            log.exception(
                "[PLUGIN] ❌ Reload failed for plugin manager"
            )

        lines = []

        if success:
            lines.append("Reloaded: " + ", ".join(success))

        if failed:
            lines.append("Failed: " + ", ".join(failed))

        bot.reply(msg, "\n".join(lines))

        return

    plugin = target

    if plugin not in bot.plugins.list():

        available = ", ".join(bot.plugins.list())

        bot.reply(
            msg,
            f"⚠️ Plugin '{plugin}' not found. Available: {available}",
        )

        log.warning(
            "[PLUGIN] ⚠️ Reload requested for unknown plugin: %s",
            plugin,
        )

        return

    try:

        bot.plugins.reload(plugin)

        log.info("[PLUGIN] 🔁 Plugin reloaded: %s", plugin)

        bot.reply(msg, f"Plugin '{plugin}' reloaded.")

    except Exception as exc:

        log.exception("[PLUGIN] ❌ Reload failed for plugin: %s", plugin)

        bot.reply(msg, f"Reload failed: {exc}")


# --------------------------------------------------
# UNLOAD
# --------------------------------------------------


@command("plugin unload", role=Role.ADMIN, aliases=["plugins unload"])
async def plugin_unload(bot, sender, nick, args, msg, is_room):
    """
    Unload a plugin.

    Usage
    -----
    {prefix}plugin unload <plugin>
    """

    if not args:

        bot.reply(msg, "⚠️ Usage: {prefix}plugin unload <plugin>")

        return

    plugin = args[0].lower()

    if plugin == "plugins":

        bot.reply(msg, "⚠️ The plugin manager cannot unload itself.")

        log.warning("[PLUGIN] ⚠️ Attempt to unload plugin manager")

        return

    if plugin not in bot.plugins.list():

        available = ", ".join(bot.plugins.list())

        bot.reply(
            msg,
            f"⚠️ Plugin '{plugin}' not found. Available: {available}",
        )

        log.warning(
            "[PLUGIN] ⚠️ Unload requested for unknown plugin: %s",
            plugin,
        )

        return

    try:

        bot.plugins.unload(plugin)

        log.info("[PLUGIN] 📦 Plugin unloaded: %s", plugin)

        bot.reply(msg, f"Plugin '{plugin}' unloaded.")

    except Exception as exc:

        log.exception("[PLUGIN] ❌ Unload failed for plugin: %s", plugin)

        bot.reply(msg, f"Unload failed: {exc}")
