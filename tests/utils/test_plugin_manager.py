import asyncio
import importlib
import inspect
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils import plugin_manager
from utils.plugin_manager import PluginManager
from utils.command import CommandRegistry, Role, command


class FakeBot:
    def __init__(self):
        self.calls = []

    def on(self, event, handler):
        self.calls.append(("on", event, handler))

    def off(self, event, handler):
        self.calls.append(("off", event, handler))


def make_fake_plugin(meta=None, has_hooks=True):
    mod = types.ModuleType("fake_plugin")
    meta = meta or {}
    setattr(mod, 'PLUGIN_META', meta)
    if has_hooks:
        async def _on_load(bot): mod.on_load_called = True
        async def _on_unload(bot): mod.on_unload_called = True
        setattr(mod, 'on_load', _on_load)
        setattr(mod, 'on_unload', _on_unload)
    else:
        # Use a safe no-op lambda instead of None
        setattr(mod, 'on_load', lambda bot: None)
        setattr(mod, 'on_unload', lambda bot: None)
    setattr(mod, "BOT_EVENTS", [])
    setattr(mod, "__name__", meta.get("name", "fake_plugin"))
    return mod


def test_split_package_command_facades_register_once(monkeypatch):
    registry = CommandRegistry()
    monkeypatch.setattr(plugin_manager, "COMMANDS", registry)
    pm = PluginManager(bot=FakeBot())

    modules = {
        "rooms": ("core_plugins.rooms", "rooms list"),
        "users": ("core_plugins.users", "users delete"),
        "idlerpg": ("plugins.idlerpg", "idlerpg"),
        "reminder": ("plugins.reminder", "remind"),
        "rss": ("plugins.rss", "rss"),
        "vcard": ("plugins.vcard", "birthday"),
    }

    for plugin_name, (module_name, expected_command) in modules.items():
        module = importlib.import_module(module_name)
        for temporary_name in ("_part", "_value"):
            assert not hasattr(module, temporary_name)

        handlers: dict[int, list[str]] = {}
        for attr_name, obj in inspect.getmembers(module):
            if callable(obj) and hasattr(obj, "_command_names"):
                handlers.setdefault(id(obj), []).append(attr_name)
        duplicates = {
            id_: names for id_, names in handlers.items() if len(names) > 1
        }
        assert duplicates == {}

        pm._register_commands(plugin_name, module)
        assert tuple(expected_command.split()) in registry.index


@pytest.mark.asyncio
async def test_lifecycle_full_load_and_unload(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot=bot, package="fakepkg")
    mod = make_fake_plugin(meta={'name': 'p1'})
    # Patch import_module to always return our mod
    monkeypatch.setattr(plugin_manager.importlib, "import_module",
                        lambda name: mod)
    # Patch iter_modules to simulate one plugin 'p1'

    class SimpleModule:
        name = "p1"
    monkeypatch.setattr(plugin_manager.pkgutil, "iter_modules",
                        lambda path: [SimpleModule()])
    # Actually load and unload
    pm.meta['p1'] = {'name': 'p1'}
    pm.plugins.clear()
    await pm.load('p1')
    assert 'p1' in pm.plugins
    assert getattr(mod, "on_load_called", False)
    await pm.unload('p1')
    assert 'p1' not in pm.plugins
    assert getattr(mod, "on_unload_called", False)


@pytest.mark.asyncio
async def test_load_plugin_with_no_hooks(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot=bot)
    # Use safe no-op for hooks
    mod = make_fake_plugin(meta={'name': 'nohooks'}, has_hooks=False)
    monkeypatch.setattr("utils.plugin_manager.importlib.import_module",
                        lambda name: mod)
    pm.meta["nohooks"] = {'name': 'nohooks'}
    await pm.load("nohooks")


@pytest.mark.asyncio
async def test_failed_load_cleans_events_and_tasks(monkeypatch):
    class EventBot:
        def __init__(self):
            self.calls = []
            self.tasks = types.SimpleNamespace(
                created=[],
                cancel_plugin=AsyncMock(return_value=1),
            )

            def _create(plugin, coro, name=None):
                coro.close()
                self.tasks.created.append((plugin, name))
                return object()

            self.tasks.create = _create

        def add_event_handler(self, event, handler):
            self.calls.append(("add", event, handler))

        def del_event_handler(self, event, handler):
            self.calls.append(("del", event, handler))

    bot = EventBot()
    registry = CommandRegistry()
    monkeypatch.setattr(plugin_manager, "COMMANDS", registry)
    pm = PluginManager(bot=bot, package="fakepkg")
    bot.bot_plugins = pm

    @command("dupe", role=Role.USER)
    async def existing(_bot, _msg, _args):
        return None

    pm._register_commands("existing", types.SimpleNamespace(existing=existing))

    mod = types.ModuleType("fakepkg.bad")

    async def _never():
        await asyncio.sleep(3600)

    created_coroutines = []

    def handler(*_args):
        return None

    async def on_load(bot_arg):
        bot_arg.bot_plugins.register_event("bad", "message", handler)
        coroutine = _never()
        created_coroutines.append(coroutine)
        bot_arg.bot_plugins.create_task("bad", coroutine, name="bad-task")

    @command("dupe", role=Role.USER)
    async def duplicate(_bot, _msg, _args):
        return None

    mod.on_load = on_load
    mod.duplicate = duplicate
    monkeypatch.setattr(
        "utils.plugin_manager.importlib.import_module",
        lambda _name: mod,
    )

    with pytest.raises(ValueError, match="Command already registered"):
        await pm.load("bad")

    assert "bad" not in pm.plugins
    assert pm._event_handlers == {}
    assert bot.calls == [
        ("add", "message", handler),
        ("del", "message", handler),
    ]
    assert bot.tasks.created == [("bad", "bad-task")]
    assert inspect.getcoroutinestate(created_coroutines[0]) == inspect.CORO_CLOSED
    bot.tasks.cancel_plugin.assert_awaited_once_with("bad")
    assert tuple("dupe".split()) in registry.index
    assert registry.by_plugin == {"existing": {tuple("dupe".split())}}


@pytest.mark.asyncio
async def test_load_all_sorted(monkeypatch, caplog):
    bot = FakeBot()
    pm = PluginManager(bot, package="fakepkg")
    pm.meta = {
        "A": {"name": "A", "requires": []},
        "B": {"name": "B", "requires": ["A"]},
    }
    fake_modA = make_fake_plugin(meta={"name": "A"})
    fake_modB = make_fake_plugin(meta={"name": "B"})
    monkeypatch.setattr("utils.plugin_manager.importlib.import_module",
                        lambda name: fake_modA if "A" in name else fake_modB)
    monkeypatch.setattr(pm, "discover", lambda: ["B", "A"])
    with caplog.at_level("DEBUG", logger="utils.plugin_manager"):
        await pm.load_all()
    assert set(pm.plugins.keys()) == {"A", "B"}
    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelname == "INFO"
        and "load_all" in record.getMessage()
    ]
    assert info_messages == [
        "[PLUGIN] load_all complete: 2/2 loaded, 0 failed"
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelname == "DEBUG"
        and "load_all pass" in record.getMessage()
    ]
    assert debug_messages == [
        "[PLUGIN] load_all pass 1: 1/2 loaded, 0 failed",
        "[PLUGIN] load_all pass 2: 2/2 loaded, 0 failed",
    ]


@pytest.mark.asyncio
async def test_reload_plugins(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot)
    modA = make_fake_plugin(meta={"name": "A"})
    modB = make_fake_plugin(meta={"name": "B"})
    pm.meta = {"A": {"name": "A"}, "B": {"name": "B"}}
    pm.plugins = {"A": modA, "B": modB}
    monkeypatch.setattr(pm, "discover", lambda: ["A", "B"])
    monkeypatch.setattr("utils.plugin_manager.importlib.import_module",
                        lambda name: modA if "A" in name else modB)
    for name in ["A", "B"]:
        await pm.reload(name)
    assert set(pm.plugins.keys()) == {"A", "B"}


@pytest.mark.asyncio
async def test_dynamic_load_runs_on_ready_after_startup(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot, package="fakepkg", core_package=None)
    calls = []
    mod = make_fake_plugin(meta={"name": "late", "requires": []})

    async def on_ready(bot_arg):
        assert bot_arg is bot
        calls.append("ready")

    mod.on_ready = on_ready
    pm._ready = True
    monkeypatch.setattr(
        "utils.plugin_manager.importlib.import_module",
        lambda _name: mod,
    )

    await pm.load("late")

    assert calls == ["ready"]
    assert "late" in pm.plugins


@pytest.mark.asyncio
async def test_dynamic_load_rolls_back_when_on_ready_fails(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    mod = make_fake_plugin(meta={"name": "late", "requires": []})

    async def on_ready(_bot):
        raise RuntimeError("ready failed")

    mod.on_ready = on_ready
    pm._ready = True
    monkeypatch.setattr(
        "utils.plugin_manager.importlib.import_module",
        lambda _name: mod,
    )

    with pytest.raises(RuntimeError, match="ready failed"):
        await pm.load("late")

    assert "late" not in pm.plugins
    assert pm.failed_plugins["late"] == "ready failed"


@pytest.mark.asyncio
async def test_load_rejects_circular_dependencies(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    modules = {
        "A": make_fake_plugin(meta={"name": "A", "requires": ["B"]}),
        "B": make_fake_plugin(meta={"name": "B", "requires": ["A"]}),
    }
    monkeypatch.setattr(
        "utils.plugin_manager.importlib.import_module",
        lambda name: modules[name.rsplit(".", 1)[-1]],
    )

    with pytest.raises(RuntimeError, match="Circular plugin dependency"):
        await pm.load("A")

    assert pm.plugins == {}


@pytest.mark.asyncio
async def test_reload_stops_when_unload_reports_failure(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    pm.plugins["A"] = make_fake_plugin(meta={"name": "A"})
    pm.meta["A"] = {"name": "A", "requires": []}
    monkeypatch.setattr(
        pm,
        "unload",
        AsyncMock(return_value=(False, "cleanup failed")),
    )
    load = AsyncMock()
    monkeypatch.setattr(pm, "load", load)

    success, message = await pm.reload("A")

    assert success is False
    assert "cleanup failed" in message
    load.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_reload_keeps_precomputed_dependency_order(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    metadata = {
        "base": {"name": "base", "requires": []},
        "mid": {"name": "mid", "requires": ["base"]},
        "leaf": {"name": "leaf", "requires": ["mid"]},
    }
    modules = {
        name: make_fake_plugin(meta=meta)
        for name, meta in metadata.items()
    }
    pm.plugins = dict(modules)
    pm.meta = {name: dict(meta) for name, meta in metadata.items()}
    calls = []

    async def unload(name, force=False, *, allow_core=False):
        calls.append(("unload", name, force, allow_core))
        pm.plugins.pop(name)
        pm.meta.pop(name)
        return True, f"Plugin {name} unloaded"

    async def load(name, _stack=None):
        calls.append(("load", name))
        pm.plugins[name] = modules[name]
        pm.meta[name] = metadata[name]

    monkeypatch.setattr(pm, "unload", unload)
    monkeypatch.setattr(pm, "load", load)

    success, message = await pm.reload("base", auto=True)

    assert success is True
    assert "2 dependent" in message
    assert calls == [
        ("unload", "leaf", True, True),
        ("unload", "mid", True, True),
        ("unload", "base", False, True),
        ("load", "base"),
        ("load", "mid"),
        ("load", "leaf"),
    ]


@pytest.mark.asyncio
async def test_auto_reload_restores_dependents_after_unload_failure(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    metadata = {
        "base": {"name": "base", "requires": []},
        "mid": {"name": "mid", "requires": ["base"]},
        "leaf": {"name": "leaf", "requires": ["mid"]},
    }
    modules = {
        name: make_fake_plugin(meta=meta)
        for name, meta in metadata.items()
    }
    pm.plugins = dict(modules)
    pm.meta = {name: dict(meta) for name, meta in metadata.items()}
    calls = []

    async def unload(name, force=False, *, allow_core=False):
        calls.append(("unload", name))
        if name == "mid":
            return False, "mid cleanup failed"
        pm.plugins.pop(name)
        pm.meta.pop(name)
        return True, f"Plugin {name} unloaded"

    async def load(name, _stack=None):
        calls.append(("load", name))
        pm.plugins[name] = modules[name]
        pm.meta[name] = metadata[name]

    monkeypatch.setattr(pm, "unload", unload)
    monkeypatch.setattr(pm, "load", load)

    success, message = await pm.reload("base", auto=True)

    assert success is False
    assert "mid cleanup failed" in message
    assert set(pm.plugins) == {"base", "mid", "leaf"}
    assert calls == [
        ("unload", "leaf"),
        ("unload", "mid"),
        ("load", "leaf"),
    ]


@pytest.mark.asyncio
async def test_auto_reload_restores_dependents_when_target_unload_fails(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    metadata = {
        "base": {"name": "base", "requires": []},
        "mid": {"name": "mid", "requires": ["base"]},
        "leaf": {"name": "leaf", "requires": ["mid"]},
    }
    modules = {
        name: make_fake_plugin(meta=meta)
        for name, meta in metadata.items()
    }
    pm.plugins = dict(modules)
    pm.meta = {name: dict(meta) for name, meta in metadata.items()}
    calls = []

    async def unload(name, force=False, *, allow_core=False):
        calls.append(("unload", name))
        if name == "base":
            return False, "base cleanup failed"
        pm.plugins.pop(name)
        pm.meta.pop(name)
        return True, f"Plugin {name} unloaded"

    async def load(name, _stack=None):
        calls.append(("load", name))
        pm.plugins[name] = modules[name]
        pm.meta[name] = metadata[name]

    monkeypatch.setattr(pm, "unload", unload)
    monkeypatch.setattr(pm, "load", load)

    success, message = await pm.reload("base", auto=True)

    assert success is False
    assert "base cleanup failed" in message
    assert set(pm.plugins) == {"base", "mid", "leaf"}
    assert calls == [
        ("unload", "leaf"),
        ("unload", "mid"),
        ("unload", "base"),
        ("load", "mid"),
        ("load", "leaf"),
    ]


@pytest.mark.asyncio
async def test_auto_reload_reports_dependent_load_failure(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    metadata = {
        "base": {"name": "base", "requires": []},
        "leaf": {"name": "leaf", "requires": ["base"]},
    }
    modules = {
        name: make_fake_plugin(meta=meta)
        for name, meta in metadata.items()
    }
    pm.plugins = dict(modules)
    pm.meta = {name: dict(meta) for name, meta in metadata.items()}

    async def unload(name, force=False, *, allow_core=False):
        pm.plugins.pop(name)
        pm.meta.pop(name)
        return True, f"Plugin {name} unloaded"

    async def load(name, _stack=None):
        if name == "leaf":
            raise RuntimeError("leaf import failed")
        pm.plugins[name] = modules[name]
        pm.meta[name] = metadata[name]

    monkeypatch.setattr(pm, "unload", unload)
    monkeypatch.setattr(pm, "load", load)

    success, message = await pm.reload("base", auto=True)

    assert success is False
    assert "leaf import failed" in message
    assert set(pm.plugins) == {"base"}


@pytest.mark.asyncio
async def test_reload_all_uses_one_dependency_ordered_cycle(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    metadata = {
        "base": {"name": "base", "requires": []},
        "mid": {"name": "mid", "requires": ["base"]},
        "leaf": {"name": "leaf", "requires": ["mid"]},
    }
    modules = {
        name: make_fake_plugin(meta=meta)
        for name, meta in metadata.items()
    }
    pm.plugins = dict(modules)
    pm.meta = {name: dict(meta) for name, meta in metadata.items()}
    calls = []

    async def unload(name, force=False, *, allow_core=False):
        assert force is True
        assert allow_core is True
        calls.append(("unload", name))
        pm.plugins.pop(name)
        pm.meta.pop(name)
        return True, f"Plugin {name} unloaded"

    async def load(name, _stack=None):
        calls.append(("load", name))
        pm.plugins[name] = modules[name]
        pm.meta[name] = metadata[name]

    monkeypatch.setattr(pm, "unload", unload)
    monkeypatch.setattr(pm, "load", load)

    success, message = await pm.reload_all()

    assert success is True
    assert "3 plugins" in message
    assert calls == [
        ("unload", "leaf"),
        ("unload", "mid"),
        ("unload", "base"),
        ("load", "base"),
        ("load", "mid"),
        ("load", "leaf"),
    ]


@pytest.mark.asyncio
async def test_reload_all_refuses_incomplete_loaded_dependency_state(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    pm.plugins["leaf"] = make_fake_plugin(meta={"name": "leaf"})
    pm.meta["leaf"] = {"name": "leaf", "requires": ["missing"]}
    unload = AsyncMock()
    monkeypatch.setattr(pm, "unload", unload)

    success, message = await pm.reload_all()

    assert success is False
    assert "leaf requires missing" in message
    unload.assert_not_awaited()


@pytest.mark.asyncio
async def test_reload_all_reports_plugins_that_remain_unloaded(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    metadata = {
        "base": {"name": "base", "requires": []},
        "leaf": {"name": "leaf", "requires": ["base"]},
    }
    pm.plugins = {
        name: make_fake_plugin(meta=meta)
        for name, meta in metadata.items()
    }
    pm.meta = {name: dict(meta) for name, meta in metadata.items()}

    async def unload(name, force=False, *, allow_core=False):
        pm.plugins.pop(name)
        pm.meta.pop(name)
        return True, f"Plugin {name} unloaded"

    async def load(name, _stack=None):
        raise RuntimeError(f"{name} failed")

    monkeypatch.setattr(pm, "unload", unload)
    monkeypatch.setattr(pm, "load", load)

    success, message = await pm.reload_all()

    assert success is False
    assert "base: base failed" in message
    assert "leaf: leaf failed" in message
    assert pm.plugins == {}


@pytest.mark.asyncio
async def test_load_all_skips_loaded_plugins_without_hiding_existing_failure(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    pm.plugins["base"] = make_fake_plugin(meta={"name": "base"})
    pm.meta["base"] = {"name": "base", "requires": []}
    pm.failed_plugins["base"] = "old failure"
    monkeypatch.setattr(pm, "discover", lambda: ["base"])
    load = AsyncMock()
    monkeypatch.setattr(pm, "load", load)

    success, message = await pm.load_all()

    load.assert_not_awaited()
    assert success is False
    assert "1 failure" in message
    assert pm.failed_plugins["base"] == "old failure"


@pytest.mark.asyncio
async def test_call_on_ready_records_failures_and_blocks_dependents():
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    calls = []

    base = make_fake_plugin(meta={"name": "base", "requires": []})
    leaf = make_fake_plugin(meta={"name": "leaf", "requires": ["base"]})

    async def broken_ready(_bot):
        calls.append("base-broken")
        raise RuntimeError("database unavailable")

    async def good_base_ready(_bot):
        calls.append("base-ready")

    async def leaf_ready(_bot):
        calls.append("leaf-ready")

    base.on_ready = broken_ready
    leaf.on_ready = leaf_ready
    pm.plugins = {"base": base, "leaf": leaf}
    pm.meta = {
        "base": {"name": "base", "requires": []},
        "leaf": {"name": "leaf", "requires": ["base"]},
    }

    await pm.call_on_ready()

    assert calls == ["base-broken"]
    assert "on_ready: RuntimeError: database unavailable" == pm.failed_plugins["base"]
    assert "blocked by failed dependency: base" in pm.failed_plugins["leaf"]
    assert pm._ready is True

    base.on_ready = good_base_ready
    await pm.call_on_ready()

    assert calls == ["base-broken", "base-ready", "leaf-ready"]
    assert pm.failed_plugins == {}


@pytest.mark.asyncio
async def test_unload_all_runs_hooks_in_reverse_dependency_order(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    calls = []
    modules = {}
    metadata = {
        "base": {"name": "base", "requires": []},
        "leaf": {"name": "leaf", "requires": ["base"]},
    }
    for name, meta in metadata.items():
        module = make_fake_plugin(meta=meta)

        async def on_unload(_bot, plugin_name=name):
            calls.append(plugin_name)

        module.on_unload = on_unload
        modules[name] = module

    pm.plugins = dict(modules)
    pm.meta = {name: dict(meta) for name, meta in metadata.items()}
    pm._ready = True
    monkeypatch.setattr(pm, "_detach_module", lambda _module, _name: None)

    success, message = await pm.unload_all()

    assert success is True
    assert "2 plugins" in message
    assert calls == ["leaf", "base"]
    assert pm.plugins == {}
    assert pm.meta == {}
    assert pm._ready is False


@pytest.mark.asyncio
async def test_unload_refuses_to_detach_plugin_with_stubborn_task(monkeypatch):
    class EventBot(FakeBot):
        def __init__(self):
            super().__init__()
            self.removed = []
            self.tasks = types.SimpleNamespace(
                cancel_plugin=AsyncMock(return_value=1),
                snapshot=lambda include_done=False: [
                    types.SimpleNamespace(
                        plugin="worker",
                        name="stubborn-loop",
                        status="running",
                    )
                ],
            )

        def del_event_handler(self, event, handler):
            self.removed.append((event, handler))

    bot = EventBot()
    pm = PluginManager(bot, package="fakepkg", core_package=None)
    module = make_fake_plugin(meta={"name": "worker", "requires": []})
    handler = object()
    pm.plugins["worker"] = module
    pm.meta["worker"] = {"name": "worker", "requires": []}
    pm._event_handlers["worker"] = [("message", handler)]
    detach = MagicMock()
    monkeypatch.setattr(pm, "_detach_module", detach)

    success, message = await pm.unload("worker")

    assert success is False
    assert "still has running task" in message
    assert "worker" in pm.plugins
    assert "worker" in pm.meta
    assert pm._event_handlers["worker"] == [("message", handler)]
    assert bot.removed == []
    detach.assert_not_called()


@pytest.mark.asyncio
async def test_shutdown_quiesce_cancels_active_lifecycle_operation(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    pm.plugins = {"A": make_fake_plugin(meta={"name": "A"})}
    pm.meta = {"A": {"name": "A", "requires": []}}
    entered = asyncio.Event()
    block = asyncio.Event()

    async def unload(name, force=False, *, allow_core=False):
        entered.set()
        await block.wait()
        pm.plugins.pop(name, None)
        pm.meta.pop(name, None)
        return True, f"Plugin {name} unloaded"

    monkeypatch.setattr(pm, "unload", unload)

    reload_task = asyncio.create_task(pm.reload("A"), name="test-plugin-reload")
    await entered.wait()

    result = await pm.quiesce_for_shutdown(
        grace_timeout=0.0,
        cancel_timeout=1.0,
    )

    assert result["status"] == "cancelled"
    assert result["operation"] == "reload"
    assert reload_task.cancelled()
    assert pm._lifecycle_lock.locked() is False

    with pytest.raises(RuntimeError, match="shutting down"):
        await pm.reload("A")

    block.set()
    success, _message = await pm.unload_all()
    assert success is True
    assert pm.plugins == {}


@pytest.mark.asyncio
async def test_shutdown_quiesce_rejects_lifecycle_waiter_queued_before_shutdown(
    monkeypatch,
):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    pm.plugins = {
        "A": make_fake_plugin(meta={"name": "A"}),
        "B": make_fake_plugin(meta={"name": "B"}),
    }
    pm.meta = {
        "A": {"name": "A", "requires": []},
        "B": {"name": "B", "requires": []},
    }
    entered = asyncio.Event()
    block = asyncio.Event()

    async def unload(name, force=False, *, allow_core=False):
        if name == "A":
            entered.set()
            await block.wait()
        pm.plugins.pop(name, None)
        pm.meta.pop(name, None)
        return True, f"Plugin {name} unloaded"

    async def load(name, _stack=None):
        pm.plugins[name] = make_fake_plugin(meta={"name": name})
        pm.meta[name] = {"name": name, "requires": []}

    monkeypatch.setattr(pm, "unload", unload)
    monkeypatch.setattr(pm, "load", load)

    first = asyncio.create_task(pm.reload("A"))
    await entered.wait()
    queued = asyncio.create_task(pm.reload("B"))
    await asyncio.sleep(0)

    result = await pm.quiesce_for_shutdown(
        grace_timeout=0.0,
        cancel_timeout=1.0,
    )

    assert result["status"] == "cancelled"
    assert first.cancelled()
    with pytest.raises(RuntimeError, match="shutting down"):
        await asyncio.gather(queued)
    assert "B" in pm.plugins


@pytest.mark.asyncio
async def test_reload_operations_are_serialized(monkeypatch):
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    pm.plugins = {
        "A": make_fake_plugin(meta={"name": "A"}),
        "B": make_fake_plugin(meta={"name": "B"}),
    }
    pm.meta = {
        "A": {"name": "A", "requires": []},
        "B": {"name": "B", "requires": []},
    }
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    calls = []

    async def unload(name, force=False, *, allow_core=False):
        calls.append(("unload", name))
        if name == "A":
            first_started.set()
            await release_first.wait()
        pm.plugins.pop(name, None)
        pm.meta.pop(name, None)
        return True, f"Plugin {name} unloaded"

    async def load(name, _stack=None):
        calls.append(("load", name))
        pm.plugins[name] = make_fake_plugin(meta={"name": name})
        pm.meta[name] = {"name": name, "requires": []}

    monkeypatch.setattr(pm, "unload", unload)
    monkeypatch.setattr(pm, "load", load)

    first = asyncio.create_task(pm.reload("A"))
    await first_started.wait()
    second = asyncio.create_task(pm.reload("B"))
    await asyncio.sleep(0)

    assert calls == [("unload", "A")]

    release_first.set()
    assert (await first)[0] is True
    assert (await second)[0] is True
    assert calls == [
        ("unload", "A"),
        ("load", "A"),
        ("unload", "B"),
        ("load", "B"),
    ]


@pytest.mark.asyncio
async def test_unload_with_dependents(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot)
    pm.meta = {
        "X": {"name": "X", "requires": []},
        "Y": {"name": "Y", "requires": ["X"]},
    }
    pm.plugins["X"] = make_fake_plugin(meta={"name": "X"})
    pm.plugins["Y"] = make_fake_plugin(meta={"name": "Y"})
    # Should not unload since dependents exist, and no Exception is raised
    await pm.unload("X")
    assert "X" in pm.plugins
    # Remove the dependent and now it should succeed
    pm.plugins.pop("Y")
    pm.meta.pop("Y")
    await pm.unload("X")
    assert "X" not in pm.plugins

@pytest.mark.asyncio
async def test_core_plugin_cannot_be_unloaded_publicly(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot)
    pm.plugins["help"] = make_fake_plugin(meta={"name": "help"})
    pm.meta["help"] = {"name": "help"}
    pm.plugin_sources["help"] = {"package": "core_plugins", "core": True}

    success, message = await pm.unload("help", force=True)

    assert success is False
    assert "core plugin" in message
    assert "help" in pm.plugins


@pytest.mark.asyncio
async def test_core_plugin_reload_uses_internal_unload(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot)
    old_mod = make_fake_plugin(meta={"name": "help"})
    new_mod = make_fake_plugin(meta={"name": "help"})
    pm.plugins["help"] = old_mod
    pm.meta["help"] = {"name": "help"}
    pm.plugin_sources["help"] = {"package": "core_plugins", "core": True}
    monkeypatch.setattr("utils.plugin_manager.importlib.import_module", lambda name: new_mod)

    success, message = await pm.reload("help")

    assert success is True
    assert "help" in pm.plugins
    assert "reloaded" in message


def test_source_discovery_precedence_and_fallback(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot)

    packages = {
        "core_plugins": types.SimpleNamespace(__path__=["core-path"]),
        "plugins": types.SimpleNamespace(__path__=["plugin-path"]),
        "notpkg": types.SimpleNamespace(),
    }

    def fake_import(name):
        if name == "missing":
            raise ImportError("missing")
        return packages[name]

    def fake_iter_modules(path):
        if path == ["core-path"]:
            return [types.SimpleNamespace(name="help"), types.SimpleNamespace(name="dupe")]
        if path == ["plugin-path"]:
            return [types.SimpleNamespace(name="xkcd"), types.SimpleNamespace(name="dupe")]
        return []

    monkeypatch.setattr(plugin_manager.importlib, "import_module", fake_import)
    monkeypatch.setattr(plugin_manager.pkgutil, "iter_modules", fake_iter_modules)

    assert pm.discover() == ["dupe", "help", "xkcd"]
    assert pm.plugin_sources["dupe"] == {"package": "core_plugins", "core": True}
    assert pm._module_path("xkcd") == "plugins.xkcd"
    assert pm.is_core_plugin("help") is True
    assert pm.is_core_plugin("xkcd") is False

    single = PluginManager(bot, package="missing", core_package=None)
    assert single.discover() == []
    assert single._source_info("custom") == {"package": "missing", "core": False}


def test_topological_sort_orders_dependencies_first():
    bot = FakeBot()
    pm = PluginManager(bot, package="fakepkg")
    pm.meta = {
        "base": {"name": "base", "requires": []},
        "mid": {"name": "mid", "requires": ["base"]},
        "leaf": {"name": "leaf", "requires": ["mid"]},
    }

    assert pm._topological_sort(["leaf", "base", "mid"]) == ["base", "mid", "leaf"]


def test_topological_sort_rejects_cycles():
    pm = PluginManager(FakeBot(), package="fakepkg")
    pm.meta = {
        "A": {"name": "A", "requires": ["B"]},
        "B": {"name": "B", "requires": ["A"]},
    }

    with pytest.raises(ValueError, match="Circular plugin dependency"):
        pm._topological_sort(["A", "B"])


def test_create_task_closes_coroutine_when_supervisor_creation_fails():
    bot = FakeBot()
    bot.tasks = types.SimpleNamespace(
        create=MagicMock(side_effect=RuntimeError("create failed")),
    )
    pm = PluginManager(bot)

    async def worker():
        return None

    coroutine = worker()
    with pytest.raises(RuntimeError, match="create failed"):
        pm.create_task("demo", coroutine, name="demo-task")

    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED


@pytest.mark.asyncio
async def test_event_task_on_ready_and_detailed_info(monkeypatch):
    class EventBot(FakeBot):
        def __init__(self):
            super().__init__()
            self.tasks = types.SimpleNamespace(
                create=lambda plugin, coro, name=None: (coro.close(), (plugin, name))[1],
                cancel_plugin=AsyncMock(return_value=2),
            )

        def add_event_handler(self, event, handler):
            self.calls.append(("add", event, handler))

        def del_event_handler(self, event, handler):
            self.calls.append(("del", event, handler))

    bot = EventBot()
    pm = PluginManager(bot)
    handler = lambda *_args: None
    pm.register_event("demo", "message", handler)
    assert bot.calls == [("add", "message", handler)]
    assert pm._event_handlers == {"demo": [("message", handler)]}

    async def never_run():
        await plugin_manager.asyncio.sleep(10)

    coroutine = never_run()
    assert pm.create_task("demo", coroutine, name="demo-task") == ("demo", "demo-task")
    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
    assert await pm._cancel_plugin_tasks("demo") == 2

    ready = []
    ready_mod = types.SimpleNamespace(on_ready=lambda bot_arg: ready.append(bot_arg))
    bad_mod = types.SimpleNamespace(on_ready=lambda bot_arg: (_ for _ in ()).throw(RuntimeError("boom")))
    pm.plugins = {"ready": ready_mod, "bad": bad_mod}
    await pm.call_on_ready()
    assert ready == [bot]

    pm.meta = {"help": {"name": "help"}}
    pm.plugin_sources = {"help": {"package": "core_plugins", "core": True}}
    assert await pm.get_plugin_info("help") == {"name": "help", "source": "core"}

    imported = make_fake_plugin(meta={"name": "xkcd", "description": "comic"})
    monkeypatch.setattr(pm, "_import", AsyncMock(return_value=imported))
    pm.plugin_sources["xkcd"] = {"package": "plugins", "core": False}
    assert await pm.get_plugin_info("xkcd") == {
        "name": "xkcd",
        "description": "comic",
        "source": "plugins",
    }

    monkeypatch.setattr(pm, "discover", lambda: ["help", "xkcd", "weather"])
    pm.plugins = {"help": ready_mod}
    pm.plugin_sources.update({
        "weather": {"package": "plugins", "core": False},
    })
    detailed = await pm.list_detailed()
    assert detailed["core"]["loaded"] == ["help"]
    assert sorted(detailed["plugins"]["available"]) == ["weather", "xkcd"]


@pytest.mark.asyncio
async def test_plugin_one_shot_task_waits_for_runtime_ready():
    bot = FakeBot()
    bot.runtime_ready = asyncio.Event()
    pm = PluginManager(bot, package="fakepkg", core_package=None)
    started = []

    async def worker():
        started.append("worker")
        return "done"

    task = pm.create_task("demo", worker(), name="demo-worker")
    await asyncio.sleep(0)

    assert started == []
    assert task.done() is False

    bot.runtime_ready.set()

    assert await task == "done"
    assert started == ["worker"]


@pytest.mark.asyncio
async def test_plugin_resilient_task_waits_for_runtime_ready():
    bot = FakeBot()
    bot.runtime_ready = asyncio.Event()
    pm = PluginManager(bot, package="fakepkg", core_package=None)
    started = []

    async def worker():
        started.append("worker")
        return "done"

    task = pm.create_resilient_task(
        "demo",
        worker,
        name="demo-service",
        service=False,
    )
    await asyncio.sleep(0)

    assert started == []
    assert task.done() is False

    bot.runtime_ready.set()

    assert await task == "done"
    assert started == ["worker"]


@pytest.mark.asyncio
async def test_resilient_ready_gate_sets_initial_service_heartbeat():
    bot = FakeBot()
    bot.runtime_ready = asyncio.Event()
    heartbeats = []
    bot.tasks = types.SimpleNamespace(
        heartbeat=lambda plugin, name: heartbeats.append((plugin, name))
    )

    async def worker():
        return "done"

    task = asyncio.create_task(
        plugin_manager._run_plugin_factory_when_ready(
            bot,
            worker,
            plugin="demo",
            name="demo-service",
        )
    )
    await asyncio.sleep(0)
    assert heartbeats == []

    bot.runtime_ready.set()

    assert await task == "done"
    assert heartbeats == [("demo", "demo-service")]


@pytest.mark.asyncio
async def test_cancelled_gated_plugin_task_closes_unstarted_coroutine():
    bot = FakeBot()
    bot.runtime_ready = asyncio.Event()
    pm = PluginManager(bot, package="fakepkg", core_package=None)

    async def worker():
        return "unused"

    coro = worker()
    task = pm.create_task("demo", coro, name="demo-worker")
    await asyncio.sleep(0)
    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)

    assert isinstance(result[0], asyncio.CancelledError)
    assert coro.cr_frame is None


@pytest.mark.asyncio
async def test_call_on_ready_uses_dependency_order_and_marks_runtime_ready():
    pm = PluginManager(FakeBot(), package="fakepkg", core_package=None)
    calls = []

    async def base_ready(_bot):
        calls.append("base")

    async def leaf_ready(_bot):
        calls.append("leaf")

    pm.plugins = {
        "leaf": types.SimpleNamespace(on_ready=leaf_ready),
        "base": types.SimpleNamespace(on_ready=base_ready),
    }
    pm.meta = {
        "leaf": {"name": "leaf", "requires": ["base"]},
        "base": {"name": "base", "requires": []},
    }

    await pm.call_on_ready()

    assert calls == ["base", "leaf"]
    assert pm._ready is True


@pytest.mark.asyncio
async def test_cleanup_room_state_calls_plugin_lifecycle_hooks(caplog):
    bot = FakeBot()
    pm = PluginManager(bot)

    async def async_cleanup(bot_arg, room_jid):
        assert bot_arg is bot
        assert room_jid == "room@example.org"
        return {"rooms": 1}

    def legacy_cleanup(bot_arg, room_jid):
        assert bot_arg is bot
        assert room_jid == "room@example.org"
        return {"legacy_rooms": 2}

    def invalid_cleanup(_bot, _room_jid):
        return "cleaned"

    def broken_cleanup(_bot, _room_jid):
        raise RuntimeError("boom")

    pm.plugins = {
        "modern": types.SimpleNamespace(cleanup_room_state=async_cleanup),
        "legacy": types.SimpleNamespace(on_room_delete=legacy_cleanup),
        "invalid": types.SimpleNamespace(cleanup_room_state=invalid_cleanup),
        "broken": types.SimpleNamespace(cleanup_room_state=broken_cleanup),
        "skipped": types.SimpleNamespace(cleanup_room_state="not-callable"),
    }

    with caplog.at_level("WARNING"):
        summary = await pm.cleanup_room_state("room@example.org")

    assert summary["modern"] == {"rooms": 1}
    assert summary["legacy"] == {"legacy_rooms": 2}
    assert summary["invalid"] == {"result": "cleaned"}
    assert summary["broken"] == {"error": "boom"}
    assert "skipped" not in summary
    assert "not callable" in caplog.text


def test_plugin_manager_list_and_available_use_loaded_and_discovered(monkeypatch):
    pm = PluginManager(FakeBot())
    pm.plugins = {"weather": object(), "help": object()}
    assert pm.list() == ["help", "weather"]

    monkeypatch.setattr(pm, "discover", lambda: ["help", "weather", "xkcd", "rss"])
    assert pm.available() == ["rss", "xkcd"]


@pytest.mark.asyncio
async def test_plugin_state_and_restart_tasks_hooks(monkeypatch):
    class Bot:
        def __init__(self):
            self.tasks = MagicMock()
            self.tasks.cancel_plugin = AsyncMock(return_value=3)

    module = types.ModuleType("plugins.stateful")

    async def get_runtime_state(bot, room_jid=None):
        return {"room": room_jid or "all", "items": 2}

    async def restart_tasks(bot):
        bot.restarted = True

    module.get_runtime_state = get_runtime_state
    module.restart_tasks = restart_tasks

    bot = Bot()
    manager = PluginManager(bot)
    manager.plugins["stateful"] = module

    assert await manager.plugin_state("stateful", room_jid="room@example.org") == {
        "loaded": True,
        "room": "room@example.org",
        "items": 2,
    }
    success, message, cancelled = await manager.restart_tasks("stateful")
    assert success is True
    assert "restarted" in message
    assert cancelled == 3
    assert bot.restarted is True


@pytest.mark.asyncio
async def test_restart_tasks_without_hook_does_not_cancel_existing_tasks():
    class Bot:
        def __init__(self):
            self.tasks = MagicMock()
            self.tasks.cancel_plugin = AsyncMock(return_value=2)

    manager = PluginManager(Bot())
    manager.plugins["passive"] = types.SimpleNamespace()

    success, message, cancelled = await manager.restart_tasks("passive")

    assert success is False
    assert "no task restart hook" in message
    assert cancelled == 0
    manager.bot.tasks.cancel_plugin.assert_not_called()

@pytest.mark.asyncio
async def test_plugin_metadata_and_doctor_helpers(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot=bot, package="fakepkg")
    good = make_fake_plugin(meta={
        "name": "good",
        "version": "1.0",
        "description": "Good plugin",
        "category": "utility",
    })
    missing = make_fake_plugin(meta={})
    pm.plugins = {"good": good, "missing": missing}
    pm.meta = {"good": good.PLUGIN_META, "missing": missing.PLUGIN_META}
    monkeypatch.setattr(pm, "discover", lambda: ["good", "missing"])

    assert await pm.metadata_issues("good") == []
    issues = await pm.metadata_issues("missing")
    assert {issue.message for issue in issues} >= {"missing non-empty 'name'", "missing non-empty 'description'", "missing non-empty 'category'"}
    all_issues = await pm.all_metadata_issues()
    assert len(all_issues) == len(issues)

    async def async_doctor(bot_arg, room_jid=None):
        assert bot_arg is bot
        assert room_jid == "room@conf"
        return ["✅ good: async ok"]

    good.doctor = async_doctor
    assert await pm.plugin_doctor("good", room_jid="room@conf") == ["✅ good: async ok"]

    good.doctor = lambda bot_arg, room_jid=None: "✅ good: string ok"
    assert await pm.plugin_doctor("good") == ["✅ good: string ok"]

    good.doctor = lambda bot_arg, room_jid=None: None
    assert await pm.plugin_doctor("good") == ["✅ good: ok"]

    good.doctor = "not-callable"
    assert await pm.plugin_doctor("good") == ["🔴 good: doctor hook is not callable"]

    def broken_doctor(_bot, room_jid=None):
        raise RuntimeError("boom")

    good.doctor = broken_doctor
    assert await pm.plugin_doctor("good") == ["🔴 good: doctor failed: boom"]

    assert await pm.plugin_doctor("not-loaded") == ["🔴 not-loaded: not loaded"]


@pytest.mark.asyncio
async def test_plugin_doctor_uses_runtime_state_when_no_hook(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot=bot, package="fakepkg")
    mod = make_fake_plugin(meta={"name": "stateful"})
    if hasattr(mod, "doctor"):
        delattr(mod, "doctor")
    pm.plugins = {"stateful": mod}

    async def plugin_state(name, room_jid=None):
        assert name == "stateful"
        assert room_jid == "room@conf"
        return {"beta": 2, "alpha": 1}

    monkeypatch.setattr(pm, "plugin_state", plugin_state)
    assert await pm.plugin_doctor("stateful", room_jid="room@conf") == [
        "ℹ️ stateful: alpha=1, beta=2"
    ]

    async def empty_plugin_state(name, room_jid=None):
        return {}

    monkeypatch.setattr(pm, "plugin_state", empty_plugin_state)
    assert await pm.plugin_doctor("stateful") == ["ℹ️ stateful: no diagnostic hook"]


@pytest.mark.asyncio
async def test_runtime_events_dispatch_and_cleanup():
    bot = FakeBot()
    pm = PluginManager(bot)
    calls = []

    def sync_handler(value):
        calls.append(("sync", value))

    async def async_handler(value):
        calls.append(("async", value))

    pm.register_runtime_event("demo", "public_groupchat_message", sync_handler)
    pm.register_runtime_event("demo", "public_groupchat_message", async_handler)
    pm.register_runtime_event("demo", "other", lambda value: calls.append(("other", value)))

    await pm.dispatch_runtime_event("public_groupchat_message", "msg-1")

    assert calls == [("sync", "msg-1"), ("async", "msg-1")]

    pm._runtime_event_handlers.pop("demo", None)
    await pm.dispatch_runtime_event("public_groupchat_message", "msg-2")
    assert calls == [("sync", "msg-1"), ("async", "msg-1")]


def test_create_resilient_task_delegates_to_supervisor():
    expected = object()
    supervisor = types.SimpleNamespace(
        create_resilient=MagicMock(return_value=expected)
    )
    bot = types.SimpleNamespace(tasks=supervisor)
    manager = PluginManager(bot)
    factory = MagicMock()

    result = manager.create_resilient_task("demo", factory)

    assert result is expected
    supervisor.create_resilient.assert_called_once()
    args, kwargs = supervisor.create_resilient.call_args
    assert args[0] == "demo"
    assert callable(args[1])
    assert kwargs == {
        "name": None,
        "max_restarts": None,
        "service": True,
    }
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_discovered_custom_room_state_plugins_have_cleanup_hooks():
    """Any plugin declaring custom room state must expose a cleanup lifecycle hook."""
    pm = PluginManager(bot=FakeBot())
    lifecycle_errors = []

    for name in pm.discover():
        for issue in await pm.metadata_issues(name):
            if "room_state='custom' requires cleanup_room_state" in issue.message:
                lifecycle_errors.append(issue.format())

    assert lifecycle_errors == []
