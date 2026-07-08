import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import core_plugins.help as help_plugin
import utils.command as command_utils
import utils.command_help as command_help

import utils.config
utils.config.config["prefix"] = ","


# ----- Fixtures and Mocks -----

class DummyBot:
    def __init__(self, *, version="99.99-x", prefix=",", role=command_utils.Role.USER,
                 plugins=None):
        self.replies = []
        self.version = version
        self.prefix = prefix
        self._role = role
        self.db = SimpleNamespace(users=SimpleNamespace(
            plugin=lambda name: AsyncMockStore()), roles={})
        self.bot_plugins = DummyPluginManager(self, plugins or {})
        self.make_message = lambda *a, **kw: None
        self.plugin = {}

    def reply(self, msg, text, **kwargs):
        self.replies.append(text)

    async def get_user_role(self, jid, room=None):  # mock permission system
        return self._role


class DummyPluginManager:
    def __init__(self, bot, plugins):
        self.plugins = plugins
        self._events = []

    def register_event(self, *a, **kw):
        self._events.append((a, kw))

    def list(self):
        return list(self.plugins.keys())


class DummyMsg:
    """Minimal Slixmpp message-like mock."""

    def __init__(self, body, is_room=True, room_jid="room@conf.test",
                 nick="Bob"):
        self.msg = {
            "body": body,
            "from": SimpleNamespace(bare=room_jid, resource=nick),
            "type": "groupchat" if is_room else "chat",
            "mucnick": nick
        }

    def __getitem__(self, key):
        return self.msg[key]

    def get(self, key, default=None):
        return self.msg.get(key, default)


class AsyncMockStore:
    async def get_global(self, key, default=None):
        if key == "HELP":  # enable in all rooms by default
            return {"room@conf.test": True}
        return default

    async def set_global(self, key, value):
        pass


@pytest.fixture
def basic_plugins_and_commands(monkeypatch):
    def foo_handler(*a, **k):
        """Foo command docstring\nSecond line."""
        return None

    def bar_handler(*a, **k):
        """Bar command admin only doc."""
        return None

    def help_handler(*a, **k):
        """Help docstring."""
        return None

    foo_cmd = command_utils.Command(name="foo", handler=foo_handler, role=command_utils.Role.USER,
                      aliases=["fooz"])
    bar_cmd = command_utils.Command(name="bar", handler=bar_handler, role=command_utils.Role.ADMIN)
    help_cmd = command_utils.Command(name="help", handler=help_handler, role=command_utils.Role.USER)

    plugins = {
        "foo": SimpleNamespace(__doc__="Foo plugin doc\nMore...",
                               __name__="foo"),
        "bar": SimpleNamespace(__doc__="Bar doc", __name__="bar"),
        "_hidden": SimpleNamespace(__doc__="Should hide for non-admin",
                                   __name__="_hidden"),
        "help": SimpleNamespace(__doc__="Help plugin doc", __name__="help"),
    }
    registry = command_utils.CommandRegistry()
    monkeypatch.setattr(help_plugin, "COMMANDS", registry)
    monkeypatch.setattr(command_utils, "COMMANDS", registry)
    registry.register("foo", foo_cmd, "foo")
    registry.register("bar", bar_cmd, "bar")
    registry.register("help", help_cmd, "help")
    registry.register("fooz", foo_cmd, "foo")  # Alias!
    return plugins, registry


# ----- Utility -----
def flatten_lines(reply):
    # Helper to return joined reply blocks if multi-line
    if isinstance(reply, (list, tuple)):
        return "\n".join(str(ln) for ln in reply)
    return str(reply)


# ----- Tests -----
@pytest.mark.asyncio
async def test_general_help_lists_plugins_and_commands(
        basic_plugins_and_commands, monkeypatch):
    plugins, reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins, role=command_utils.Role.ADMIN)
    msg = DummyMsg(body=",help")
    await help_plugin.cmd_help(bot, "user@host", "Bob", [], msg, True)
    assert bot.replies
    reply = flatten_lines(bot.replies[-1])
    # Plugins in expected list
    assert "foo" in reply
    assert "bar" in reply
    assert "help" in reply
    # Hidden and no-cmd plugin filtered (because user is admin-permitted)
    assert "_hidden" in reply  # visible to admin (command_utils.Role.ADMIN)
    assert "Foo plugin doc" in reply
    assert ",help ,<command>" in reply
    assert ",help <command> — focused command help" not in reply


@pytest.mark.asyncio
async def test_help_filters_hidden_and_no_cmd_plugins_for_user(
        basic_plugins_and_commands, monkeypatch):
    plugins, reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins, role=command_utils.Role.USER)  # Regular (not admin)
    msg = DummyMsg(body=",help")
    await help_plugin.cmd_help(bot, "user@host", "Alice", [], msg, True)
    reply = flatten_lines(bot.replies[-1])
    # Should NOT list _hidden because user is not admin
    assert "_hidden" not in reply
    # Should only show foo (has user command), not bar (admin-only, hidden for
    # normal users)
    assert "foo" in reply
    assert "bar" not in reply


@pytest.mark.asyncio
async def test_command_help_happy_path(basic_plugins_and_commands):
    plugins, reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins)
    msg = DummyMsg(body=",help ,foo")
    await help_plugin.cmd_help(bot, "user@host", "Test", [",foo"], msg, True)
    reply = flatten_lines(bot.replies[-1])
    assert "Command:" in reply
    assert "foo" in reply
    assert "Foo command docstring" in reply


@pytest.mark.asyncio
async def test_prefixed_command_help_includes_plugin_context(
        basic_plugins_and_commands):
    plugins, _reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins)
    msg = DummyMsg(body=",help ,foo")

    await help_plugin.cmd_help(bot, "user@host", "Test", [",foo"], msg, True)

    reply = flatten_lines(bot.replies[-1])
    assert "Command: ,foo" in reply
    assert "Plugin context:" in reply
    assert "Plugin: foo" in reply
    assert "Foo plugin doc" in reply


@pytest.mark.asyncio
async def test_command_help_permission_denied(basic_plugins_and_commands):
    plugins, reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins, role=command_utils.Role.USER)
    msg = DummyMsg(body=",help ,bar")
    # bar is admin-only, this user is 'USER', so should reject
    await help_plugin.cmd_help(bot, "user@host", "Test", [",bar"], msg, True)
    reply = flatten_lines(bot.replies[-1])
    assert "permission" in reply.lower()


@pytest.mark.asyncio
async def test_command_help_notfound(basic_plugins_and_commands):
    plugins, reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins)
    msg = DummyMsg(body=",help ,notfound")
    await help_plugin.cmd_help(bot, "user@host", "Test", [",notfound"],
                               msg, True)
    reply = flatten_lines(bot.replies[-1])
    assert "unknown command" in reply.lower()


@pytest.mark.asyncio
async def test_plugin_help_happy_path(basic_plugins_and_commands):
    plugins, reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins)
    msg = DummyMsg(body=",help foo")
    await help_plugin.cmd_help(bot, "user@host", "Test", ["foo"], msg, True)
    reply = flatten_lines(bot.replies[-1])
    assert "Plugin: foo" in reply
    # Plugin docstring
    assert "Foo plugin doc" in reply
    # Command list
    assert "foo" in reply
    assert ",foo [user]" in reply
    assert "Command details:" in reply
    assert "Command: ,foo" in reply
    assert "Usage:" in reply


@pytest.mark.asyncio
async def test_plugin_help_notfound(basic_plugins_and_commands):
    plugins, reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins)
    msg = DummyMsg(body=",help nosuch")
    await help_plugin.cmd_help(bot, "user@host", "Test", ["nosuch"], msg, True)
    reply = flatten_lines(bot.replies[-1])
    assert "unknown plugin" in reply.lower()


@pytest.mark.asyncio
async def test_plugin_help_no_permission_for_internal(
        basic_plugins_and_commands):
    plugins, reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins, role=command_utils.Role.USER)
    msg = DummyMsg(body=",help _hidden")
    await help_plugin.cmd_help(bot, "user@host", "Test", ["_hidden"],
                               msg, True)
    reply = flatten_lines(bot.replies[-1])
    # Hides internal plugins for non-admin
    assert "unknown plugin" in reply.lower()


@pytest.mark.asyncio
async def test_inroom_help_toggle_invokes_toggler(monkeypatch):
    """
    Verify help inroom calls handle_room_toggle_command and sets usage message.
    """
    called = {}

    async def fake_toggle(*a, **kw):
        called["ok"] = True
        return True

    monkeypatch.setattr(help_plugin, "handle_room_toggle_command", fake_toggle)
    bot = DummyBot()
    msg = DummyMsg(",help inroom on")
    await help_plugin.help_inroom_command(bot, "jid", "nick", ["on"],
                                          msg, True)
    assert called.get("ok")


@pytest.mark.asyncio
async def test_inroom_help_usage_when_not_handled(monkeypatch):
    # If handle_room_toggle_command returns False, it should reply with usage
    async def fake_toggle(*a, **kw): return False
    monkeypatch.setattr(help_plugin, "handle_room_toggle_command", fake_toggle)
    bot = DummyBot()
    msg = DummyMsg(",help inroom x")
    await help_plugin.help_inroom_command(bot, "jid", "nick", ["notareal"],
                                          msg, True)
    reply = flatten_lines(bot.replies[-1])
    assert "usage" in reply.lower()
    assert "help inroom" in reply.lower()


# ----- Coverage: In-room disabled, with room forced off -----
@pytest.mark.asyncio
async def test_help_room_disabled(monkeypatch, basic_plugins_and_commands):
    plugins, reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins)
    # Patch get_global to say disabled in room

    class DisabledStore:
        async def get_global(self, key, default=None):
            return {"someotherroom@conf.x": True}

        async def set_global(self, key, value):
            pass

    def fake_plugin(name):
        return DisabledStore()

    bot.db.users.plugin = fake_plugin
    msg = DummyMsg(",help", is_room=True, room_jid="room@conf.test")
    await help_plugin.cmd_help(bot, "user@x", "nick", [], msg, True)
    reply = flatten_lines(bot.replies[-1])
    assert "help is only available via private message" in reply.lower()


@pytest.mark.asyncio
async def test_muc_pm_help_uses_resolved_sender_jid_for_role(
        basic_plugins_and_commands):
    plugins, _reg = basic_plugins_and_commands

    class RoleByJidBot(DummyBot):
        def __init__(self):
            super().__init__(plugins=plugins)
            self.role_checks = []
            self.presence = SimpleNamespace(
                joined_rooms={"room@conf.test": "EnvsBot"}
            )

        async def get_user_role(self, jid, room=None):
            self.role_checks.append((jid, room))
            if jid == "admin@host":
                return command_utils.Role.ADMIN
            return command_utils.Role.NONE

    bot = RoleByJidBot()
    msg = DummyMsg(body=",help plugins", is_room=False,
                   room_jid="room@conf.test", nick="Alice")

    await help_plugin.cmd_help(
        bot, "admin@host/resource", "Alice", ["plugins"], msg, False
    )

    reply = flatten_lines(bot.replies[-1])
    assert "bar" in reply
    assert ("admin@host", "room@conf.test") in bot.role_checks


# ----- Plugin meta -----
def test_plugin_meta():
    meta = help_plugin.PLUGIN_META
    assert isinstance(meta, dict)
    for field in ("name", "description", "version"):
        assert field in meta


def test_docstring_and_formatting_helpers():
    def documented():
        """
        First line.

        Usage
        -----
          {prefix}demo <arg>

        Examples
        --------
          {prefix}demo value
        """

    cmd = command_utils.Command(
        name="demo",
        handler=documented,
        role=command_utils.Role.MODERATOR,
        aliases=["demo", "d"],
        category="room_tools",
    )
    assert help_plugin._clean_doc(None, ",") == ""
    assert help_plugin._first_line("\n\n  hello\n  world") == "hello"
    assert help_plugin._command_usage(cmd, ",") == ["  ,demo <arg>"]
    assert help_plugin._command_examples(cmd, ",") == ["  ,demo value"]
    assert help_plugin._context_label(cmd) == "private chat / MUC PM"
    assert help_plugin._category_name(cmd) == "room_tools"
    assert help_plugin._category_title("room_tools") == "Room Tools"
    line = help_plugin._format_command_line(cmd, ",")
    assert ",demo" in line
    assert ",d" in line
    details = "\n".join(help_plugin._format_command_detail(cmd, ","))
    assert "Context: private chat / MUC PM" in details
    assert "Examples:" in details

    structured = command_utils.Command(
        name="structured",
        handler=lambda: None,
        role=command_utils.Role.USER,
        short="Short {prefix}text",
        usage="{prefix}structured [x]",
        examples=["{prefix}structured 1"],
        context="private",
    )
    assert help_plugin._command_short(structured, ",") == "Short ,text"
    assert help_plugin._command_usage(structured, ",") == [",structured [x]"]
    assert help_plugin._command_examples(structured, ",") == [",structured 1"]
    assert help_plugin._context_label(structured) == "private"


@pytest.mark.asyncio
async def test_help_command_group_prefers_subcommands_over_base_alias(
    monkeypatch,
):
    registry = command_utils.CommandRegistry()
    monkeypatch.setattr(help_plugin, "COMMANDS", registry)
    monkeypatch.setattr(command_utils, "COMMANDS", registry)

    def handler(*_args, **_kwargs):
        return None

    config_show = command_utils.Command(
        name="config show",
        handler=handler,
        role=command_utils.Role.ADMIN,
        aliases=["config"],
        short="Show config.",
        usage="{prefix}config show [all|page|last]",
    )
    config_diff = command_utils.Command(
        name="config diff",
        handler=handler,
        role=command_utils.Role.ADMIN,
        short="Show changed config values.",
        usage="{prefix}config diff [all|page|last]",
    )
    config_validate = command_utils.Command(
        name="config validate",
        handler=handler,
        role=command_utils.Role.ADMIN,
        short="Validate config.py.",
        usage="{prefix}config validate",
    )
    config_reload = command_utils.Command(
        name="config reload",
        handler=handler,
        role=command_utils.Role.ADMIN,
        short="Reload config.py.",
        usage="{prefix}config reload",
    )

    registry.register("config show", config_show, "config_cmd")
    registry.register("config", config_show, "config_cmd")
    registry.register("config diff", config_diff, "config_cmd")
    registry.register("config validate", config_validate, "config_cmd")
    registry.register("config reload", config_reload, "config_cmd")

    bot = DummyBot(
        plugins={"config_cmd": SimpleNamespace(__doc__="Config commands")},
        role=command_utils.Role.ADMIN,
    )
    msg = DummyMsg(body=",help config")

    await help_plugin.cmd_help(
        bot, "admin@host", "Admin", ["config"], msg, True
    )

    reply = flatten_lines(bot.replies[-1])
    assert "Command group: ,config" in reply
    assert ",config show [all|page|last]" in reply
    assert ",config diff [all|page|last]" in reply
    assert ",config validate" in reply
    assert ",config reload" in reply
    assert "Command: ,config show" not in reply


@pytest.mark.asyncio
async def test_help_prefixed_command_group_query(monkeypatch):
    registry = command_utils.CommandRegistry()
    monkeypatch.setattr(help_plugin, "COMMANDS", registry)
    monkeypatch.setattr(command_utils, "COMMANDS", registry)

    def handler(*_args, **_kwargs):
        return None

    for name in ("backup create", "backup list", "backup show"):
        registry.register(
            name,
            command_utils.Command(
                name=name,
                handler=handler,
                role=command_utils.Role.ADMIN,
                short=f"{name} short.",
                usage="{prefix}" + name,
            ),
            "backups",
        )

    bot = DummyBot(
        plugins={"backups": SimpleNamespace(__doc__="Backup commands")},
        role=command_utils.Role.ADMIN,
    )
    msg = DummyMsg(body=",help ,backup")

    await help_plugin.cmd_help(
        bot, "admin@host", "Admin", [",backup"], msg, True
    )

    reply = flatten_lines(bot.replies[-1])
    assert "Command group: ,backup" in reply
    assert ",backup create" in reply
    assert ",backup list" in reply
    assert ",backup show" in reply


@pytest.mark.asyncio
async def test_help_categories_plugins_and_all_empty_or_grouped(monkeypatch):
    registry = command_utils.CommandRegistry()
    monkeypatch.setattr(help_plugin, "COMMANDS", registry)
    bot = DummyBot(plugins={})
    assert "No commands" in "\n".join(await help_plugin._commands(bot, command_utils.Role.USER))
    assert "No commands" in "\n".join(await help_plugin._categories(bot, command_utils.Role.USER))
    assert "Unknown help category" in "\n".join(await help_plugin._category(bot, command_utils.Role.USER, "missing"))

    def public_handler():
        """Public command."""

    public_cmd = command_utils.Command(
        name="foo_now",
        handler=public_handler,
        role=command_utils.Role.USER,
        category="misc-tools",
    )
    registry.register("foo_now", public_cmd, "foo")
    bot.bot_plugins.plugins = {
        "foo": SimpleNamespace(__doc__="Doc", PLUGIN_META={"category": "misc"})
    }

    categories = "\n".join(await help_plugin._categories(bot, command_utils.Role.USER))
    assert "misc-tools" in categories
    category = "\n".join(
        await help_plugin._category(bot, command_utils.Role.USER, "misc-tools")
    )
    assert ",foo_now" in category
    all_text = "\n".join(await help_plugin._all(bot, command_utils.Role.USER))
    assert "Loaded plugins" in all_text
    assert "Commands by category" in all_text
    plugins_text = "\n".join(await help_plugin._plugins(bot, command_utils.Role.USER))
    assert "misc:" in plugins_text


@pytest.mark.asyncio
async def test_sender_role_room_resolution_fallbacks(monkeypatch, basic_plugins_and_commands):
    plugins, _reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins, role=command_utils.Role.ADMIN)
    bot.presence = SimpleNamespace(joined_rooms={"pmroom@conf.test": "botnick"})

    direct_msg = DummyMsg(body=",help", is_room=False, room_jid="pmroom@conf.test", nick="Nick")
    role, room = await help_plugin._sender_role(bot, "user@example.org/resource", direct_msg)
    assert role == command_utils.Role.ADMIN
    assert room == "pmroom@conf.test"

    group_msg = DummyMsg(body=",help", is_room=True, room_jid="room@conf.test", nick="RoomNick")
    bot.plugin = {"xep_0045": SimpleNamespace(get_jid_property=lambda *a: "real@example.org/res")}
    seen = []

    async def fake_role(jid, room=None):
        seen.append((jid, room))
        return command_utils.Role.USER

    bot.get_user_role = fake_role
    role, room = await help_plugin._sender_role(bot, "fallback@example.org", group_msg)
    assert role == command_utils.Role.USER
    assert ("real@example.org", "room@conf.test") in seen

    def raising_get_jid_property(*_args):
        raise RuntimeError("boom")

    bot.plugin = {
        "xep_0045": SimpleNamespace(get_jid_property=raising_get_jid_property)
    }
    role, room = await help_plugin._sender_role(bot, "fallback@example.org/res", group_msg)
    assert role == command_utils.Role.USER


@pytest.mark.asyncio
async def test_cmd_help_dispatches_special_queries(basic_plugins_and_commands):
    plugins, _reg = basic_plugins_and_commands
    bot = DummyBot(plugins=plugins, role=command_utils.Role.ADMIN)

    for args, expected in [
        (["all"], "Commands by category"),
        (["commands"], "Commands by category"),
        (["plugins"], "Loaded plugins"),
        (["roles"], "Roles"),
        (["categories"], "Help categories"),
        (["room", "settings"], "Room plugin settings"),
        (["category", "other"], "Other commands"),
    ]:
        bot.replies.clear()
        await help_plugin.cmd_help(bot, "user@host", "Nick", args, DummyMsg(",help"), True)
        assert expected in flatten_lines(bot.replies[-1])


@pytest.mark.asyncio
async def test_plugin_help_includes_room_feature_controls(monkeypatch):
    registry = command_utils.CommandRegistry()
    monkeypatch.setattr(help_plugin, "COMMANDS", registry)

    def duck_handler(*_args, **_kwargs):
        """Duck command."""

    duck_cmd = command_utils.Command(
        name="duck",
        handler=duck_handler,
        role=command_utils.Role.USER,
        short="Start or interact with the duck game.",
        usage="{prefix}duck <on|off|status|befriend|trap>",
        examples=["{prefix}duck status"],
        category="fun",
    )
    registry.register("duck", duck_cmd, "ducks")

    plugins = {
        "ducks": SimpleNamespace(
            __doc__="Duck game plugin",
            __name__="ducks",
            PLUGIN_META={
                "name": "ducks",
                "description": "Duck game for MUCs",
                "category": "fun",
            },
        )
    }
    bot = DummyBot(plugins=plugins, role=command_utils.Role.USER)
    msg = DummyMsg(body=",help ducks")

    await help_plugin.cmd_help(bot, "user@host", "Nick", ["ducks"], msg, True)

    reply = flatten_lines(bot.replies[-1])
    assert "Plugin: ducks" in reply
    assert "Room setting:" in reply
    assert "Feature name: ducks" in reply
    assert ",rooms enable ducks" in reply
    assert ",rooms enable room@conference.example.org ducks" in reply
    assert ",duck on|off|status" in reply


@pytest.mark.asyncio
async def test_room_feature_help_page_lists_feature_names(monkeypatch):
    monkeypatch.setattr(
        help_plugin,
        "_available_room_features",
        lambda: ["ducks", "information"],
    )
    bot = DummyBot(plugins={})

    lines = "\n".join(await help_plugin._room_features(bot, command_utils.Role.USER))

    assert "Room plugin settings" in lines
    assert ",rooms enable ducks" in lines
    assert ",rooms enable room@conference.example.org ducks" in lines
    assert "ducks, information" in lines
    assert "information can also be addressed as info" in lines


def test_available_room_features_uses_configured_feature_list(monkeypatch):
    import utils.room_features as room_features

    monkeypatch.setattr(
        room_features,
        "available_features",
        lambda: ["ducks", "help", "xkcd"],
    )

    assert help_plugin._available_room_features() == ["ducks", "help", "xkcd"]


def test_available_room_features_falls_back_to_help_metadata(monkeypatch, caplog):
    import utils.room_features as room_features

    def broken_feature_list():
        raise RuntimeError("room feature config unavailable")

    monkeypatch.setattr(room_features, "available_features", broken_feature_list)
    caplog.set_level("DEBUG", logger=help_plugin.log.name)

    features = help_plugin._available_room_features()

    assert features == sorted(
        {str(entry["feature"]) for entry in help_plugin.ROOM_FEATURE_HELP.values()}
    )
    assert "ducks" in features
    assert "information" in features
    assert "info" not in features
    assert len(features) == len(set(features))

    records = [
        record for record in caplog.records
        if record.name == help_plugin.log.name
    ]
    assert records
    assert records[-1].message == "[HELP] Could not load room feature list"
    assert records[-1].exc_info


def test_room_feature_help_helpers():
    assert help_plugin._feature_alias_text({"aliases": ["info"]}) == " (alias: info)"
    assert help_plugin._feature_alias_text({}) == ""
    assert help_plugin._room_feature_entry("ducks")["feature"] == "ducks"
    assert help_plugin._room_feature_entry("missing") is None


@pytest.mark.asyncio
async def test_help_store_getter_uses_help_plugin_store():
    marker = object()
    bot = MagicMock()
    bot.db.users.plugin.return_value = marker
    assert await help_plugin.get_help_store(bot) is marker
    bot.db.users.plugin.assert_called_once_with("help")


def test_command_help_metadata_is_complete():
    root = Path(help_plugin.__file__).resolve().parents[1]
    command_names = []
    incomplete = []

    for rel in ("plugins", "core_plugins"):
        for path in sorted((root / rel).glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    func = decorator.func
                    is_command = (
                        isinstance(func, ast.Name) and func.id == "command"
                    ) or (
                        isinstance(func, ast.Attribute) and func.attr == "command"
                    )
                    if not is_command:
                        continue
                    if (
                        not decorator.args
                        or not isinstance(decorator.args[0], ast.Constant)
                    ):
                        continue

                    name = str(decorator.args[0].value)
                    command_names.append(name)
                    explicit_help = {kw.arg for kw in decorator.keywords} & {
                        "short",
                        "usage",
                    }
                    if name not in command_help.COMMAND_HELP and not explicit_help:
                        incomplete.append(
                            f"{path.relative_to(root)}:{node.name}:{name}"
                        )

    assert command_names
    assert not incomplete


def test_command_help_metadata_has_usage_and_examples():
    root = Path(help_plugin.__file__).resolve().parents[1]
    incomplete = []

    for rel in ("plugins", "core_plugins"):
        for path in sorted((root / rel).glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    func = decorator.func
                    is_command = (
                        isinstance(func, ast.Name) and func.id == "command"
                    ) or (
                        isinstance(func, ast.Attribute) and func.attr == "command"
                    )
                    if not is_command:
                        continue
                    if (
                        not decorator.args
                        or not isinstance(decorator.args[0], ast.Constant)
                    ):
                        continue

                    name = str(decorator.args[0].value).lower()
                    keywords = {kw.arg: kw.value for kw in decorator.keywords}
                    metadata = command_help.COMMAND_HELP.get(name, {})

                    has_usage = bool(metadata.get("usage")) or "usage" in keywords
                    has_examples = (
                        bool(metadata.get("examples"))
                        or "examples" in keywords
                    )
                    has_short = bool(metadata.get("short")) or "short" in keywords
                    if not (has_usage and has_examples and has_short):
                        incomplete.append(
                            f"{path.relative_to(root)}:{node.name}:{name}"
                        )

    assert not incomplete


def test_plugin_command_aliases_are_documented_for_shortcut():
    import core_plugins.plugins as plugin_commands

    assert "plugins" in plugin_commands.plugin_list._command_names
    assert command_help.COMMAND_HELP["plugin list"]["usage"] == (
        "{prefix}plugin list [all|page|last]"
    )
    assert (
        "{prefix}plugins"
        in command_help.COMMAND_HELP["plugin list"]["examples"]
    )

def test_weather_command_metadata_matches_city_zip_support():
    metadata = command_help.COMMAND_HELP["weather"]

    assert metadata["usage"] == "{prefix}weather [on|off|status|nick|city|zip]"
    assert "vCard location" in metadata["short"]
    assert "room nick" in metadata["short"]
    assert "city/ZIP code" in metadata["short"]

