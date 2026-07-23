"""
📚 Help system for the bot.

The help output is generated from the live command registry. It supports plugin
help, focused command help, role filtering and aliases.

Usage
-----
  {prefix}help
  {prefix}help all
  {prefix}help commands
  {prefix}help plugins
  {prefix}help roles
  {prefix}help categories
  {prefix}help category <name>
  {prefix}help room settings
  {prefix}help <plugin>
  {prefix}help {prefix}<command>
  {prefix}help <command>
  {prefix}help inroom <on|off|status>

Examples
--------
  {prefix}help room settings
  {prefix}help ducks
  {prefix}help rooms enable
  {prefix}help rooms add
  {prefix}help {prefix}rooms add
  {prefix}help users role
"""

from __future__ import annotations

import inspect
import logging
import re

import slixmpp

from utils.command import (
    COMMANDS,
    CommandExample,
    CommandSubcommand,
    Role,
    check_permission,
    command,
    command_examples,
    command_subcommands,
    resolve_command,
)
from utils.command_metadata import help_example, help_subcommand
from utils.config import config

from core_plugins._core import handle_room_toggle_command, _get_enabled_rooms

log = logging.getLogger(__name__)

HELP_KEY = "HELP"

PLUGIN_META = {
    "name": "help",
    "version": "0.6.0",
    "description": "Dynamic help for plugins and commands.",
    "category": "core",
    "requires": ["_core", "rooms"],
}


# Plugin name -> room feature toggle metadata.  The feature name is the value
# accepted by `,rooms enable|disable`, while command is the optional
# plugin-local on/off/status shortcut.
ROOM_FEATURE_HELP = {
    "birthday_notify": {"feature": "birthday_notify", "command": "birthday_notify"},
    "dice": {"feature": "dice", "command": "dice"},
    "ducks": {"feature": "ducks", "command": "duck"},
    "help": {"feature": "help", "command": "help inroom"},
    "info": {"feature": "information", "command": "info", "aliases": ["info"]},
    "karma": {"feature": "karma", "command": "karma"},
    "pin": {"feature": "pin", "command": "pin"},
    "poll": {"feature": "poll", "command": "poll"},
    "presence": {"feature": "presence", "command": "presence"},
    "reminder": {"feature": "reminder", "command": "remind"},
    "sed": {"feature": "sed", "command": "sed"},
    "tell": {"feature": "tell", "command": "tell"},
    "tools": {"feature": "tools", "command": "tools"},
    "translate": {"feature": "translate", "command": "translate"},
    "urlcheck": {"feature": "urlcheck", "command": "urlcheck"},
    "vcard": {"feature": "vcard", "command": "vcard"},
    "weather": {"feature": "weather", "command": "weather"},
    "xkcd": {"feature": "xkcd", "command": "xkcd"},
    "xmpp": {"feature": "xmpp", "command": "xmpp"},
}

ROOM_FEATURE_HELP_QUERIES = {
    "room settings",
    "rooms settings",
    "room plugins",
    "rooms plugins",
    "room toggles",
    "rooms toggles",
    "room features",
    "rooms features",
    "features",
    "toggles",
}


# Store getter
async def get_help_store(bot):
    return bot.db.users.plugin("help")


# --------------------------------------------------
# DOCSTRING / METADATA HELPERS
# --------------------------------------------------

def _clean_doc(doc: str | None, prefix: str) -> str:
    """Return a readable docstring with prefix placeholders resolved."""
    if not doc:
        return ""
    return inspect.cleandoc(doc).replace("{prefix}", prefix).strip()


def _first_line(doc: str | None) -> str:
    """Return the first non-empty line from a docstring."""
    doc = _clean_doc(doc, "")
    if not doc:
        return ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _section_lines(doc: str, title: str) -> list[str]:
    """
    Extract simple NumPy-style docstring sections such as Usage or Examples.
    """
    if not doc:
        return []

    lines = doc.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == title.lower():
            start = i + 1
            # Skip underline made of dashes if present.
            if start < len(lines) and set(lines[start].strip()) <= {"-"}:
                start += 1
            break
    if start is None:
        return []

    out = []
    for line in lines[start:]:
        stripped = line.strip()
        if (
            stripped
            and re.fullmatch(r"[A-Za-z][A-Za-z /_-]+", stripped)
            and len(stripped.split()) <= 4
        ):
            break
        out.append(line.rstrip())

    return [line for line in out if line.strip()]


def _command_short(cmd_obj, prefix: str) -> str:
    """Return the command summary from decorator metadata only."""
    short = str(getattr(cmd_obj, "short", "") or "")
    return short.format(prefix=prefix) if short else "No description available."


def _command_usage(cmd_obj, prefix: str) -> list[str]:
    """Return usage lines from decorator metadata only."""
    usage = str(getattr(cmd_obj, "usage", "") or "")
    return [usage.format(prefix=prefix)] if usage else []


def _command_example_entries(cmd_obj, prefix: str) -> list[CommandExample]:
    """Return normalized, prefix-resolved command examples."""
    return [
        CommandExample(
            example.command.format(prefix=prefix),
            example.description.format(prefix=prefix),
        )
        for example in command_examples(cmd_obj)
    ]


def _command_examples(cmd_obj, prefix: str) -> list[str]:
    """Return example commands for compatibility with older callers."""
    return [example.command for example in _command_example_entries(cmd_obj, prefix)]


def _command_subcommand_entries(
    cmd_obj,
    prefix: str,
) -> list[CommandSubcommand]:
    """Return normalized, prefix-resolved structured subcommands."""
    result = []
    for subcommand in command_subcommands(cmd_obj):
        result.append(
            CommandSubcommand(
                name=subcommand.name,
                usage=subcommand.usage.format(prefix=prefix),
                short=subcommand.short.format(prefix=prefix),
                aliases=tuple(subcommand.aliases),
                examples=tuple(
                    CommandExample(
                        example.command.format(prefix=prefix),
                        example.description.format(prefix=prefix),
                    )
                    for example in subcommand.examples
                ),
                role=subcommand.role,
                context=subcommand.context,
            )
        )
    return result


def _role_label(role: Role) -> str:
    return str(role)


def _context_label(cmd_obj) -> str:
    context = getattr(cmd_obj, "context", "any") or "any"
    if context != "any":
        return context

    # envsbot blocks privileged commands in normal room messages.
    if getattr(cmd_obj, "role", Role.NONE) <= Role.MODERATOR:
        return "private chat / MUC PM"
    return "room, MUC PM or private chat"


def _plugin_meta(bot, name: str) -> dict:
    meta = getattr(bot.bot_plugins, "meta", {}).get(name, {}) or {}
    if meta:
        return meta

    module = bot.bot_plugins.plugins.get(name)
    if module is None:
        return {}
    return getattr(module, "PLUGIN_META", {}) or {}


def _plugin_description(bot, name: str, module) -> str:
    meta = _plugin_meta(bot, name)
    desc = meta.get("description") or _first_line(module.__doc__)
    return desc or "No description available."


def _room_feature_entry(plugin: str) -> dict | None:
    """Return room-toggle metadata for a plugin, if it has room settings."""
    return ROOM_FEATURE_HELP.get(str(plugin).strip().lower())


def _feature_alias_text(entry: dict) -> str:
    aliases = [str(alias) for alias in entry.get("aliases", []) if alias]
    if not aliases:
        return ""
    return f" (alias: {', '.join(aliases)})"


def _plugin_room_feature_lines(bot, plugin: str) -> list[str]:
    """Return room-setting help for one plugin."""
    entry = _room_feature_entry(plugin)
    if not entry:
        return []

    prefix = bot.prefix
    feature = str(entry["feature"])
    command_name = str(entry.get("command") or feature)
    alias_text = _feature_alias_text(entry)

    return [
        "",
        "Room setting:",
        f"  Feature name: {feature}{alias_text}",
        f"  Enable current room/MUC PM: {prefix}rooms enable {feature}",
        f"  Disable current room/MUC PM: {prefix}rooms disable {feature}",
        f"  Enable from private chat: "
        f"{prefix}rooms enable room@conference.example.org {feature}",
        f"  Show room settings: {prefix}rooms plugins [room@conference.example.org] all",
        f"  Shortcut in MUC PM: {prefix}{command_name} on|off|status",
    ]


def _available_room_features() -> list[str]:
    """Return configured room-feature names for the room-settings help page."""
    try:
        from utils.room_features import available_features

        return available_features()
    except Exception:
        log.debug("[HELP] Could not load room feature list", exc_info=True)
        return sorted({str(entry["feature"]) for entry in ROOM_FEATURE_HELP.values()})


# --------------------------------------------------
# COMMAND DISCOVERY / FORMATTERS
# --------------------------------------------------

def _commands_for_plugin(bot, plugin_name, user_role):
    """Collect visible canonical commands belonging to a plugin."""
    commands = []
    seen = set()

    tokens_list = COMMANDS.by_plugin.get(plugin_name, ())

    for tokens in tokens_list:
        cmd = COMMANDS.get(tokens)

        if not cmd or id(cmd) in seen:
            continue
        if not check_permission(user_role, cmd):
            continue

        seen.add(id(cmd))
        commands.append(cmd)

    commands.sort(key=lambda c: c.name)
    return commands


def _all_visible_commands(bot, role: Role):
    commands = []
    seen = set()
    for plugin_name in sorted(bot.bot_plugins.plugins):
        for cmd in _commands_for_plugin(bot, plugin_name, role):
            if id(cmd) not in seen:
                seen.add(id(cmd))
                commands.append((plugin_name, cmd))
    commands.sort(key=lambda item: (item[0], item[1].name))
    return commands


def _format_command_line(cmd_obj, prefix: str) -> str:
    aliases = sorted(set(a for a in (cmd_obj.aliases or []) if a != cmd_obj.name))
    alias_text = ""
    if aliases:
        alias_text = f" / aliases: {', '.join(prefix + a for a in aliases)}"
    return (
        f"• {prefix}{cmd_obj.name} [{_role_label(cmd_obj.role)}] — "
        f"{_command_short(cmd_obj, prefix)}{alias_text}"
    )


def _effective_subcommand_role(cmd_obj, subcommand: CommandSubcommand) -> Role:
    return subcommand.role if subcommand.role is not None else cmd_obj.role


def _effective_subcommand_context(cmd_obj, subcommand: CommandSubcommand) -> str:
    return subcommand.context or _context_label(cmd_obj)


def _visible_subcommands(cmd_obj, role: Role, prefix: str) -> list[CommandSubcommand]:
    """Return structured subcommands visible to one user role."""
    return [
        subcommand
        for subcommand in _command_subcommand_entries(cmd_obj, prefix)
        if role <= _effective_subcommand_role(cmd_obj, subcommand)
    ]


def _subcommand_aliases(cmd_obj, subcommand: CommandSubcommand, prefix: str) -> list[str]:
    """Return full command aliases for one structured subcommand."""
    root = str(cmd_obj.name)
    return [f"{prefix}{root} {alias}" for alias in subcommand.aliases]


def _access_summary(role: Role, context: str) -> str:
    """Return one compact role/context line for focused help output."""
    return f"Role: {_role_label(role)} · Context: {context}"


def _access_label(role: Role, context: str) -> str:
    """Return a short access label suitable for one command line."""
    return f"{_role_label(role)} · {context}"


def _command_access_profiles(
    cmd_obj,
    prefix: str,
    role: Role,
) -> list[tuple[Role, str]]:
    """Return visible role/context pairs represented by one command family."""
    subcommands = _visible_subcommands(cmd_obj, role, prefix)
    if subcommands:
        return [
            (
                _effective_subcommand_role(cmd_obj, subcommand),
                _effective_subcommand_context(cmd_obj, subcommand),
            )
            for subcommand in subcommands
        ]
    return [(cmd_obj.role, _context_label(cmd_obj))]


def _common_plugin_access(
    commands: list,
    prefix: str,
    role: Role,
) -> tuple[Role, str] | None:
    """Return a shared access profile when every visible command uses it."""
    profiles = {
        profile
        for cmd_obj in commands
        for profile in _command_access_profiles(cmd_obj, prefix, role)
    }
    return next(iter(profiles)) if len(profiles) == 1 else None


def _format_plugin_command_lines(
    cmd_obj,
    prefix: str,
    role: Role,
    *,
    common_access: tuple[Role, str] | None = None,
) -> list[str]:
    """Return compact, consistently spaced plugin-help command lines."""
    subcommands = _visible_subcommands(cmd_obj, role, prefix)
    if subcommands:
        lines = []
        for subcommand in subcommands:
            effective_role = _effective_subcommand_role(cmd_obj, subcommand)
            context = _effective_subcommand_context(cmd_obj, subcommand)
            access = (effective_role, context)
            access_suffix = (
                ""
                if common_access == access
                else f" [{_access_label(effective_role, context)}]"
            )
            lines.append(
                f"• {subcommand.usage} — {subcommand.short}{access_suffix}"
            )
            aliases = _subcommand_aliases(cmd_obj, subcommand, prefix)
            if aliases:
                lines.append("  Aliases: " + ", ".join(aliases))
        return lines

    aliases = sorted(set(a for a in (cmd_obj.aliases or []) if a != cmd_obj.name))
    access = (cmd_obj.role, _context_label(cmd_obj))
    access_suffix = (
        ""
        if common_access == access
        else f" [{_access_label(*access)}]"
    )
    lines = [
        f"• {_command_usage(cmd_obj, prefix)[0]} — "
        f"{_command_short(cmd_obj, prefix)}{access_suffix}",
    ]
    if aliases:
        lines.append("  Aliases: " + ", ".join(prefix + alias for alias in aliases))
    return lines


def _example_description_for_command(
    cmd_obj,
    example: CommandExample,
    prefix: str,
) -> str:
    """Return an explicit or subcommand-derived example description."""
    if example.description:
        return example.description

    example_tokens = _command_query_tokens(example.command, prefix)
    for subcommand in _command_subcommand_entries(cmd_obj, prefix):
        names = [subcommand.name, *subcommand.aliases]
        for name in names:
            if not name or name.startswith("<"):
                continue
            name_tokens = tuple(name.lower().split())
            primary_tokens = tuple(str(cmd_obj.name).lower().split())
            if example_tokens[: len(primary_tokens)] != primary_tokens:
                continue
            remaining = example_tokens[len(primary_tokens):]
            if remaining[: len(name_tokens)] == name_tokens:
                return subcommand.short
    return _command_short(cmd_obj, prefix)


def _format_example_lines(
    cmd_obj,
    examples: list[CommandExample] | tuple[CommandExample, ...],
    prefix: str,
) -> list[str]:
    """Render every example and its description on one compact line."""
    lines = []
    for example in examples:
        description = _example_description_for_command(cmd_obj, example, prefix)
        suffix = f" — {description}" if description else ""
        lines.append(f"• {example.command}{suffix}")
    return lines


def _examples_for_plugin_command(
    cmd_obj,
    prefix: str,
    role: Role,
) -> list[CommandExample]:
    """Prefer concise structured examples for aggregate commands."""
    subcommands = _visible_subcommands(cmd_obj, role, prefix)
    if subcommands:
        return [example for subcommand in subcommands for example in subcommand.examples]
    return _command_example_entries(cmd_obj, prefix)


def _format_command_detail(cmd_obj, prefix: str, role: Role | None = None) -> list[str]:
    lines = [
        f"📖 Command: {prefix}{cmd_obj.name}",
        _access_summary(cmd_obj.role, _context_label(cmd_obj)),
    ]

    aliases = sorted(set(a for a in (cmd_obj.aliases or []) if a != cmd_obj.name))
    if aliases:
        lines.append("Aliases: " + ", ".join(prefix + a for a in aliases))

    lines += ["", _command_short(cmd_obj, prefix), "", "Usage:"]
    for usage in _command_usage(cmd_obj, prefix):
        lines.append(f"  {usage}")

    visible_role = role if role is not None else Role.OWNER
    subcommands = _visible_subcommands(cmd_obj, visible_role, prefix)
    if subcommands:
        lines += ["", "Subcommands:"]
        lines.extend(_format_plugin_command_lines(cmd_obj, prefix, visible_role))

    examples = _examples_for_plugin_command(cmd_obj, prefix, visible_role)
    if examples:
        lines += ["", "Examples:"]
        lines.extend(_format_example_lines(cmd_obj, examples, prefix))

    return lines


def _command_context_plugin(bot, cmd_obj) -> str | None:
    """Return the plugin name matching a focused command, if any."""
    first_token = str(cmd_obj.name).split(maxsplit=1)[0].lower()
    if first_token in getattr(bot.bot_plugins, "plugins", {}):
        return first_token
    return None


def _format_plugin_context_lines(bot, plugin: str) -> list[str]:
    """Return compact plugin context for focused command help."""
    module = bot.bot_plugins.plugins[plugin]
    meta = _plugin_meta(bot, plugin)
    lines = ["", "Plugin context:", f"• Plugin: {plugin}"]

    if meta.get("version"):
        lines.append(f"• Version: {meta['version']}")
    if meta.get("category"):
        lines.append(f"• Category: {meta['category']}")

    lines.append(f"• Description: {_plugin_description(bot, plugin, module)}")

    feature_lines = _plugin_room_feature_lines(bot, plugin)
    if feature_lines:
        lines.extend(feature_lines)

    return lines


def _command_query_tokens(query: str, prefix: str) -> tuple[str, ...]:
    """Return normalized command tokens for a help query."""
    query = query.strip().lower()
    if prefix and query.startswith(prefix):
        query = query[len(prefix):].strip()
    return tuple(part for part in query.split() if part)


def _commands_matching_prefix(
    tokens: tuple[str, ...],
    role: Role,
) -> list[object]:
    """Return visible commands matching a registered name or alias prefix."""
    if not tokens:
        return []

    commands = []
    seen = set()
    for registered_tokens, cmd in COMMANDS.items():
        if len(registered_tokens) < len(tokens):
            continue
        if registered_tokens[:len(tokens)] != tokens:
            continue
        if id(cmd) in seen:
            continue
        if not check_permission(role, cmd):
            continue
        seen.add(id(cmd))
        commands.append(cmd)

    return commands


def _exact_primary_command(query: str, prefix: str):
    """Return a command only when the query matches its primary name exactly."""
    tokens = _command_query_tokens(query, prefix)
    if not tokens:
        return None

    cmd = COMMANDS.get(tokens)
    if not cmd:
        return None

    primary_tokens = tuple(str(getattr(cmd, "name", "")).lower().split())
    return cmd if primary_tokens == tokens else None


def _structured_subcommand_match(
    query: str,
    prefix: str,
    role: Role,
) -> tuple[object, CommandSubcommand] | None:
    """Resolve help for a structured subcommand without registering a handler."""
    tokens = _command_query_tokens(query, prefix)
    if len(tokens) < 2:
        return None

    candidates = []
    for registered_tokens, cmd in COMMANDS.items():
        if not command_subcommands(cmd):
            continue
        if len(tokens) <= len(registered_tokens):
            continue
        if tokens[: len(registered_tokens)] != registered_tokens:
            continue
        if not check_permission(role, cmd):
            continue
        remainder = tokens[len(registered_tokens):]
        for subcommand in _visible_subcommands(cmd, role, prefix):
            names = [subcommand.name, *subcommand.aliases]
            for name in names:
                if not name or name.startswith("<"):
                    continue
                name_tokens = tuple(name.lower().split())
                if remainder[: len(name_tokens)] == name_tokens:
                    candidates.append(
                        (len(registered_tokens) + len(name_tokens), cmd, subcommand)
                    )
    if not candidates:
        return None
    _score, cmd, subcommand = max(candidates, key=lambda item: item[0])
    return cmd, subcommand


def _format_structured_subcommand_detail(
    bot,
    cmd_obj,
    subcommand: CommandSubcommand,
) -> list[str]:
    """Render focused help for one metadata-only subcommand."""
    role = _effective_subcommand_role(cmd_obj, subcommand)
    context = _effective_subcommand_context(cmd_obj, subcommand)
    lines = [
        f"📖 Command: {bot.prefix}{cmd_obj.name} {subcommand.name}",
        _access_summary(role, context),
    ]
    aliases = _subcommand_aliases(cmd_obj, subcommand, bot.prefix)
    if aliases:
        lines.append("Aliases: " + ", ".join(aliases))
    lines += [
        "",
        subcommand.short,
        "",
        "Usage:",
        f"  {subcommand.usage}",
    ]
    if subcommand.examples:
        lines += ["", "Examples:"]
        lines.extend(_format_example_lines(cmd_obj, subcommand.examples, bot.prefix))
    plugin = _command_context_plugin(bot, cmd_obj)
    if plugin is not None:
        lines.extend(_format_plugin_context_lines(bot, plugin))
    return lines


def _format_command_group(bot, query: str, role: Role) -> list[str] | None:
    """Return an overview for command families such as `config` or `rooms`."""
    tokens = _command_query_tokens(query, bot.prefix)
    commands = _commands_matching_prefix(tokens, role)
    if len(commands) <= 1:
        return None

    group = " ".join(tokens)
    lines = [
        f"📖 Command group: {bot.prefix}{group}",
        "",
        "Subcommands:",
    ]
    for cmd in commands:
        usage = _command_usage(cmd, bot.prefix)[0]
        lines.append(f"• {usage} — {_command_short(cmd, bot.prefix)}")

    lines += [
        "",
        f"Use {bot.prefix}help {bot.prefix}<command> for detailed help.",
        f"Example: {bot.prefix}help {bot.prefix}{commands[0].name}",
    ]
    return lines


def _plugin_is_visible(bot, name: str, role: Role) -> bool:
    if name.startswith("_") and role > Role.ADMIN:
        return False
    if role <= Role.ADMIN:
        return True
    return bool(_commands_for_plugin(bot, name, role))


# --------------------------------------------------
# ROLE RESOLUTION
# --------------------------------------------------

def _joined_room_from_private_message(bot, msg) -> str | None:
    """Return the MUC room JID when a private message came from a MUC PM."""
    if msg.get("type") == "groupchat":
        return msg["from"].bare

    try:
        room = msg["from"].bare
    except Exception:
        return None

    joined_rooms = getattr(getattr(bot, "presence", None), "joined_rooms", {}) or {}
    if room in joined_rooms:
        return room

    try:
        from bot.room_state import JOINED_ROOMS
    except Exception:
        return None

    if room in JOINED_ROOMS:
        return room
    return None


async def _sender_role(bot, sender_jid, msg) -> tuple[Role, str | None]:
    """Resolve the role for help output in rooms, MUC PMs and direct DMs."""
    room = _joined_room_from_private_message(bot, msg)

    try:
        jid = str(slixmpp.JID(sender_jid).bare)
    except Exception:
        jid = str(sender_jid)

    try:
        if msg.get("type") == "groupchat":
            nick = msg.get("mucnick") or msg["from"].resource
            muc = bot.plugin.get("xep_0045", None)
            if muc and room:
                resolved = muc.get_jid_property(room, nick, "jid")
                if resolved:
                    jid = str(slixmpp.JID(resolved).bare)
    except Exception:
        log.debug("[HELP] Could not resolve MUC sender JID", exc_info=True)

    return await bot.get_user_role(jid, room), room


# --------------------------------------------------
# HELP COMMAND
# --------------------------------------------------

@command(
    "help",
    aliases=["h"],
    short="Show help for plugins and commands.",
    usage="{prefix}help [all|commands|plugins|roles|categories|category <name>|room settings|<plugin>|{prefix}<command>]",
    subcommands=[
        help_subcommand(
            "<overview>",
            "{prefix}help",
            "Show the main help overview and loaded plugins.",
            examples=[help_example("{prefix}help", "Open the main help page.")],
        ),
        help_subcommand(
            "commands",
            "{prefix}help commands",
            "List commands visible to your role, grouped by category.",
            examples=[help_example("{prefix}help commands", "Show the command overview for your role.")],
        ),
        help_subcommand(
            "plugins",
            "{prefix}help plugins",
            "List loaded plugins and their descriptions.",
            examples=[help_example("{prefix}help plugins", "Show all plugins visible to you.")],
        ),
        help_subcommand(
            "roles",
            "{prefix}help roles",
            "Show the bot role hierarchy and command access model.",
            examples=[help_example("{prefix}help roles", "Show role meanings and privilege order.")],
        ),
        help_subcommand(
            "categories",
            "{prefix}help categories",
            "List available help categories.",
            examples=[help_example("{prefix}help categories", "Show every command category.")],
        ),
        help_subcommand(
            "category",
            "{prefix}help category <name>",
            "List commands in one help category.",
            examples=[help_example("{prefix}help category admin", "Show commands in the admin category.")],
        ),
        help_subcommand(
            "room settings",
            "{prefix}help room settings",
            "Show how room-scoped plugins are enabled, disabled and inspected.",
            aliases=("rooms settings", "room plugins", "rooms plugins"),
            examples=[help_example("{prefix}help room settings", "Show room plugin toggle guidance.")],
        ),
        help_subcommand(
            "<plugin>",
            "{prefix}help <plugin>",
            "Show detailed help for one plugin.",
            examples=[help_example("{prefix}help rss", "Show the RSS plugin commands, subcommands and examples.")],
        ),
        help_subcommand(
            "<command>",
            "{prefix}help {prefix}<command>",
            "Show focused help for one command or structured subcommand.",
            examples=[help_example("{prefix}help {prefix}rss add", "Show focused help for the RSS add subcommand.")],
        ),
    ],
    examples=[
        "{prefix}help",
        "{prefix}help room settings",
        "{prefix}help rooms settings",
        "{prefix}help ducks",
        "{prefix}help rooms enable",
        "{prefix}help {prefix}users role",
        "{prefix}help category admin",
    ],
    category="core",
    context="any",
)
async def cmd_help(bot, sender_jid, nick, args, msg, is_room):
    """Show help for plugins and commands."""
    enabled_rooms = await _get_enabled_rooms(bot, HELP_KEY, "help")
    if is_room and msg["from"].bare not in enabled_rooms:
        bot.reply(msg, "ℹ️ Help is only available via private message in this room.")
        return

    role, _room = await _sender_role(bot, sender_jid, msg)
    query = " ".join(args).strip()

    if not query:
        bot.reply(msg, await _general(bot, role))
        return

    query_lc = query.lower()
    if query_lc == "all":
        bot.reply(msg, await _all(bot, role))
        return
    if query_lc == "commands":
        bot.reply(msg, await _commands(bot, role))
        return
    if query_lc == "plugins":
        bot.reply(msg, await _plugins(bot, role))
        return
    if query_lc == "roles":
        bot.reply(msg, _roles())
        return
    if query_lc == "categories":
        bot.reply(msg, await _categories(bot, role))
        return
    if query_lc in ROOM_FEATURE_HELP_QUERIES:
        bot.reply(msg, await _room_features(bot, role))
        return
    if query_lc.startswith("category "):
        category = query_lc.split(None, 1)[1].strip()
        bot.reply(msg, await _category(bot, role, category))
        return

    # Focused command help. Accept both ",help ,rooms add" and
    # ",help rooms add" because the latter is easier to type. Exact plugin
    # names keep plugin-help priority for backwards compatibility. Primary
    # command names such as `remind` still win over group overviews, so
    # `,help remind` shows the full reminder examples even though
    # `remind delete` is also available. Alias-only group roots such as
    # `config` keep the subcommand overview.
    if query.startswith(bot.prefix):
        command_query = query[len(bot.prefix):].strip()
        structured_match = _structured_subcommand_match(
            command_query, bot.prefix, role
        )
        if structured_match:
            cmd_obj, subcommand = structured_match
            bot.reply(
                msg,
                _format_structured_subcommand_detail(bot, cmd_obj, subcommand),
            )
            return

        exact_command = _exact_primary_command(command_query, bot.prefix)
        if exact_command:
            bot.reply(msg, await _command(bot, exact_command, role))
            return

        command_group = _format_command_group(bot, command_query, role)
        if command_group:
            bot.reply(msg, command_group)
            return

        cmd_obj, _ = resolve_command(command_query)
        if cmd_obj:
            bot.reply(msg, await _command(bot, cmd_obj, role))
        else:
            bot.reply(msg, ["🟡️ Unknown command."])
        return

    if query_lc in bot.bot_plugins.plugins:
        bot.reply(msg, await _plugin(bot, query, role))
        return

    structured_match = _structured_subcommand_match(query, bot.prefix, role)
    if structured_match:
        cmd_obj, subcommand = structured_match
        bot.reply(
            msg,
            _format_structured_subcommand_detail(bot, cmd_obj, subcommand),
        )
        return

    exact_command = _exact_primary_command(query, bot.prefix)
    if exact_command:
        bot.reply(msg, await _command(bot, exact_command, role))
        return

    command_group = _format_command_group(bot, query, role)
    if command_group:
        bot.reply(msg, command_group)
        return

    cmd_obj, _ = resolve_command(query)
    if cmd_obj:
        bot.reply(msg, await _command(bot, cmd_obj, role))
        return

    bot.reply(msg, await _plugin(bot, query, role))


# --------------------------------------------------
# GENERAL HELP
# --------------------------------------------------
async def _general(bot, role: Role) -> list[str]:
    lines = [
        f"📚 Envsbot {bot.version or 'unknown'} help",
        "",
        "Start here:",
        f"• {bot.prefix}help commands — list commands visible to you",
        f"• {bot.prefix}help plugins — list loaded plugins",
        f"• {bot.prefix}help <plugin> — plugin help with related commands",
        f"• {bot.prefix}help {bot.prefix}<command> — focused command help",
        f"• {bot.prefix}help room settings — how to enable/disable plugins per room",
        f"• {bot.prefix}help roles — role overview",
        f"• {bot.prefix}help categories — list command categories",
        f"• {bot.prefix}help category <name> — commands in one category",
        "",
        "Loaded plugins:",
    ]

    for name, module in sorted(bot.bot_plugins.plugins.items()):
        if not _plugin_is_visible(bot, name, role):
            continue
        desc = _plugin_description(bot, name, module)
        lines.append(f"• {name} — {desc}")

    lines += [
        "",
        f"Tip: use {bot.prefix}help commands for a category-based overview or {bot.prefix}help all for everything.",
        f"Room settings: use {bot.prefix}help room settings or {bot.prefix}help <plugin> to find enable/disable examples.",
    ]
    return lines


async def _plugins(bot, role: Role) -> list[str]:
    lines = ["📦 Loaded plugins", ""]
    by_category: dict[str, list[str]] = {}

    for name, module in sorted(bot.bot_plugins.plugins.items()):
        if not _plugin_is_visible(bot, name, role):
            continue
        meta = _plugin_meta(bot, name)
        category = meta.get("category", "other")
        desc = _plugin_description(bot, name, module)
        by_category.setdefault(category, []).append(f"• {name} — {desc}")

    for category in sorted(by_category):
        lines.append(f"{category}:")
        lines.extend(by_category[category])
        lines.append("")

    if lines[-1] == "":
        lines.pop()
    return lines


def _category_name(cmd_obj) -> str:
    category = getattr(cmd_obj, "category", "") or "other"
    return str(category).strip().lower() or "other"


def _category_title(category: str) -> str:
    return category.replace("_", " ").replace("-", " ").title()


def _commands_by_category(bot, role: Role) -> dict[str, list[tuple[str, object]]]:
    grouped: dict[str, list[tuple[str, object]]] = {}
    for plugin_name, cmd in _all_visible_commands(bot, role):
        grouped.setdefault(_category_name(cmd), []).append((plugin_name, cmd))
    for commands in grouped.values():
        commands.sort(key=lambda item: (item[1].name, item[0]))
    return grouped


async def _room_features(bot, _role: Role) -> list[str]:
    """Return an overview for room-scoped plugin toggles."""
    feature_names = _available_room_features()
    lines = [
        "🏠 Room plugin settings",
        "",
        "Use these commands to enable, disable or inspect room-scoped plugins:",
        f"• {bot.prefix}rooms plugins [<room_jid>] [all|page|last]",
        f"• {bot.prefix}rooms enable [<room_jid>] <plugin>",
        f"• {bot.prefix}rooms disable [<room_jid>] <plugin>",
        f"• {bot.prefix}rooms set_plugin_defaults [<room_jid>]",
        "",
        "Examples:",
        f"• {bot.prefix}rooms enable ducks",
        "  Enable the ducks feature in the current room or MUC PM.",
        f"• {bot.prefix}rooms disable ducks",
        "  Disable the ducks feature in the current room or MUC PM.",
        f"• {bot.prefix}rooms enable room@conference.example.org ducks",
        "  Enable ducks for an explicit room from a normal private chat.",
        f"• {bot.prefix}rooms plugins room@conference.example.org all",
        "  Show every room feature setting without pagination.",
        "",
        "Notes:",
        "• In a room or MUC PM, <room_jid> can be omitted.",
        "• In a normal private chat, pass <room_jid> explicitly.",
        "• The sender must be room owner/admin or have a bot moderator/admin role.",
        "• Some plugins also support a MUC-PM shortcut such as `duck on|off|status`.",
        "",
        "Available room feature names:",
    ]

    if not feature_names:
        lines.append("No room features are configured.")
    else:
        lines.append("• " + ", ".join(feature_names))
        lines.append("• information can also be addressed as info")

    return lines


async def _categories(bot, role: Role) -> list[str]:
    grouped = _commands_by_category(bot, role)
    lines = ["🗂️ Help categories", ""]
    if not grouped:
        return lines + ["No commands available for your role."]

    for category in sorted(grouped):
        lines.append(
            f"• {category} — {len(grouped[category])} command(s). "
            f"Use {bot.prefix}help category {category}"
        )
    return lines


async def _category(bot, role: Role, category: str) -> list[str]:
    category = category.strip().lower()
    grouped = _commands_by_category(bot, role)
    if category not in grouped:
        return [
            "🟡️ Unknown help category.",
            "",
            f"Use {bot.prefix}help categories to list available categories.",
        ]

    lines = [f"🗂️ {_category_title(category)} commands", ""]
    for _plugin_name, cmd in grouped[category]:
        lines.append(_format_command_line(cmd, bot.prefix))
    return lines


async def _commands(bot, role: Role) -> list[str]:
    lines = ["🧭 Commands by category", ""]
    grouped = _commands_by_category(bot, role)

    if not grouped:
        return lines + ["No commands available for your role."]

    for category in sorted(grouped):
        lines.append(f"{_category_title(category)}:")
        for _plugin_name, cmd in grouped[category]:
            lines.append(_format_command_line(cmd, bot.prefix))
        lines.append("")

    if lines[-1] == "":
        lines.pop()
    return lines


async def _all(bot, role: Role) -> list[str]:
    lines = await _general(bot, role)
    lines += ["", "────────────────", ""]
    lines.extend(await _commands(bot, role))
    return lines


# --------------------------------------------------
# COMMAND HELP
# --------------------------------------------------
async def _command(
    bot,
    cmd_obj,
    role: Role,
    *,
    include_plugin_context: bool = True,
) -> list[str]:
    if not check_permission(role, cmd_obj):
        return ["⛔ You do not have permission to use this command."]

    lines = _format_command_detail(cmd_obj, bot.prefix, role)
    if include_plugin_context:
        plugin = _command_context_plugin(bot, cmd_obj)
        if plugin is not None:
            lines.extend(_format_plugin_context_lines(bot, plugin))
    return lines


# --------------------------------------------------
# PLUGIN HELP
# --------------------------------------------------
async def _plugin(bot, query: str, role: Role) -> list[str]:
    pm = bot.bot_plugins
    plugin = query.lower()

    if plugin.startswith("_") and role > Role.ADMIN:
        return ["🟡️ Unknown plugin or command."]

    if plugin not in pm.plugins:
        return ["🟡️ Unknown plugin or command."]

    module = pm.plugins[plugin]
    meta = _plugin_meta(bot, plugin)
    lines = [f"📦 Plugin: {plugin}"]

    if meta.get("version"):
        lines.append(f"Version: {meta['version']}")
    if meta.get("category"):
        lines.append(f"Category: {meta['category']}")
    if meta.get("requires"):
        lines.append("Requires: " + ", ".join(meta["requires"]))

    lines += ["", _plugin_description(bot, plugin, module)]
    lines.extend(_plugin_room_feature_lines(bot, plugin))
    lines += ["", "Commands:"]

    commands = _commands_for_plugin(bot, plugin, role)
    if not commands:
        lines.append("No commands available for your role.")
    else:
        common_access = _common_plugin_access(commands, bot.prefix, role)
        if common_access is not None:
            lines.append("Access: " + _access_label(*common_access))
        for cmd in commands:
            lines.extend(
                _format_plugin_command_lines(
                    cmd,
                    bot.prefix,
                    role,
                    common_access=common_access,
                )
            )

        example_lines = []
        for cmd in commands:
            examples = _examples_for_plugin_command(cmd, bot.prefix, role)
            if not examples:
                continue
            example_lines.extend(_format_example_lines(cmd, examples, bot.prefix))
        if example_lines:
            lines += ["", "Examples:", *example_lines]

        lines += [
            "",
            f"Use {bot.prefix}help {bot.prefix}<command> for focused help.",
        ]

    return lines


def _roles() -> list[str]:
    return [
        "🛡️ Roles",
        "",
        "Lower numbers have more privileges.",
        "• owner — full control; configured owner JID",
        "• superadmin — high-level administration",
        "• admin — normal bot administration",
        "• moderator — room/plugin moderation commands",
        "• trusted — trusted user commands",
        "• user — normal user commands",
        "• new / none — limited or unknown users",
        "• banned — no command access",
        "",
        "Only the configured owner should be able to grant superadmin rights.",
        "Privileged commands are normally intended for private chats or MUC PMs.",
        "Room setting commands can also be used from a normal private chat when the target room JID is supplied.",
    ]


@command(
    "help inroom",
    role=Role.USER,
    aliases=["h inroom"],
    short="Enable, disable or show room help availability.",
    usage="{prefix}help inroom <on|off|status>",
    examples=[
        "{prefix}help inroom on",
        "{prefix}help inroom status",
    ],
    category="core",
    context="room or MUC PM",
)
async def help_inroom_command(bot, sender_jid, sender_nick,
                              args, msg, is_room):
    """
    Toggles usage of help inside a particular chat room.
    This is stored on a per-room basis and does not affect private messages.
    """

    handled = await handle_room_toggle_command(
        bot,
        msg,
        is_room,
        args,
        store_getter=get_help_store,
        key=HELP_KEY,
        label="In-Room Help",
        plugin="help",
        storage="dict",
        log_prefix="[HELP]",
    )
    if handled:
        return

    bot.reply(msg, f"Usage: {config.get('prefix', ',')}help inroom <on|off|status>")
