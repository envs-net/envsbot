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
  {prefix}help <command>
  {prefix}help {prefix}<command>
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
    Role,
    check_permission,
    command,
    resolve_command,
)
from utils.config import config

from core_plugins._core import handle_room_toggle_command, _get_enabled_rooms

log = logging.getLogger(__name__)

HELP_KEY = "HELP"

PLUGIN_META = {
    "name": "help",
    "version": "0.5.0",
    "description": "Dynamic help for plugins and commands.",
    "category": "core",
    "requires": ["_core"],
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
    if getattr(cmd_obj, "short", ""):
        return cmd_obj.short.format(prefix=prefix)
    return _first_line(cmd_obj.handler.__doc__) or "No description available."


def _command_usage(cmd_obj, prefix: str) -> list[str]:
    if getattr(cmd_obj, "usage", ""):
        return [cmd_obj.usage.format(prefix=prefix)]

    doc = _clean_doc(cmd_obj.handler.__doc__, prefix)
    usage = _section_lines(doc, "Usage")
    if usage:
        return usage

    return [f"{prefix}{cmd_obj.name}"]


def _command_examples(cmd_obj, prefix: str) -> list[str]:
    examples = [e.format(prefix=prefix) for e in getattr(cmd_obj, "examples", [])]
    if examples:
        return examples

    doc = _clean_doc(cmd_obj.handler.__doc__, prefix)
    return _section_lines(doc, "Example") + _section_lines(doc, "Examples")


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


def _format_command_detail(cmd_obj, prefix: str) -> list[str]:
    lines = [
        f"📖 Command: {prefix}{cmd_obj.name}",
        f"Role: {_role_label(cmd_obj.role)}",
        f"Context: {_context_label(cmd_obj)}",
    ]

    aliases = sorted(set(a for a in (cmd_obj.aliases or []) if a != cmd_obj.name))
    if aliases:
        lines.append("Aliases: " + ", ".join(prefix + a for a in aliases))

    lines += ["", _command_short(cmd_obj, prefix), "", "Usage:"]
    for usage in _command_usage(cmd_obj, prefix):
        lines.append(f"  {usage}")

    examples = _command_examples(cmd_obj, prefix)
    if examples:
        lines += ["", "Examples:"]
        for example in examples:
            lines.append(f"  {example}")

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
        from core_plugins.rooms import JOINED_ROOMS
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
    usage=(
        "{prefix}help [all|commands|plugins|roles|categories|"
        "category <name>|room settings|<plugin>|<command>]"
    ),
    examples=[
        "{prefix}help",
        "{prefix}help room settings",
        "{prefix}help ducks",
        "{prefix}help rooms enable",
        "{prefix}help {prefix}users role",
        "{prefix}help category rooms",
    ],
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
    # ",help rooms add" because the latter is easier to type.  Exact plugin
    # names keep plugin-help priority for backwards compatibility.
    if query.startswith(bot.prefix):
        command_query = query[len(bot.prefix):].strip()
        cmd_obj, _ = resolve_command(command_query)
        if cmd_obj:
            bot.reply(msg, await _command(bot, cmd_obj, role))
        else:
            bot.reply(msg, ["🟡️ Unknown command."])
        return

    if query_lc in bot.bot_plugins.plugins:
        bot.reply(msg, await _plugin(bot, query, role))
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
        f"• {bot.prefix}help <plugin> — plugin-specific help",
        f"• {bot.prefix}help <command> — focused command help",
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
        f"• {bot.prefix}rooms disable ducks",
        f"• {bot.prefix}rooms enable room@conference.example.org ducks",
        f"• {bot.prefix}rooms plugins room@conference.example.org all",
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
async def _command(bot, cmd_obj, role: Role) -> list[str]:
    if not check_permission(role, cmd_obj):
        return ["⛔ You do not have permission to use this command."]
    return _format_command_detail(cmd_obj, bot.prefix)


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
        for cmd in commands:
            lines.append(_format_command_line(cmd, bot.prefix))

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
    examples=["{prefix}help inroom on", "{prefix}help inroom status"],
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
        storage="dict",
        log_prefix="[HELP]",
    )
    if handled:
        return

    bot.reply(msg, f"Usage: {config.get('prefix', ',')}help inroom <on|off|status>")
