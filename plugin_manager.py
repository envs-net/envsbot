"""
plugin_manager.py

Runtime plugin management for the bot.

This module implements the PluginManager class, responsible for
discovering, loading, unloading, and reloading bot plugins during
runtime. Plugins are Python modules located inside the configured
plugin package (by default "plugins").

Responsibilities
----------------
• Discover available plugin modules in the plugin package.
• Load plugins and resolve their dependencies.
• Register commands exposed by plugins.
• Unload plugins and remove their commands.
• Reload plugins without restarting the bot.
• Provide metadata about loaded plugins.

Plugin Structure
----------------
Each plugin is expected to be a Python module that may define:

PLUGIN_META
    Optional dictionary containing metadata such as:
    - name
    - version
    - description
    - category
    - requires (list of plugin dependencies)

setup(bot)
    Optional function called after a plugin is loaded.

teardown(bot)
    Optional function called before a plugin is unloaded.

Command functions
    Functions decorated with the bot's command decorator.
    The plugin manager registers these automatically.

Notes
-----
• Dependencies declared in PLUGIN_META["requires"] are loaded
  automatically before the plugin itself.

• Commands registered by a plugin are tracked so they can be
  removed when the plugin is unloaded.

• Reloading a plugin performs an unload followed by a load.

• This manager only tracks plugins loaded during runtime and does
  not enforce isolation between plugin modules.

See Also
--------
plugins.py
    Administrative plugin providing commands such as
    ",plugin list", ",plugin load", and ",plugin reload".
"""

import importlib
import pkgutil
import sys
import inspect
import logging

log = logging.getLogger(__name__)


class PluginManager:
    """Runtime plugin manager."""

    def __init__(self, bot, package="plugins"):
        self.bot = bot
        self.package = package

        # plugin_name -> module
        self.plugins = {}

        # command -> plugin_name
        self.command_owner = {}

        # plugin_name -> metadata
        self.meta = {}

    # --------------------------------------------------
    # DISCOVERY
    # --------------------------------------------------

    def discover(self):
        """Return all available plugin names."""

        package = importlib.import_module(self.package)

        plugins = []

        for module in pkgutil.iter_modules(package.__path__):
            plugins.append(module.name)

        return sorted(plugins)

    # --------------------------------------------------
    # LISTING
    # --------------------------------------------------

    def list(self):
        """Return loaded plugin names."""

        return sorted(self.plugins.keys())

    def available(self):
        """Return available but unloaded plugins."""

        return sorted(set(self.discover()) - set(self.plugins))

    # --------------------------------------------------
    # LOAD
    # --------------------------------------------------

    def load(self, name):
        """Load a plugin."""

        if name in self.plugins:
            log.warning("[PLUGIN] ⚠️ Plugin already loaded: %s", name)
            return

        log.info("[PLUGIN] 📦 Loading plugin: %s", name)

        module_path = f"{self.package}.{name}"

        module = importlib.import_module(module_path)

        meta = getattr(module, "PLUGIN_META", {})

        # dependency resolution
        for dep in meta.get("requires", []):

            if dep not in self.plugins:

                log.info(
                    "[PLUGIN] 🔗 Loading dependency '%s' for '%s'",
                    dep,
                    name,
                )

                self.load(dep)

        self._register_commands(name, module)

        if hasattr(module, "setup"):
            module.setup(self.bot)

        self.plugins[name] = module
        self.meta[name] = meta

        log.info("[PLUGIN] ✅ Plugin loaded: %s", name)

    # --------------------------------------------------
    # COMMAND REGISTRATION
    # --------------------------------------------------

    def _register_commands(self, plugin_name, module):

        for _, obj in inspect.getmembers(module):

            if hasattr(obj, "_command_names"):

                for name in obj._command_names:

                    if name in self.bot.commands:

                        log.warning(
                            "[PLUGIN] ⚠️ Command conflict: %s "
                            "(plugin: %s)",
                            name,
                            plugin_name,
                        )

                    self.bot.commands[name] = obj
                    self.command_owner[name] = plugin_name

    # --------------------------------------------------
    # UNLOAD
    # --------------------------------------------------

    def unload(self, name):
        """Unload a plugin."""

        if name not in self.plugins:

            log.warning("[PLUGIN] ⚠️ Plugin not loaded: %s", name)
            return

        log.info("[PLUGIN] 📤 Unloading plugin: %s", name)

        module = self.plugins[name]

        if hasattr(module, "teardown"):
            module.teardown(self.bot)

        # remove commands
        remove = []

        for cmd, owner in self.command_owner.items():
            if owner == name:
                remove.append(cmd)

        for cmd in remove:

            del self.bot.commands[cmd]
            del self.command_owner[cmd]

        # remove module
        module_path = f"{self.package}.{name}"

        if module_path in sys.modules:
            del sys.modules[module_path]

        del self.plugins[name]
        del self.meta[name]

        log.info("[PLUGIN] 📤 Plugin unloaded: %s", name)

    # --------------------------------------------------
    # RELOAD
    # --------------------------------------------------

    def reload(self, name):
        """Reload a plugin."""

        log.info("[PLUGIN] 🔄 Reloading plugin: %s", name)

        self.unload(name)

        self.load(name)

    # --------------------------------------------------
    # BULK LOAD
    # --------------------------------------------------

    def load_all(self):
        """Load all discovered plugins."""

        for plugin in self.discover():

            if plugin not in self.plugins:

                try:
                    self.load(plugin)

                except Exception:

                    log.exception(
                        "[PLUGIN] ❌ Failed to load plugin: %s",
                        plugin,
                    )
