"""
plugin_manager.py

Runtime plugin management for the bot.

This module implements the PluginManager class which is responsible
for discovering, loading, unloading, and reloading bot plugins
during runtime.

Design
------
Plugins are normal Python modules located in the configured plugin
package (default: "plugins").

A plugin may define:

PLUGIN_META
    Optional metadata dictionary.

setup(bot)
    Optional setup hook executed after the plugin is loaded.

teardown(bot)
    Optional cleanup hook executed before the plugin is unloaded.

Commands
--------
Commands are discovered by scanning the module for functions
decorated with the command decorator. These functions contain
a `_command_names` attribute.

Handlers are registered into:

    bot.commands[name] = handler

Ownership information is stored in:

    self.command_owner[name] = plugin_name

Internal Plugins
----------------
Plugins whose filename begins with "_" are treated as internal.
Commands belonging to such plugins automatically require at
least ADMIN privileges.
"""

import importlib
import pkgutil
import sys
import inspect
import logging

from utils.command import COMMAND_INDEX, Role

log = logging.getLogger(__name__)


class PluginManager:
    """
    Runtime plugin manager responsible for plugin lifecycle.
    """

    def __init__(self, bot, package="plugins"):
        self.bot = bot
        self.package = package

        # plugin_name -> module
        self.plugins = {}

        # command_name -> plugin_name
        self.command_owner = {}

        # plugin_name -> metadata
        self.meta = {}

    # --------------------------------------------------
    # DISCOVERY
    # --------------------------------------------------

    def discover(self):
        """
        Discover available plugin modules.

        Returns
        -------
        list[str]
            Sorted list of plugin module names.
        """

        package = importlib.import_module(self.package)

        plugins = []

        for module in pkgutil.iter_modules(package.__path__):
            plugins.append(module.name)

        return sorted(plugins)

    # --------------------------------------------------
    # LISTING
    # --------------------------------------------------

    def list(self):
        """
        Return names of currently loaded plugins.
        """

        return sorted(self.plugins.keys())

    def available(self):
        """
        Return discovered plugins that are not currently loaded.
        """

        return sorted(set(self.discover()) - set(self.plugins))

    # --------------------------------------------------
    # LOAD
    # --------------------------------------------------

    def load(self, name):
        """
        Load a plugin module.

        Steps
        -----
        1. Import the module
        2. Load dependencies declared in PLUGIN_META
        3. Register commands
        4. Run setup() hook if present
        """

        if name in self.plugins:
            log.warning("[PLUGIN] ⚠️ Plugin already loaded: %s", name)
            return

        log.info("[PLUGIN] 📦 Loading plugin: %s", name)

        module_path = f"{self.package}.{name}"

        module = importlib.import_module(module_path)

        meta = getattr(module, "PLUGIN_META", {})

        # --------------------------------------------------
        # DEPENDENCIES
        # --------------------------------------------------

        for dep in meta.get("requires", []):

            if dep not in self.plugins:

                log.info(
                    "[PLUGIN] 🔗 Loading dependency '%s' for '%s'",
                    dep,
                    name,
                )

                self.load(dep)

        # --------------------------------------------------
        # COMMAND REGISTRATION
        # --------------------------------------------------

        self._register_commands(name, module)

        # --------------------------------------------------
        # SETUP HOOK
        # --------------------------------------------------

        if hasattr(module, "setup"):
            module.setup(self.bot)

        self.plugins[name] = module
        self.meta[name] = meta

        log.info("[PLUGIN] ✅ Plugin loaded: %s", name)

    # --------------------------------------------------
    # COMMAND REGISTRATION
    # --------------------------------------------------

    def _register_commands(self, plugin_name, module):
        """
        Register commands exposed by a plugin module.
        """

        is_internal = plugin_name.startswith("_")

        for _, obj in inspect.getmembers(module):
            if callable(obj) and hasattr(obj, "_command_names"):
                for name in obj._command_names:
                    if name in self.bot.commands:
                        log.warning(
                            "[PLUGIN] ⚠️ Command conflict: %s (plugin: %s)",
                            name,
                            plugin_name,
                        )
                    # register handler
                    self.bot.commands[name] = obj
                    self.command_owner[name] = plugin_name

                    # --------------------------------------------------
                    # INTERNAL PLUGIN PERMISSION POLICY
                    # --------------------------------------------------

                    if is_internal:

                        tokens = tuple(name.lower().split())
                        cmd = COMMAND_INDEX.get(tokens)

                        if cmd and cmd.role > Role.ADMIN:

                            log.debug(
                                "[PLUGIN] 🔒 Elevating role for internal command '%s' to ADMIN",
                                name,
                            )

                            cmd.role = Role.ADMIN

    # --------------------------------------------------
    # UNLOAD
    # --------------------------------------------------

    def unload(self, name):
        """
        Unload a plugin and remove its commands.
        """

        if name not in self.plugins:

            log.warning("[PLUGIN] ⚠️ Plugin not loaded: %s", name)
            return

        log.info("[PLUGIN] 📤 Unloading plugin: %s", name)

        module = self.plugins[name]

        if hasattr(module, "teardown"):
            module.teardown(self.bot)

        # remove commands belonging to plugin
        remove = []

        for cmd, owner in list(self.command_owner.items()):
            if owner == name:
                remove.append(cmd)

        for cmd_name in remove:

            handler = self.bot.commands.get(cmd_name)

            self.bot.commands.pop(cmd_name, None)
            self.command_owner.pop(cmd_name, None)

            # --------------------------------------------------
            # REMOVE FROM COMMAND_INDEX (alias-safe)
            # --------------------------------------------------

            for tokens, cmd_obj in list(COMMAND_INDEX.items()):

                if getattr(cmd_obj, "handler", None) is handler:
                    COMMAND_INDEX.pop(tokens, None)

        # remove module
        module_path = f"{self.package}.{name}"
        for mod in list(sys.modules):
            if mod == module_path or mod.startswith(module_path + "."):
                del sys.modules[mod]

        del self.plugins[name]
        self.meta.pop(name, None)

        log.info("[PLUGIN] 📤 Plugin unloaded: %s", name)

    # --------------------------------------------------
    # RELOAD
    # --------------------------------------------------

    def reload(self, name):
        """
        Reload a plugin.
        """

        log.info("[PLUGIN] 🔄 Reloading plugin: %s", name)

        self.unload(name)
        self.load(name)

    # --------------------------------------------------
    # BULK LOAD
    # --------------------------------------------------

    def load_all(self):
        """
        Load all discovered plugins.
        """

        for plugin in self.discover():

            if plugin in self.plugins:
                continue

            try:
                self.load(plugin)

            except Exception:

                log.exception(
                    "[PLUGIN] ❌ Failed to load plugin: %s",
                    plugin,
                )
