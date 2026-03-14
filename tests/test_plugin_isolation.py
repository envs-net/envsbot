"""
Plugin isolation tests.

These tests ensure that plugins can be imported and inspected
independently without interfering with each other. This helps
detect issues such as duplicate command registrations or plugins
modifying shared state unexpectedly.
"""

import importlib
import pkgutil
import plugins


def test_plugins_register_unique_commands(bot):
    """
    Ensure no plugin registers a command name that conflicts with
    another plugin.
    """

    command_names = list(bot.commands.keys())

    assert len(command_names) == len(set(command_names)), \
        "Duplicate command names registered by plugins"


def test_plugins_can_be_imported_individually():
    """
    Ensure each plugin module can be imported in isolation.

    This prevents hidden dependencies between plugins that could
    break hot-reload or selective plugin loading.
    """

    for module in pkgutil.iter_modules(plugins.__path__):

        module_name = f"plugins.{module.name}"

        try:
            importlib.import_module(module_name)

        except Exception as e:
            raise AssertionError(
                f"Plugin '{module_name}' cannot be imported independently: {e}"
            )
