"""
Unit tests for PluginManager.

These tests verify the deterministic behavior of the plugin loading
system implemented in `utils.plugin_manager.PluginManager`.

The goal of these tests is to ensure correct handling of the core
plugin lifecycle features without relying on real plugin files.
Instead, temporary in-memory modules are created and injected into
`sys.modules` to simulate plugin packages.

Test coverage
-------------

Dependency loading
    Ensures that plugins declaring dependencies via
    `PLUGIN_META["requires"]` automatically trigger loading of those
    dependencies.

Circular dependency detection
    Verifies that circular plugin dependency graphs are detected and
    handled gracefully without causing infinite recursion.

Setup failure safety
    Ensures that if a plugin raises an exception during `setup(bot)`,
    the plugin is not partially initialized and no commands are
    registered in the bot.

Test isolation
--------------

Each test dynamically creates fake plugin modules inside `sys.modules`
under the `plugins.*` namespace. A fixture automatically removes these
modules after every test to ensure that tests remain isolated and
deterministic.

These tests validate expected behavior of specific scenarios. Broader
robustness against arbitrary dependency graphs is verified separately
using property-based tests in `test_plugin_manager_property.py`.
"""

import types
import sys
import pytest

from utils.plugin_manager import PluginManager


class DummyBot:
    def __init__(self):
        self.commands = {}


def make_plugin(name, requires=None, setup=None, commands=None):
    """
    Create a fake plugin module and register it in sys.modules.
    """
    module = types.ModuleType(name)

    module.PLUGIN_META = {"requires": requires or []}

    if setup:
        module.setup = setup

    if commands:
        for cmd_name, func in commands.items():
            func._command_names = [cmd_name]
            setattr(module, func.__name__, func)

    sys.modules[name] = module
    return module


@pytest.fixture(autouse=True)
def cleanup_modules():
    before = set(sys.modules.keys())
    yield
    after = set(sys.modules.keys())

    for name in after - before:
        if name.startswith("plugins."):
            del sys.modules[name]


def test_dependency_loading():
    """
    Dependencies should automatically load.
    """

    bot = DummyBot()
    pm = PluginManager(bot, package="plugins")

    make_plugin("plugins.dep")
    make_plugin("plugins.main", requires=["dep"])

    pm.load("main")

    assert "main" in pm.plugins
    assert "dep" in pm.plugins


def test_circular_dependency_detection(caplog):
    """
    Circular dependencies should not recurse infinitely.
    """

    bot = DummyBot()
    pm = PluginManager(bot, package="plugins")

    make_plugin("plugins.a", requires=["b"])
    make_plugin("plugins.b", requires=["a"])

    pm.load("a")

    assert "Circular dependency detected" in caplog.text


def test_setup_failure_does_not_register_commands():
    """
    Commands must not register if setup() fails.
    """

    bot = DummyBot()
    pm = PluginManager(bot, package="plugins")

    def setup_fail(bot):
        raise RuntimeError("boom")

    def handler():
        pass

    handler._command_names = ["test"]

    make_plugin(
        "plugins.bad",
        setup=setup_fail,
        commands={"test": handler},
    )

    with pytest.raises(RuntimeError):
        pm.load("bad")

    assert "test" not in bot.commands
