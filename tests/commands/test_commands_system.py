"""
Command system validation tests.

These tests validate that plugin commands are correctly registered
and follow the expected structure.
"""

from utils.command import Role


def test_commands_registered(bot):
    """Ensure at least one command exists."""

    assert bot.commands, "No commands were registered."


def test_command_names_unique(bot):
    """Ensure command names are unique."""

    names = list(bot.commands.keys())

    assert len(names) == len(set(names)), "Duplicate command names detected."


def test_command_handlers_callable(bot):
    """Ensure command handlers are callable functions."""

    for name, handler in bot.commands.items():

        assert callable(handler), f"Command '{name}' handler is not callable"


def test_command_roles_valid(bot):
    """
    Ensure command roles are valid.

    If no role metadata exists, assume Role.NONE.
    """

    for name, handler in bot.commands.items():

        role = getattr(handler, "role", Role.NONE)

        assert isinstance(role, Role), f"Command '{name}' has invalid role"


def test_command_docstrings(bot):
    """Ensure command handlers have documentation."""

    for name, handler in bot.commands.items():

        doc = handler.__doc__

        assert doc is not None, f"Command '{name}' missing docstring"
        assert doc.strip(), f"Command '{name}' has empty docstring"
