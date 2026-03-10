import logging
from command import command

log = logging.getLogger(__name__)


PLUGIN_META = {
    "name": "plugins",
    "version": "2.1",
    "description": "Unified plugin management command"
}


@command("plugins", owner_only=True)
async def plugins_command(bot, sender, nick, args, msg, is_room):
    """
    Manage bot plugins at runtime.

    This command allows admins to load, unload, reload, and inspect plugins
    without restarting the bot.

    Command
    -------
    {prefix}plugins <subcommand> [arguments]

    Subcommands
    ----------
    list
        Show loaded plugins and plugins available for loading.

    load <plugin>
        Load a specific plugin.

    load all
        Load all plugins that exist but are not currently loaded.

    reload <plugin>
        Reload a specific plugin.

    reload all
        Reload all currently loaded plugins.

    unload <plugin>
        Unload a currently loaded plugin.

    Permissions
    ----------
    Admins / bot owners only.

    Usage
    -----
    {prefix}plugins list
    {prefix}plugins load <plugin>
    {prefix}plugins load all
    {prefix}plugins reload <plugin>
    {prefix}plugins reload all
    {prefix}plugins unload <plugin>

    Examples
    --------
    {prefix}plugins list
        Show plugin status.

    {prefix}plugins load help
        Load the "help" plugin.

    {prefix}plugins reload status
        Reload the "status" plugin.

    {prefix}plugins unload help
        Unload the "help" plugin.

    Notes
    -----
    • Plugins are discovered from the bot's plugin directory.

    • Loading a plugin registers its commands with the bot.

    • Unloading a plugin removes all commands registered by it.

    • When reloading all plugins, this plugin ("plugins") reloads itself
      last so the running command is not interrupted.
    """

    if not args:
        bot.reply(
            msg,
            f"🚨 Usage: {bot.prefix}plugins "
            "<list|load|reload|unload> [plugin]"
        )
        return

    sub = args[0].lower()

    log.info("[PLUGIN] 📦 Command by %s: %s", sender, " ".join(args))

    dispatch = {
        "list": _plugins_list,
        "load": _plugins_load,
        "reload": _plugins_reload,
        "unload": _plugins_unload,
    }

    handler = dispatch.get(sub)

    if not handler:
        log.warning("[PLUGIN] 🚨 Unknown plugins subcommand: %s", sub)
        bot.reply(
            msg,
            f"❌ Unknown subcommand. Use "
            f"{bot.prefix}plugins <list|load|reload|unload>"
        )
        return

    await handler(bot, sender, args[1:], msg)


# -------------------------------------------------
# LIST
# -------------------------------------------------

async def _plugins_list(bot, sender, args, msg):

    loaded = sorted(bot.plugins.plugins.keys())
    discovered = sorted(bot.plugins.discover())
    not_loaded = sorted(set(discovered) - set(loaded))

    lines = ["📜 Plugin status"]

    if loaded:
        lines.append("📦 Loaded:")
        lines.append(", ".join(loaded))
    else:
        lines.append("📦 Loaded: none")

    if not_loaded:
        lines.append("")
        lines.append("🧩 Available:")
        lines.append(", ".join(not_loaded))

    log.info("[PLUGIN] 📜 Listed plugins for %s", sender)

    bot.reply(msg, lines)


# -------------------------------------------------
# LOAD
# -------------------------------------------------

async def _plugins_load(bot, sender, args, msg):

    if not args:
        bot.reply(
            msg,
            f"🚨 Usage: {bot.prefix}plugins load <plugin|all>"
        )
        return

    target = args[0].lower()

    if target == "all":

        discovered = set(bot.plugins.discover())
        loaded = set(bot.plugins.plugins.keys())
        to_load = sorted(discovered - loaded)

        if not to_load:
            bot.reply(msg, "ℹ️ All plugins are already loaded.")
            log.info("[PLUGIN] ℹ️ All plugins already loaded")
            return

        success = []
        failed = []

        for name in to_load:
            try:
                bot.plugins.load(name)
                success.append(name)
                log.info("[PLUGIN] 📦 Loaded plugin: %s", name)
            except Exception as e:
                log.exception(
                    "[PLUGIN] ❌ Failed loading plugin: %s", name
                )
                failed.append(f"{name} ({e})")

        message = []

        if success:
            message.append("✅ Loaded: " + ", ".join(success))

        if failed:
            message.append("❌ Failed: " + ", ".join(failed))

        bot.reply(msg, "\n".join(message))
        return

    plugin = target

    if plugin in bot.plugins.plugins:
        bot.reply(msg, f"🚨 Plugin '{plugin}' already loaded.")
        log.warning("[PLUGIN] 🚨 Plugin already loaded: %s", plugin)
        return

    try:
        bot.plugins.load(plugin)
        log.info("[PLUGIN] 📦 Plugin loaded: %s", plugin)
        bot.reply(msg, f"✅ Plugin '{plugin}' loaded.")
    except Exception as e:
        log.exception(
            "[PLUGIN] ❌ Load failed for plugin: %s", plugin
        )
        bot.reply(msg, f"❌ Load failed: {e}")


# -------------------------------------------------
# RELOAD
# -------------------------------------------------

async def _plugins_reload(bot, sender, args, msg):

    if not args:
        bot.reply(
            msg,
            f"🚨 Usage: {bot.prefix}plugins reload <plugin|all>"
        )
        return

    target = args[0].lower()

    if target == "all":

        plugins = list(bot.plugins.plugins.keys())

        success = []
        failed = []

        for name in plugins:
            if name == "plugins":
                continue

            try:
                bot.plugins.reload(name)
                success.append(name)
                log.info("[PLUGIN] 🔁 Reloaded plugin: %s", name)
            except Exception as e:
                log.exception(
                    "[PLUGIN] ❌ Reload failed for plugin: %s", name
                )
                failed.append(f"{name} ({e})")

        try:
            bot.plugins.reload("plugins")
            success.append("plugins")
            log.info("[PLUGIN] 🔁 Reloaded plugin manager")
        except Exception:
            log.exception(
                "[PLUGIN] ❌ Reload failed for plugin manager"
            )

        message = []

        if success:
            message.append("🔁 Reloaded: " + ", ".join(success))

        if failed:
            message.append("❌ Failed: " + ", ".join(failed))

        bot.reply(msg, "\n".join(message))
        return

    plugin = target

    if plugin not in bot.plugins.plugins:
        available = ", ".join(
            sorted(bot.plugins.plugins.keys())
        )
        bot.reply(
            msg,
            f"❌ Plugin '{plugin}' not found. "
            f"Available: {available}"
        )
        log.warning(
            "[PLUGIN] 🚨 Reload requested for unknown plugin: %s",
            plugin
        )
        return

    try:
        bot.plugins.reload(plugin)
        log.info("[PLUGIN] 🔁 Plugin reloaded: %s", plugin)
        bot.reply(msg, f"🔁 Plugin '{plugin}' reloaded.")
    except Exception as e:
        log.exception(
            "[PLUGIN] ❌ Reload failed for plugin: %s", plugin
        )
        bot.reply(msg, f"❌ Reload failed: {e}")


# -------------------------------------------------
# UNLOAD
# -------------------------------------------------

async def _plugins_unload(bot, sender, args, msg):

    if not args:
        bot.reply(
            msg,
            f"🚨 Usage: {bot.prefix}plugins unload <plugin>"
        )
        return

    plugin = args[0].lower()

    if plugin == "plugins":
        bot.reply(
            msg,
            "🚨 The plugins manager cannot unload itself."
        )
        log.warning("[PLUGIN] 🚨 Attempt to unload plugin manager")
        return

    if plugin not in bot.plugins.plugins:
        available = ", ".join(
            sorted(bot.plugins.plugins.keys())
        )
        bot.reply(
            msg,
            f"❌ Plugin '{plugin}' not found. "
            f"Available: {available}"
        )
        log.warning(
            "[PLUGIN] 🚨 Unload requested for unknown plugin: %s",
            plugin
        )
        return

    try:
        bot.plugins.unload(plugin)
        log.info("[PLUGIN] 📦 Plugin unloaded: %s", plugin)
        bot.reply(msg, f"📦 Plugin '{plugin}' unloaded.")
    except Exception as e:
        log.exception(
            "[PLUGIN] ❌ Unload failed for plugin: %s", plugin
        )
        bot.reply(msg, f"❌ Unload failed: {e}")
