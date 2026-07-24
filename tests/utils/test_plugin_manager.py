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

    def handler(*_args):
        return None

    async def on_load(bot_arg):
        bot_arg.bot_plugins.register_event("bad", "message", handler)
        bot_arg.bot_plugins.create_task("bad", _never(), name="bad-task")

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
    bot.tasks.cancel_plugin.assert_awaited_once_with("bad")
    assert tuple("dupe".split()) in registry.index
    assert registry.by_plugin == {"existing": {tuple("dupe".split())}}


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


def test_topological_sort_orders_dependencies_first():
    bot = FakeBot()
    pm = PluginManager(bot, package="fakepkg")
    pm.meta = {
        "base": {"name": "base", "requires": []},
        "mid": {"name": "mid", "requires": ["base"]},
        "leaf": {"name": "leaf", "requires": ["mid"]},
    }

    assert pm._topological_sort(["leaf", "base", "mid"]) == ["base", "mid", "leaf"]


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
