import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils import plugin_manager
from utils.plugin_manager import PluginManager


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
async def test_load_all_sorted(monkeypatch):
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
    monkeypatch.setattr(pm, "discover", lambda: ["A", "B"])
    await pm.load_all()
    assert set(pm.plugins.keys()) == {"A", "B"}


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


def test_dependency_validation_and_topological_sort(monkeypatch):
    bot = FakeBot()
    pm = PluginManager(bot, package="fakepkg")
    pm.meta = {
        "base": {"name": "base", "requires": []},
        "mid": {"name": "mid", "requires": ["base"]},
        "leaf": {"name": "leaf", "requires": ["mid"]},
        "missingdep": {"name": "missingdep", "requires": ["nope"]},
        "cycle": {"name": "cycle", "requires": ["cycle"]},
    }
    monkeypatch.setattr(pm, "discover", lambda: ["base", "mid", "leaf", "missingdep", "cycle"])

    assert pm._topological_sort(["leaf", "base", "mid"]) == ["base", "mid", "leaf"]
    assert pm._validate_dependencies("leaf") == (True, "")
    assert pm._validate_dependencies("missingdep") == (
        False,
        "Plugin missingdep requires nope, which is not available",
    )
    valid, msg = pm._validate_dependencies("cycle")
    assert valid is False
    assert "Circular dependency" in msg

    monkeypatch.setattr(plugin_manager.importlib, "import_module", lambda _name: (_ for _ in ()).throw(ImportError("boom")))
    valid, msg = pm._validate_dependencies("external")
    assert valid is False
    assert "Cannot load external" in msg


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

    assert pm.create_task("demo", never_run(), name="demo-task") == ("demo", "demo-task")
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
