"""
command.py

Provides a system for registering, managing, and resolving bot commands,
including role-based permissions and plugin integration.
"""

from __future__ import annotations
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Tuple


class Role(IntEnum):
    """
    Enum representing user roles for command permissions.
    Lower numbers indicate higher privileges. The range 1–100 allows
    for future expansion of roles and fine-grained access control.
    """

    OWNER = 1
    SUPERADMIN = 10
    ADMIN = 20
    MODERATOR = 40
    TRUSTED = 60
    USER = 80
    NEW = 90
    NONE = 95
    BANNED = 100

    def __str__(self):
        """Return the lowercase string name of the role."""
        return self.name.lower()


def role_from_int(value: int) -> Role:
    """
    Convert an integer value to a Role enum member.
    Returns USER if the value does not match any defined role.
    """
    try:
        return Role(value)
    except ValueError:
        return Role.USER


def is_banned(role: Role) -> bool:
    """
    Determine if the given role is considered banned.
    Returns True if the role is BANNED or higher.
    """
    return role >= Role.BANNED


@dataclass(frozen=True, slots=True)
class CommandExample:
    """One help example with an optional explanatory sentence."""

    command: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class CommandSubcommand:
    """Structured help metadata for a subcommand handled by a parent command."""

    name: str
    usage: str
    short: str
    aliases: Tuple[str, ...] = ()
    examples: Tuple[CommandExample, ...] = ()
    role: Role | None = None
    context: str = ""
    section: str = ""


def normalize_command_example(value: object) -> CommandExample:
    """Normalize string, pair or mapping example metadata."""
    if isinstance(value, CommandExample):
        return value
    if isinstance(value, str):
        return CommandExample(value)
    if isinstance(value, Mapping):
        command_text = value.get("command", value.get("example", ""))
        return CommandExample(
            str(command_text or ""),
            str(value.get("description", value.get("short", "")) or ""),
        )
    if isinstance(value, (tuple, list)) and value:
        command_text = value[0]
        description = value[1] if len(value) > 1 else ""
        return CommandExample(str(command_text), str(description or ""))
    return CommandExample(str(value))


def normalize_command_subcommand(value: object) -> CommandSubcommand:
    """Normalize mapping or dataclass subcommand metadata."""
    if isinstance(value, CommandSubcommand):
        return value
    if not isinstance(value, Mapping):
        raise TypeError(f"Unsupported subcommand metadata: {value!r}")
    examples = tuple(
        normalize_command_example(example)
        for example in (value.get("examples", ()) or ())
    )
    role = value.get("role")
    if role is not None and not isinstance(role, Role):
        if isinstance(role, str) and not role.strip().isdigit():
            role = Role[role.strip().upper()]
        else:
            role = Role(int(role))
    alias_values = value.get("aliases", ()) or ()
    if isinstance(alias_values, str):
        alias_values = (alias_values,)
    aliases = tuple(str(alias) for alias in alias_values)
    return CommandSubcommand(
        name=str(value.get("name", "") or ""),
        usage=str(value.get("usage", "") or ""),
        short=str(value.get("short", value.get("description", "")) or ""),
        aliases=aliases,
        examples=examples,
        role=role,
        context=str(value.get("context", "") or ""),
        section=str(value.get("section", "") or ""),
    )


def command_examples(cmd: object) -> List[CommandExample]:
    """Return normalized examples from a command-like object."""
    values = getattr(cmd, "examples", ()) or ()
    if isinstance(values, (str, Mapping, CommandExample)):
        values = (values,)
    return [normalize_command_example(value) for value in values]


def command_subcommands(cmd: object) -> List[CommandSubcommand]:
    """Return normalized structured subcommands from a command-like object."""
    values = getattr(cmd, "subcommands", ()) or ()
    if isinstance(values, (Mapping, CommandSubcommand)):
        values = (values,)
    return [normalize_command_subcommand(value) for value in values]


class CommandRegistry:
    """
    Central registry for all commands exposed by plugins.
    Supports registration, removal, and lookup of commands by name,
    handler, plugin, or prefix for efficient command management.
    """

    def __init__(self):
        """Initialize the command registry with empty indices."""
        self.index: Dict[Tuple[str, ...], Command] = {}
        self.by_handler: Dict[object, set[tuple[str, ...]]] = {}
        self.by_plugin: Dict[str, set[tuple[str, ...]]] = {}
        self.by_prefix: Dict[str, set[tuple[str, ...]]] = {}

    def register(self, name: str, cmd: "Command", plugin: str | None = None):
        """
        Register a command under the given name and optional plugin.
        Raises ValueError if the command name is already registered.
        """
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

    def _normalize_tokens(self, tokens: str | Iterable[str]) -> Tuple[str, ...]:
        """Normalize command names or token iterables to registry keys."""
        if isinstance(tokens, str):
            return tuple(tokens.lower().split())
        return tuple(str(token).lower() for token in tokens)

    def remove(self, tokens: str | Iterable[str]):
        tokens = self._normalize_tokens(tokens)
        if not tokens:
            return
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

        # This is the corrected part:
        for plugin, value_set in list(self.by_plugin.items()):
            value_set.discard(tokens)
            if not value_set:
                del self.by_plugin[plugin]

    def remove_by_handler(self, handler):
        """
        Remove all commands associated with a specific handler function.
        Useful for cleaning up commands when unloading plugins.
        """
        tokens = list(self.by_handler.get(handler, ()))
        for t in tokens:
            self.remove(t)

    def remove_by_plugin(self, plugin: str):
        """
        Remove all commands registered by a specific plugin.
        Cleans up plugin-related command entries.
        """
        tokens = list(self.by_plugin.get(plugin, ()))

        for t in tokens:
            self.remove(t)

        self.by_plugin.pop(plugin, None)

    def items(self):
        """
        Return all registered commands as (tokens, Command) pairs.
        Useful for iterating over the command registry.
        """
        return self.index.items()

    def get(self, tokens):
        """
        Retrieve a command by its token tuple.
        Returns the Command instance or None if not found.
        """
        return self.index.get(tokens)

    def debug_dump(self) -> Dict[str, dict]:
        """
        Return a structured snapshot of the command registry for debugging.
        Includes handler names, required roles, and aliases for each command.
        """
        data = {}

        for tokens, cmd in self.index.items():
            name = " ".join(tokens)

            entry = {
                "handler": getattr(cmd.handler, "__name__", str(cmd.handler)),
                "role": str(cmd.role),
                "aliases": list(cmd.aliases),
                "short": cmd.short,
                "usage": cmd.usage,
                "examples": [example.command for example in command_examples(cmd)],
                "category": cmd.category,
                "context": cmd.context,
            }
            subcommands = command_subcommands(cmd)
            if subcommands:
                entry["subcommands"] = [
                    {
                        "name": subcommand.name,
                        "usage": subcommand.usage,
                        "short": subcommand.short,
                        "aliases": list(subcommand.aliases),
                        "examples": [
                            {
                                "command": example.command,
                                "description": example.description,
                            }
                            for example in subcommand.examples
                        ],
                        "role": subcommand.role,
                        "context": subcommand.context,
                        "section": subcommand.section,
                    }
                    for subcommand in subcommands
                ]
            data[name] = entry

        return data


@dataclass
class Command:
    """
    Represents a registered command.

    The original command system only stored the callable, required role and
    aliases.  The additional fields are optional and backwards compatible: old
    plugins can keep using docstrings, while new or touched commands can expose
    structured help data directly via the @command decorator.
    """

    name: str
    handler: Callable
    role: Role = Role.NONE
    aliases: List[str] = field(default_factory=list)
    short: str = ""
    usage: str = ""
    examples: List[object] = field(default_factory=list)
    subcommands: List[object] = field(default_factory=list)
    category: str = ""
    context: str = "any"


COMMANDS = CommandRegistry()


def _register(name: str, cmd: Command):
    """
    Attach command metadata to the handler for plugin registration.
    Prevents duplicate registrations during plugin reloads by checking
    existing metadata on the handler.
    """
    tokens = tuple(name.lower().split())

    if not tokens:
        return

    if not hasattr(cmd.handler, "__commands__"):
        cmd.handler.__commands__ = []
    else:
        if not isinstance(cmd.handler.__commands__, list):
            cmd.handler.__commands__ = []

    entry = (name, cmd)

    # Prevent duplicate registrations during plugin reload
    if entry not in cmd.handler.__commands__:
        cmd.handler.__commands__.append((name, cmd))


def command(
    name: str,
    role: Role = Role.NONE,
    aliases: Optional[List[str]] = None,
    short: str = "",
    usage: str = "",
    examples: Optional[List[object]] = None,
    subcommands: Optional[List[object]] = None,
    category: str = "",
    context: str = "any",
):
    """
    Decorator to register a function as a command.

    Structured help metadata is the command registry source of truth.
    Repository commands are expected to provide ``short``, ``usage``,
    ``examples``, ``category`` and ``context`` directly in the decorator;
    CI/preflight checks fail when metadata is incomplete.
    """
    if aliases is None:
        aliases = []
    if examples is None:
        examples = []
    if subcommands is None:
        subcommands = []

    def decorator(func: Callable):
        """
        Decorator function that attaches command metadata to the handler.
        Registers the command and its aliases for later plugin integration.
        """
        cmd = Command(
            name=name,
            handler=func,
            role=role,
            aliases=aliases,
            short=short,
            usage=usage,
            examples=examples,
            subcommands=subcommands,
            category=category,
            context=context,
        )

        _register(name, cmd)

        for alias in aliases:
            _register(alias, cmd)

        func._command = name
        func._command_names = [name] + aliases
        func._required_role = role
        func._aliases = aliases
        func._command_short = short
        func._command_usage = usage
        func._command_examples = examples
        func._command_subcommands = subcommands
        func._command_category = category
        func._command_context = context

        return func

    return decorator


def resolve_command(text: str):
    """
    Resolve the longest matching command from a text input string.
    Returns a tuple of (Command, arguments) if found, or (None, tokens)
    if no command matches the input.
    """
    tokens = text.split()

    if not tokens:
        return None, []

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

    args = tokens[best_len:]

    return best_cmd, args


def is_command_group(text: str) -> bool:
    """Return whether *text* is a registered command-family prefix.

    Exact commands are intentionally excluded: callers should resolve those
    normally first.  This helper only recognizes prefixes that have at least
    one longer registered command, for example ``rooms`` when ``rooms list``
    and ``rooms add`` are registered.
    """
    tokens = tuple(part.lower() for part in str(text).split() if part)
    if not tokens:
        return False

    candidates = COMMANDS.by_prefix.get(tokens[0], ())
    return any(
        len(candidate) > len(tokens) and candidate[:len(tokens)] == tokens
        for candidate in candidates
    )


def has_permission(user_role: Role, required_role: Role) -> bool:
    """
    Check if a user with user_role is permitted to execute a command
    requiring required_role. Returns False if the user is banned.
    """
    if is_banned(user_role):
        return False

    return user_role <= required_role


def check_permission(user_role: Role, cmd: Command) -> bool:
    """
    Check if a user with user_role is allowed to execute the given command.
    Uses the command's required role for comparison.
    """
    return has_permission(user_role, cmd.role)


def debug_leaks():
    """
    Print debug information about the command registry to help detect
    memory leaks or improper cleanup of command references.
    """
    print("\n--- COMMAND REGISTRY DEBUG ---")

    print("index size:", len(COMMANDS.index))
    print("by_handler size:", len(COMMANDS.by_handler))
    print("by_plugin size:", len(COMMANDS.by_plugin))
    print("by_prefix size:", len(COMMANDS.by_prefix))

    if COMMANDS.by_handler:
        print("\nHandlers still referenced:")
        for handler, tokens in COMMANDS.by_handler.items():
            print(" ", handler, "->", tokens)

    if COMMANDS.by_plugin:
        print("\nPlugins still registered:")
        for plugin, tokens in COMMANDS.by_plugin.items():
            print(" ", plugin, "->", tokens)

    print("--- END DEBUG ---\n")
