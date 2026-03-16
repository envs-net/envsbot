"""
Property-based tests for PluginManager.

These tests validate the robustness of the plugin loading system by
generating many different plugin dependency graphs automatically.

Unlike the deterministic unit tests, which verify specific behaviors,
these tests focus on a broader property:

    The PluginManager must never crash or recurse infinitely
    regardless of the plugin dependency graph.

Hypothesis is used to generate random sets of plugin names. From these
names, random dependency graphs are constructed, including graphs that
contain:

- deep dependency chains
- multiple branching dependencies
- disconnected plugin groups
- circular dependencies
- dense dependency graphs

The test then attempts to load each plugin using PluginManager. The
expected property is that the loader always handles these graphs
safely without raising unexpected exceptions.

Test isolation
--------------

Plugins are simulated using dynamically created modules inserted into
`sys.modules` under the `plugins.*` namespace. A fixture automatically
removes these modules after each test to ensure the test environment
remains clean and deterministic.

These property tests complement the deterministic tests in
`test_plugin_manager_unit.py`, which verify specific expected behavior
such as dependency loading, circular dependency detection, and setup
failure safety.
"""

import types
import sys

import pytest
from hypothesis import given, strategies as st, settings

from utils.plugin_manager import PluginManager


class DummyBot:
    def __init__(self):
        self.commands = {}


def make_plugin(name, requires):
    module = types.ModuleType(name)
    module.PLUGIN_META = {"requires": requires}
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


plugin_names = st.lists(
    st.text(min_size=1, max_size=4),
    min_size=1,
    max_size=8,
    unique=True,
)


@settings(max_examples=100)
@given(plugin_names)
def test_loader_never_crashes(plugin_names):
    """
    Property test: PluginManager must never crash regardless
    of dependency graph layout.
    """

    import random

    bot = DummyBot()
    pm = PluginManager(bot, package="plugins")

    graph = {}

    for name in plugin_names:
        deps = random.sample(plugin_names,
                             k=random.randint(0, len(plugin_names)))
        deps = [d for d in deps if d != name]
        graph[name] = deps

    for name, deps in graph.items():
        make_plugin(f"plugins.{name}", deps)

    for name in graph.keys():
        try:
            pm.load(name)
        except Exception as e:
            pytest.fail(f"PluginManager crashed on graph {graph}: {e}")
