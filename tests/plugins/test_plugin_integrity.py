"""
Plugin integrity tests.

These tests verify that all plugin modules can be imported and that
they provide valid metadata required by the bot's plugin system.
"""

import importlib
import pkgutil
import plugins


def test_plugins_importable():
    """
    Ensure all plugin modules can be imported without raising errors.
    """

    for module in pkgutil.iter_modules(plugins.__path__):

        module_name = f"plugins.{module.name}"

        try:
            importlib.import_module(module_name)

        except Exception as e:
            raise AssertionError(f"Plugin '{module_name}' failed to import: {e}")


def test_plugins_have_metadata():
    """
    Ensure each plugin defines a PLUGIN_META dictionary.
    """

    for module in pkgutil.iter_modules(plugins.__path__):

        module_name = f"plugins.{module.name}"
        mod = importlib.import_module(module_name)

        assert hasattr(mod, "PLUGIN_META"), f"{module_name} missing PLUGIN_META"

        meta = mod.PLUGIN_META

        assert isinstance(meta, dict), f"{module_name} PLUGIN_META must be dict"


def test_plugin_metadata_fields():
    """
    Ensure plugin metadata contains required fields.
    """

    required_fields = ["name", "version", "description", "category"]

    for module in pkgutil.iter_modules(plugins.__path__):

        module_name = f"plugins.{module.name}"
        mod = importlib.import_module(module_name)

        meta = getattr(mod, "PLUGIN_META", {})

        for field in required_fields:
            assert field in meta, f"{module_name} missing metadata field '{field}'"
