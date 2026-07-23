import pytest
from utils.command import Role, role_from_int, is_banned, CommandRegistry


def fake_handler1():
    return 1


def fake_handler2():
    return 2


class FakeCommand:
    def __init__(self, handler): self.handler = handler


def test_role_enum_and_str():
    assert str(Role.USER) == "user"
    assert str(Role.BANNED) == "banned"


@pytest.mark.parametrize("val,expected", [
    (1, Role.OWNER), (80, Role.USER),
    (90, Role.NEW), (42, Role.USER), (999, Role.USER)
])
def test_role_from_int_various(val, expected):
    assert role_from_int(val) == expected


@pytest.mark.parametrize("role,result", [
    (Role.BANNED, True), (Role.NONE, False),
    (Role.ADMIN, False), (Role.USER, False)
])
def test_is_banned_for_various_roles(role, result):
    assert is_banned(role) == result


def test_registry_register_and_remove_and_plugin_indices():
    reg = CommandRegistry()
    c1 = FakeCommand(fake_handler1)
    c2 = FakeCommand(fake_handler2)
    reg.register("foo bar", c1, "pluginA")
    reg.register("hello", c2, None)
    # All registered?
    assert ("foo", "bar") in reg.index
    assert ("hello",) in reg.index
    # by_plugin
    assert "pluginA" in reg.by_plugin
    assert ("foo", "bar") in reg.by_plugin["pluginA"]
    # by_handler
    assert c1.handler in reg.by_handler
    assert ("foo", "bar") in reg.by_handler[c1.handler]
    # by_prefix
    assert "foo" in reg.by_prefix
    assert ("foo", "bar") in reg.by_prefix["foo"]
    # Remove "foo bar"
    reg.remove(("foo", "bar"))
    assert ("foo", "bar") not in reg.index
    for value_set in reg.by_plugin.values():
        assert ("foo", "bar") not in value_set


def test_registry_register_duplicate_raises():
    reg = CommandRegistry()
    c1 = FakeCommand(fake_handler1)
    reg.register("baz", c1)
    with pytest.raises(ValueError):
        reg.register("baz", c1)


def test_registry_remove_nonexistent_does_nothing():
    reg = CommandRegistry()
    c1 = FakeCommand(fake_handler1)
    reg.register("abc", c1)
    # Should do nothing
    reg.remove(("notareal",))
    assert ("abc",) in reg.index

from utils import command as command_mod


def test_registry_debug_dump_and_remove_by_handler_plugin():
    reg = CommandRegistry()
    cmd = command_mod.Command(
        name="demo",
        handler=fake_handler1,
        role=Role.ADMIN,
        aliases=["d"],
        short="Short text",
        usage=",demo",
        examples=[",demo now"],
        category="misc",
        context="private",
    )
    reg.register("demo", cmd, "pluginA")

    dump = reg.debug_dump()
    assert dump["demo"] == {
        "handler": "fake_handler1",
        "role": "admin",
        "aliases": ["d"],
        "short": "Short text",
        "usage": ",demo",
        "examples": [",demo now"],
        "category": "misc",
        "context": "private",
    }

    reg.remove_by_handler(fake_handler1)
    assert reg.index == {}
    assert reg.by_handler == {}
    assert reg.by_plugin == {}

    reg.register("demo", cmd, "pluginA")
    reg.remove_by_plugin("pluginA")
    assert reg.index == {}
    assert "pluginA" not in reg.by_plugin


def test_register_command_decorator_metadata_and_resolution(monkeypatch):
    registry = CommandRegistry()
    monkeypatch.setattr(command_mod, "COMMANDS", registry)

    @command_mod.command(
        "demo run",
        role=Role.USER,
        aliases=["dr"],
        short="Run demo",
        usage=",demo run",
        examples=[",demo run now"],
        category="tests",
        context="private",
    )
    def handler():
        return "ok"

    for name, cmd in handler.__commands__:
        registry.register(name, cmd, "tests")

    cmd, args = command_mod.resolve_command("demo run now")
    assert cmd.handler is handler
    assert args == ["now"]
    alias_cmd, alias_args = command_mod.resolve_command("dr later")
    assert alias_cmd.handler is handler
    assert alias_args == ["later"]
    assert handler._command_names == ["demo run", "dr"]
    assert command_mod.check_permission(Role.USER, cmd) is True
    assert command_mod.has_permission(Role.BANNED, cmd.role) is False


def test_register_command_decorator_does_not_use_legacy_metadata(monkeypatch):
    registry = CommandRegistry()
    monkeypatch.setattr(command_mod, "COMMANDS", registry)

    @command_mod.command("unknown command", role=Role.USER)
    def handler():
        return "ok"

    cmd = handler.__commands__[0][1]
    assert cmd.short == ""
    assert cmd.usage == ""
    assert cmd.examples == []
    assert cmd.category == ""
    assert cmd.context == "any"


def test_debug_leaks_outputs_registry_state(monkeypatch, capsys):
    registry = CommandRegistry()
    cmd = command_mod.Command(
        name="leak demo",
        handler=fake_handler1,
        role=Role.USER,
        aliases=["ld"],
    )
    registry.register("leak demo", cmd, "pluginA")
    monkeypatch.setattr(command_mod, "COMMANDS", registry)

    command_mod.debug_leaks()

    out = capsys.readouterr().out
    assert "COMMAND REGISTRY DEBUG" in out
    assert "index size: 1" in out
    assert "Handlers still referenced" in out
    assert "Plugins still registered" in out
    assert "pluginA" in out


def test_registry_remove_accepts_space_separated_name_and_tokens():
    reg = CommandRegistry()
    cmd = command_mod.Command(name="foo bar", handler=fake_handler1, role=Role.USER)

    reg.register("foo bar", cmd, "pluginA")
    reg.remove("foo bar")

    assert ("foo", "bar") not in reg.index
    assert reg.by_handler == {}
    assert reg.by_plugin == {}
    assert reg.by_prefix == {}

    reg.register("foo bar", cmd, "pluginA")
    reg.remove(("foo", "bar"))

    assert reg.index == {}
    assert reg.by_handler == {}
    assert reg.by_plugin == {}
    assert reg.by_prefix == {}


def test_structured_help_metadata_normalizes_examples_subcommands_and_roles():
    example = command_mod.normalize_command_example(
        {"command": "{prefix}demo add", "description": "Add a demo."}
    )
    assert example == command_mod.CommandExample(
        "{prefix}demo add",
        "Add a demo.",
    )
    assert command_mod.normalize_command_example(
        ("{prefix}demo list", "List demos.")
    ) == command_mod.CommandExample("{prefix}demo list", "List demos.")

    subcommand = command_mod.normalize_command_subcommand(
        {
            "name": "delete",
            "usage": "{prefix}demo delete <id>",
            "description": "Delete one demo.",
            "aliases": ["del", "remove", "rm"],
            "examples": [
                {
                    "command": "{prefix}demo delete 7",
                    "description": "Delete demo 7.",
                }
            ],
            "role": int(Role.MODERATOR),
            "context": "private chat / MUC PM",
        }
    )

    assert subcommand.name == "delete"
    assert subcommand.short == "Delete one demo."
    assert subcommand.aliases == ("del", "remove", "rm")
    assert subcommand.examples == (
        command_mod.CommandExample(
            "{prefix}demo delete 7",
            "Delete demo 7.",
        ),
    )
    assert subcommand.role is Role.MODERATOR
    assert subcommand.context == "private chat / MUC PM"

    string_metadata = command_mod.normalize_command_subcommand(
        {
            "name": "remove",
            "usage": "{prefix}demo remove <id>",
            "short": "Remove one demo.",
            "aliases": "rm",
            "role": "moderator",
        }
    )
    assert string_metadata.aliases == ("rm",)
    assert string_metadata.role is Role.MODERATOR


def test_command_decorator_exposes_structured_help_metadata(monkeypatch):
    registry = CommandRegistry()
    monkeypatch.setattr(command_mod, "COMMANDS", registry)
    subcommands = [
        {
            "name": "add",
            "usage": "{prefix}demo add <value>",
            "short": "Add one value.",
            "examples": [
                {
                    "command": "{prefix}demo add value",
                    "description": "Add the value named value.",
                }
            ],
        }
    ]

    @command_mod.command(
        "demo",
        role=Role.USER,
        short="Manage demos.",
        usage="{prefix}demo <add>",
        examples=["{prefix}demo add value"],
        subcommands=subcommands,
        category="tests",
        context="any",
    )
    def handler():
        return None

    cmd = handler.__commands__[0][1]
    assert handler._command_subcommands is subcommands
    assert command_mod.command_subcommands(cmd) == [
        command_mod.CommandSubcommand(
            name="add",
            usage="{prefix}demo add <value>",
            short="Add one value.",
            examples=(
                command_mod.CommandExample(
                    "{prefix}demo add value",
                    "Add the value named value.",
                ),
            ),
        )
    ]


def test_room_toggle_subcommands_support_custom_status_name():
    from utils.command_metadata import room_toggle_subcommands

    holder = type(
        "Holder",
        (),
        {
            "subcommands": room_toggle_subcommands(
                "idlerpg",
                "IdleRPG",
                status_name="enabled",
            )
        },
    )()
    subcommands = command_mod.command_subcommands(holder)

    assert [subcommand.name for subcommand in subcommands] == [
        "on",
        "off",
        "enabled",
    ]
    assert subcommands[-1].usage == "{prefix}idlerpg enabled"
    assert subcommands[-1].examples[0].description
