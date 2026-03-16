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

from __future__ import annotations
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


class CommandRegistry:
    """
    Central registry for all commands exposed by plugins.

    The registry maps a command trigger (represented as a tuple of
    lowercase tokens) to a `Command` instance. It acts as the single
    source of truth for command discovery and resolution within the bot.

    Example
    -------
    A command declared as:

        @command("weather now")
        async def weather_cmd(...):

    will be stored internally as:

        ("weather", "now") -> Command(...)

    Responsibilities
    ----------------
    The registry is responsible for:

    - Storing all commands registered by plugins.
    - Providing iteration over registered commands for command
      resolution.
    - Allowing commands to be removed when a plugin is unloaded
      or reloaded.
    - Normalizing command names into a consistent token format.

    Token Format
    ------------
    Commands are indexed by tuples of lowercase tokens:

        "ping"        -> ("ping",)
        "weather now" -> ("weather", "now")

    This structure allows efficient prefix matching when resolving
    user messages.

    Lifecycle
    ---------
    Commands are typically added through the `@command` decorator
    during plugin import. When plugins are unloaded or reloaded,
    the plugin manager removes the associated entries from this
    registry.

    Notes
    -----
    The registry intentionally provides only minimal operations
    (register, remove, iterate, lookup) so that higher-level logic
    such as command parsing, permission checks, or argument
    handling remains outside of this class.

    This class replaces the older global `COMMAND_INDEX` dictionary
    and provides a structured abstraction that can later support
    dependency injection or multiple registries if needed.
    """

    def __init__(self):
        self.index: Dict[Tuple[str, ...], Command] = {}
        self.by_handler: Dict[object, set[tuple[str, ...]]] = {}
        self.by_plugin: Dict[str, set[tuple[str, ...]]] = {}
        self.by_prefix: Dict[str, set[tuple[str, ...]]] = {}

    def register(self, name: str, cmd: Command, plugin: str | None = None):
        tokens = tuple(name.lower().split())
        if not tokens:
            return

        if tokens in self.index:
            existing = self.index[tokens]
            raise ValueError(
                f"Command already registered: '{' '.join(tokens)}' "
                f"(handler={existing.handler.__name__})"
            )

        self.index[tokens] = cmd

        prefix = tokens[0]
        self.by_prefix.setdefault(prefix, set()).add(tokens)

        if plugin:
            self.by_plugin.setdefault(plugin, set()).add(tokens)

        handler = getattr(cmd, "handler", None)
        if handler is not None:
            self.by_handler.setdefault(handler, set()).add(tokens)

    def remove(self, tokens: Tuple[str, ...]):
        cmd = self.index.pop(tokens, None)

        if not cmd:
            return

        prefix = tokens[0]
        if prefix in self.by_prefix:
            self.by_prefix[prefix].discard(tokens)
            if not self.by_prefix[prefix]:
                del self.by_prefix[prefix]

        handler = getattr(cmd, "handler", None)
        if handler in self.by_handler:
            self.by_handler[handler].discard(tokens)
            if not self.by_handler[handler]:
                del self.by_handler[handler]

    def remove_by_handler(self, handler):
        tokens = list(self.by_handler.get(handler, ()))
        for t in tokens:
            self.remove(t)

    def remove_by_plugin(self, plugin: str):
        tokens = list(self.by_plugin.get(plugin, ()))

        for t in tokens:
            self.remove(t)
        self.by_plugin.pop(plugin, None)

    def items(self):
        return self.index.items()

    def get(self, tokens):
        return self.index.get(tokens)


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
COMMANDS = CommandRegistry()


def _register(name: str, cmd: Command):
    """
    Attach command metadata to the handler so PluginManager
    can register it when the plugin loads.
    """

    tokens = tuple(name.lower().split())

    if not tokens:
        return

    if not hasattr(cmd.handler, "__commands__"):
        cmd.handler.__commands__ = []
    else:
        # plugin reload safety: avoid accumulating duplicates
        if not isinstance(cmd.handler.__commands__, list):
            cmd.handler.__commands__ = []

    entry = (name, cmd)
    # --- Prevent duplicate registrations ---
    if entry not in cmd.handler.__commands__:
        cmd.handler.__commands__.append((name, cmd))


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
    lower_tokens = [t.lower() for t in tokens]

    best_cmd = None
    best_len = 0

    candidates = COMMANDS.by_prefix.get(lower_tokens[0], ())

    for cmd_tokens in candidates:
        cmd = COMMANDS.get(cmd_tokens)

        n = len(cmd_tokens)

        if len(lower_tokens) < n:
            continue

        if tuple(lower_tokens[:n]) == cmd_tokens:
            if n > best_len:
                best_cmd = cmd
                best_len = n

    if best_cmd is None:
        return None, tokens

    args = tokens[best_len:]   # ← original case preserved
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
