"""
command.py

Command registration and resolution system for the bot.

This module provides a decorator-based API for registering commands used by
plugins and core bot functionality. It also implements role-based access
control and a hierarchical command resolver that supports multi-word commands
and aliases.

Design goals
------------
- Simple decorator API for plugin authors
- Support hierarchical commands (e.g. "plugins reload")
- Support aliases for commands
- Resolve the longest matching command
- Provide role-based access control
- Keep implementation self-contained

Role system
-----------
Roles are implemented as an IntEnum with lower numbers representing higher
privileges:

    OWNER      = 1
    ADMIN      = 2
    MODERATOR  = 3
    USER       = 4
    NONE       = 5

Permission rule:
    user_role <= required_role
"""

from enum import IntEnum
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


class Role(IntEnum):
    """
    Role hierarchy used for command permission checks.
    Lower numbers represent higher privileges.
    """

    OWNER = 1
    ADMIN = 2
    MODERATOR = 3
    USER = 4
    NONE = 5

    def __str__(self):
        return self.name.lower()


@dataclass
class Command:
    """
    Representation of a registered command.

    Attributes
    ----------
    name:
        Canonical command name (e.g. "plugins reload")
    handler:
        Callable that implements the command
    role:
        Minimum required role to execute the command
    aliases:
        Alternative command names
    """

    name: str
    handler: Callable
    role: Role = Role.NONE
    aliases: List[str] = field(default_factory=list)


# token tuple -> Command
COMMAND_INDEX: Dict[Tuple[str, ...], Command] = {}


def _register(name: str, cmd: Command):
    """
    Register a command name or alias in the command index.

    Parameters
    ----------
    name:
        Command string (canonical name or alias).
    cmd:
        Command object.
    """

    tokens = tuple(name.lower().split())

    if not tokens:
        return

    COMMAND_INDEX[tokens] = cmd


def command(name: str,
            role: Role = Role.NONE,
            aliases: Optional[List[str]] = None):
    """
    Decorator used to register a command.

    Parameters
    ----------
    name:
        Canonical command name. May contain multiple words.

    role:
        Minimum role required to execute the command.

    aliases:
        Optional list of alternative command names.

    Examples
    --------

    Basic command:

        @command("help")

    Command with role:

        @command("kick", role=Role.MODERATOR)

    Command with aliases:

        @command(
            "plugins reload",
            role=Role.ADMIN,
            aliases=["reload", "pl reload"]
        )

    Notes
    -----
    Aliases are registered as full command entries rather than token
    rewrites. This avoids side effects where unrelated commands could
    modify each other's tokens.
    """

    if aliases is None:
        aliases = []

    def decorator(func: Callable):

        cmd = Command(
            name=name,
            handler=func,
            role=role,
            aliases=aliases
        )

        # register canonical command
        _register(name, cmd)

        # register aliases
        for alias in aliases:
            _register(alias, cmd)

        func._command = name
        func._command_names = [name] + aliases
        func._required_role = role
        func._aliases = aliases

        return func

    return decorator


def resolve_command(text: str):
    """
    Resolve the longest matching command from a text input.

    Parameters
    ----------
    text:
        Command text without the command prefix.

    Returns
    -------
    tuple(Command | None, List[str])
        Command object and argument list.

        If no command is found, the command will be None and the
        tokens will be returned as arguments.
    """

    tokens = text.split()

    if not tokens:
        return None, []

    tokens = [t.lower() for t in tokens]

    best_cmd = None
    best_len = 0

    for cmd_tokens, cmd in COMMAND_INDEX.items():

        n = len(cmd_tokens)

        if len(tokens) < n:
            continue

        if tuple(tokens[:n]) == cmd_tokens:
            if n > best_len:
                best_cmd = cmd
                best_len = n

    if best_cmd is None:
        return None, tokens

    args = tokens[best_len:]

    return best_cmd, args


def has_permission(user_role: Role, required_role: Role) -> bool:
    """
    Check whether a user role satisfies a command's role requirement.
    """

    return user_role <= required_role


def check_permission(user_role: Role, cmd: Command) -> bool:
    """
    Convenience wrapper for permission checking.
    """

    return has_permission(user_role, cmd.role)
