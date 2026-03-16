"""
plugin_manager.py

Plugin loading, unloading, and lifecycle management for the bot.

This module is responsible for discovering plugin modules, importing them,
registering their commands, and unloading them safely when requested.
It acts as the central coordinator between plugin code and the command
system.

## Design goals

* Allow plugins to be loaded and unloaded dynamically
* Support safe hot-reloading of plugin modules
* Ensure commands are registered only when a plugin is active
* Ensure commands are removed when a plugin is unloaded
* Keep plugin authorship simple (decorator-based commands)

## Plugin model

Plugins are normal Python modules located in the configured plugin
directory. A plugin typically exposes one or more command handlers
using the @command decorator from utils.command.

Example:

```
@command("ping")
async def ping_handler(...):
    ...
```

During import, the decorator attaches command metadata to the handler
function but does not register the command globally. The PluginManager
performs the actual registration during plugin load.

## Command registration

When a plugin is loaded, PluginManager scans the module for callables
that contain command metadata (stored by the decorator). For each
declared command it registers the command with the global
CommandRegistry.

This ensures that command registration happens in a controlled place
and that plugin reloads cannot accidentally accumulate duplicate
commands.

## Command removal

When a plugin is unloaded, the PluginManager removes all commands
belonging to that plugin using the registry’s ownership tracking:

```
CommandRegistry.remove_by_plugin(plugin_name)
```

This guarantees that unloading a plugin leaves no orphaned commands
behind.

## Security rules

Plugins whose names begin with "_" are considered internal plugins.
Commands from such plugins automatically require at least ADMIN role
even if a lower role was declared in the decorator.

This prevents accidental exposure of privileged internal commands.

## Architecture overview

```
plugin module
      │
      ▼
@command decorator
      │
      ▼
handler.__commands__ metadata
      │
      ▼
PluginManager._register_commands()
      │
      ▼
CommandRegistry.register(...)
      │
      ▼
resolve_command()
      │
      ▼
Command.handler(...)
```

The PluginManager therefore owns the command lifecycle while the
CommandRegistry owns command lookup and execution routing.
"""


import importlib
import pkgutil
import sys
import inspect
import logging

from utils.command import COMMANDS, Role

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

    def load(self, name, _stack=None):
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

        if _stack is None:
            _stack = []

        if name in _stack:
            log.error(
                "[PLUGIN] 🔁 Circular dependency detected: %s -> %s",
                " -> ".join(_stack),
                name,
            )
            return

        _stack.append(name)

        try:

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

                    self.load(dep, _stack)

            # --------------------------------------------------
            # SETUP HOOK
            # --------------------------------------------------

            if hasattr(module, "setup"):
                module.setup(self.bot)

            # --------------------------------------------------
            # COMMAND REGISTRATION
            # --------------------------------------------------

            self._register_commands(name, module)

            self.plugins[name] = module
            self.meta[name] = meta

            log.info("[PLUGIN] ✅ Plugin loaded: %s", name)

        finally:
            _stack.pop()

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

                # --- REGISTER COMMAND ---
                for name, cmd in getattr(obj, "__commands__", []):
                    COMMANDS.register(name, cmd, plugin_name)

                for name in obj._command_names:
                    # --------------------------------------------------
                    # INTERNAL PLUGIN PERMISSION POLICY
                    # --------------------------------------------------

                    if is_internal:

                        tokens = tuple(name.lower().split())
                        cmd = COMMANDS.get(tokens)

                        if cmd and cmd.role > Role.ADMIN:

                            log.debug(
                                "[PLUGIN] 🔒 Elevating role for internal command '%s' to ADMIN",
                                name,
                            )

                            cmd.role = Role.ADMIN

    # --------------------------------------------------
    # UNLOAD
    # --------------------------------------------------

    def unload(self, plugin_name: str):
        """
        Unload a plugin and remove all of its commands.
        """

        module = self.plugins.get(plugin_name)

        if not module:
            return False

        # remove commands belonging to this plugin
        COMMANDS.remove_by_plugin(plugin_name)

        # remove plugin module
        self.plugins.pop(plugin_name, None)

        # remove from sys.modules so reload works correctly
        modname = module.__name__

        if modname in sys.modules:
            del sys.modules[modname]

        return True

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
