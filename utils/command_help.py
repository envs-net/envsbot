"""Structured command help metadata for built-in plugins.

The command decorator can be used with explicit metadata. This module fills in
sensible defaults for existing commands so runtime help and generated docs stay
complete while plugins are gradually cleaned up.

Usage string notation used in this module:
- ``{prefix}``: runtime command prefix placeholder.
- ``[optional]``: optional argument or segment.
- ``<required>``: required argument value.
- ``a|b``: alternatives; choose one listed option.
"""

from __future__ import annotations

from typing import TypedDict


class CommandMetadata(TypedDict, total=False):
    short: str
    usage: str
    examples: list[str]
    context: str
    category: str


COMMAND_HELP: dict[str, CommandMetadata] = {
    "help": {
        "short": "Show help for plugins and commands.",
        "usage": "{prefix}help [all|commands|plugins|roles|categories|(category <name>)|<plugin>|<command>]",
        "examples": [
            "{prefix}help",
            "{prefix}help rooms",
            "{prefix}help rooms add",
            "{prefix}help category rooms",
        ],
        "category": "core",
    },
    "help inroom": {
        "short": "Enable, disable or show public room help availability.",
        "usage": "{prefix}help inroom <on|off|status>",
        "examples": ["{prefix}help inroom status"],
        "context": "room or MUC PM",
        "category": "core",
    },
    "bot restart": {
        "short": "Restart the bot process gracefully.",
        "usage": "{prefix}bot restart",
        "examples": ["{prefix}bot restart"],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "bot shutdown": {
        "short": "Stop the bot using the configured stop command.",
        "usage": "{prefix}bot shutdown",
        "examples": ["{prefix}bot shutdown"],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "bot status": {
        "short": "Show bot, runtime, XMPP, plugin and database status.",
        "usage": "{prefix}bot status [full]",
        "examples": [
            "{prefix}bot status",
            "{prefix}status",
            "{prefix}bot status full",
        ],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "bot version": {
        "short": "Show the running EnvsBot version and latest checked release.",
        "usage": "{prefix}bot version",
        "examples": ["{prefix}bot version", "{prefix}version"],
        "category": "core",
    },
    "bot checkupdate": {
        "short": "Check whether a newer EnvsBot release is available.",
        "usage": "{prefix}bot checkupdate",
        "examples": [
            "{prefix}bot checkupdate",
            "{prefix}checkupdate",
            "{prefix}updatecheck",
        ],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "tasks": {
        "short": "Show supervised background task status.",
        "usage": "{prefix}tasks [full] [plugin <name>] [running|failed|cancelled|done] [all|page|last]",
        "examples": [
            "{prefix}tasks",
            "{prefix}tasks full",
            "{prefix}tasks plugin rss",
            "{prefix}tasks failed",
        ],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "backup create": {
        "short": "Create a managed ZIP backup archive.",
        "usage": "{prefix}backup create [reason]",
        "examples": [
            "{prefix}backup create",
            "{prefix}backup create before config change",
            "{prefix}backup",
        ],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "backup list": {
        "short": "List managed backup archives.",
        "usage": "{prefix}backup list [all|page|last]",
        "examples": ["{prefix}backup list", "{prefix}backup list all"],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "backup show": {
        "short": "Show manifest details for one managed backup archive.",
        "usage": "{prefix}backup show <archive|last>",
        "examples": ["{prefix}backup show last"],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "restore": {
        "short": "Restore a managed backup after explicit confirmation.",
        "usage": "{prefix}restore <archive|last> confirm",
        "examples": ["{prefix}restore last confirm"],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "config show": {
        "short": "Show the effective config grouped like config_sample.py, with secrets redacted.",
        "usage": "{prefix}config show [all|page|last]",
        "examples": ["{prefix}config show", "{prefix}config show all"],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "config diff": {
        "short": "Show config values that differ from config_sample.py defaults.",
        "usage": "{prefix}config diff [all|page|last]",
        "examples": ["{prefix}config diff", "{prefix}config diff all"],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "config validate": {
        "short": "Validate the current config.py file.",
        "usage": "{prefix}config validate",
        "examples": ["{prefix}config validate"],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "config reload": {
        "short": "Reload config.py into the running bot where possible.",
        "usage": "{prefix}config reload",
        "examples": ["{prefix}config reload"],
        "context": "private chat / MUC PM",
        "category": "admin",
    },
    "plugin list": {
        "short": "List loaded and available core/optional plugins.",
        "usage": "{prefix}plugins [all|page|last]",
        "examples": [
            "{prefix}plugins",
            "{prefix}plugins all",
            "{prefix}plugins list",
        ],
        "context": "private chat / MUC PM",
        "category": "core",
    },
    "plugin info": {
        "short": "Show metadata and source information for one plugin.",
        "usage": "{prefix}plugin info <plugin>",
        "examples": ["{prefix}plugin info rooms"],
        "context": "private chat / MUC PM",
        "category": "core",
    },
    "plugin load": {
        "short": "Load one plugin or all plugins.",
        "usage": "{prefix}plugin load <plugin|all>",
        "examples": ["{prefix}plugin load weather"],
        "context": "private chat / MUC PM",
        "category": "core",
    },
    "plugin unload": {
        "short": "Unload one optional plugin; core plugins are protected.",
        "usage": "{prefix}plugin unload <plugin> [force]",
        "examples": ["{prefix}plugin unload weather"],
        "context": "private chat / MUC PM",
        "category": "core",
    },
    "plugin reload": {
        "short": "Reload one plugin or all plugins.",
        "usage": "{prefix}plugin reload <plugin|all> [auto]",
        "examples": ["{prefix}plugin reload help", "{prefix}plugin reload all auto"],
        "context": "private chat / MUC PM",
        "category": "core",
    },
    "rooms set_plugin_defaults": {
        "short": "Restore room plugin toggles to default values.",
        "usage": "{prefix}rooms set_plugin_defaults",
        "examples": ["{prefix}rooms spd"],
        "context": "MUC PM only",
        "category": "rooms",
    },
    "rooms plugins": {
        "short": "Show plugin toggle state for the current room.",
        "usage": "{prefix}rooms plugins [all|page|last]",
        "examples": ["{prefix}rooms plugins", "{prefix}rooms plugins all"],
        "context": "MUC PM only",
        "category": "rooms",
    },
    "rooms enable": {
        "short": "Enable a room-scoped plugin for the current room.",
        "usage": "{prefix}rooms enable <plugin>",
        "examples": ["{prefix}rooms enable weather"],
        "context": "MUC PM only",
        "category": "rooms",
    },
    "rooms disable": {
        "short": "Disable a room-scoped plugin for the current room.",
        "usage": "{prefix}rooms disable <plugin>",
        "examples": ["{prefix}rooms disable xkcd"],
        "context": "MUC PM only",
        "category": "rooms",
    },
    "rooms add": {
        "short": "Add or update a stored room configuration.",
        "usage": "{prefix}rooms add <room_jid> [nick] [autojoin]",
        "examples": ["{prefix}rooms add test@conference.example.org EnvsBot true"],
        "context": "private chat / MUC PM",
        "category": "rooms",
    },
    "rooms update": {
        "short": "Update one field of a stored room.",
        "usage": "{prefix}rooms update <room_jid> <nick|autojoin|status> <value>",
        "examples": ["{prefix}rooms update test@conference.example.org autojoin true"],
        "context": "private chat / MUC PM",
        "category": "rooms",
    },
    "rooms delete": {
        "short": "Remove a stored room and leave it if currently joined.",
        "usage": "{prefix}rooms delete <room_jid>",
        "examples": ["{prefix}rooms delete test@conference.example.org"],
        "context": "private chat / MUC PM",
        "category": "rooms",
    },
    "rooms list": {
        "short": "List stored rooms and currently joined rooms.",
        "usage": "{prefix}rooms list [all|page|last]",
        "examples": ["{prefix}rooms list", "{prefix}rooms list all"],
        "context": "private chat / MUC PM",
        "category": "rooms",
    },
    "rooms join": {
        "short": "Join a room immediately and store it if needed.",
        "usage": "{prefix}rooms join <room_jid> [nick]",
        "examples": ["{prefix}rooms join test@conference.example.org"],
        "context": "private chat / MUC PM",
        "category": "rooms",
    },
    "rooms invite": {
        "short": "List, accept or decline pending room invites.",
        "usage": "{prefix}rooms invite <list|accept|decline|cleanup> [id]",
        "examples": [
            "{prefix}rooms invite list",
            "{prefix}rooms invite accept 1",
            "{prefix}rooms invite decline 1",
        ],
        "context": "private chat / MUC PM / invite notify room",
        "category": "rooms",
    },
    "rooms leave": {
        "short": "Leave a room without deleting its stored configuration.",
        "usage": "{prefix}rooms leave <room_jid>",
        "examples": ["{prefix}rooms leave test@conference.example.org"],
        "context": "private chat / MUC PM",
        "category": "rooms",
    },
    "rooms sync": {
        "short": "Synchronize joined rooms with stored autojoin settings.",
        "usage": "{prefix}rooms sync",
        "examples": ["{prefix}rooms sync"],
        "context": "private chat / MUC PM",
        "category": "rooms",
    },
    "users info": {
        "short": "Show user info by JID or known nickname.",
        "usage": "{prefix}users info <jid|nick>",
        "examples": ["{prefix}users info alice@example.org"],
        "context": "private chat / MUC PM",
        "category": "users",
    },
    "users list": {
        "short": "List users currently known in one joined room.",
        "usage": "{prefix}users list [room_jid]",
        "examples": ["{prefix}users list test@conference.example.org"],
        "context": "private chat only",
        "category": "users",
    },
    "users role": {
        "short": "Change a user's global bot role with hierarchy checks.",
        "usage": "{prefix}users role <jid> <role>",
        "examples": ["{prefix}users role alice@example.org trusted"],
        "context": "private chat / MUC PM",
        "category": "users",
    },
    "users roles": {
        "short": "Show available roles and their ordering.",
        "usage": "{prefix}users roles",
        "examples": ["{prefix}users roles"],
        "context": "private chat / MUC PM",
        "category": "users",
    },
    "users admins": {
        "short": "List users with admin-level roles.",
        "usage": "{prefix}users admins [all|page|last]",
        "examples": ["{prefix}users admins"],
        "context": "private chat / MUC PM",
        "category": "users",
    },
    "users delete": {
        "short": "Delete one non-privileged user record and its runtime data.",
        "usage": "{prefix}users delete <jid>",
        "examples": ["{prefix}users delete alice@example.org"],
        "context": "private chat / MUC PM",
        "category": "users",
    },
    "presence": {
        "short": "Show or control per-room access to presence lookup.",
        "usage": "{prefix}presence [on|off|status]",
        "examples": ["{prefix}presence", "{prefix}presence status"],
        "category": "info",
    },
    "presence set": {
        "short": "Set the bot presence state and status text.",
        "usage": "{prefix}presence set <online|chat|away|xa|dnd> [message]",
        "examples": ["{prefix}presence set away maintenance"],
        "context": "private chat / MUC PM",
        "category": "info",
    },
    "dice": {
        "short": "Roll dice using common dice notation.",
        "usage": "{prefix}dice [NdM]",
        "examples": ["{prefix}dice", "{prefix}dice 2d6"],
        "category": "fun",
    },
    "duck": {
        "short": "Start or interact with the duck game.",
        "usage": "{prefix}duck",
        "examples": ["{prefix}duck"],
        "category": "fun",
    },
    "bef": {
        "short": "Befriend the current duck.",
        "usage": "{prefix}bef",
        "examples": ["{prefix}bef"],
        "category": "fun",
    },
    "trap": {
        "short": "Set a trap in the duck game.",
        "usage": "{prefix}trap",
        "examples": ["{prefix}trap"],
        "category": "fun",
    },
    "duckstats": {
        "short": "Show duck game stats.",
        "usage": "{prefix}duckstats [nick]",
        "examples": ["{prefix}duckstats"],
        "category": "fun",
    },
    "fediverse": {
        "short": "Look up Fediverse account or instance information.",
        "usage": "{prefix}fediverse <account|instance>",
        "examples": ["{prefix}fedi @user@example.org"],
        "category": "info",
    },
    "udict": {
        "short": "Search Urban Dictionary.",
        "usage": "{prefix}udict <term>",
        "examples": ["{prefix}ud xmpp"],
        "category": "info",
    },
    "wikipedia": {
        "short": "Search Wikipedia.",
        "usage": "{prefix}wikipedia <term>",
        "examples": ["{prefix}wiki XMPP"],
        "category": "info",
    },
    "acronyms": {
        "short": "Look up stored acronym definitions.",
        "usage": "{prefix}acronyms <term>",
        "examples": ["{prefix}acro XMPP"],
        "category": "info",
    },
    "acronyms add": {
        "short": "Add a definition to an acronym.",
        "usage": "{prefix}acronyms add <term> <definition>",
        "examples": ["{prefix}acro add XMPP Extensible Messaging and Presence Protocol"],
        "category": "info",
    },
    "acronyms remove": {
        "short": "Remove one acronym definition.",
        "usage": "{prefix}acronyms remove <term> <number>",
        "examples": ["{prefix}acro remove XMPP 1"],
        "category": "info",
    },
    "acronyms list": {
        "short": "List known acronyms.",
        "usage": "{prefix}acronyms list [all|page|last]",
        "examples": ["{prefix}acro list"],
        "category": "info",
    },
    "acronyms merge": {
        "short": "Merge one acronym into another.",
        "usage": "{prefix}acronyms merge <source> <target>",
        "examples": ["{prefix}acro merge xmpp XMPP"],
        "category": "info",
    },
    "acronyms delete": {
        "short": "Delete an acronym completely.",
        "usage": "{prefix}acronyms delete <term>",
        "examples": ["{prefix}acro delete XMPP"],
        "category": "info",
    },
    "info": {
        "short": "Enable, disable or show room access to information commands.",
        "usage": "{prefix}info <on|off|status>",
        "examples": ["{prefix}info status"],
        "context": "room or MUC PM",
        "category": "info",
    },
    "karma": {
        "short": "Show or update karma for a term.",
        "usage": "{prefix}karma [term|term++|term--]",
        "examples": ["{prefix}karma xmpp++", "{prefix}karma xmpp"],
        "category": "fun",
    },
    "pin": {
        "short": "Pin, list or delete room pins.",
        "usage": "{prefix}pin <add|list|delete|on|off|status> ...",
        "examples": ["{prefix}pin list"],
        "category": "rooms",
    },
    "poll": {
        "short": "Create and manage polls.",
        "usage": "{prefix}poll <new|vote|list|close|on|off|status> ...",
        "examples": ["{prefix}poll list"],
        "category": "rooms",
    },
    "remind": {
        "short": "Create a reminder.",
        "usage": "{prefix}remind <when> <text>",
        "examples": ["{prefix}remind 10m check logs"],
        "category": "utility",
    },
    "reminders": {
        "short": "List your reminders.",
        "usage": "{prefix}reminders [all|page|last]",
        "examples": ["{prefix}reminders"],
        "category": "utility",
    },
    "remind delete": {
        "short": "Delete one reminder.",
        "usage": "{prefix}remind delete <id>",
        "examples": ["{prefix}remind delete 12"],
        "category": "utility",
    },
    "rss": {
        "short": "Manage RSS feed subscriptions for a room.",
        "usage": "{prefix}rss <add|list|delete|on|off|status> ...",
        "examples": ["{prefix}rss list"],
        "category": "rooms",
    },
    "sed": {
        "short": "Apply sed-style corrections to recent messages.",
        "usage": "{prefix}s/old/new/",
        "examples": ["{prefix}s/teh/the/"],
        "category": "utility",
    },
    "tell": {
        "short": "Leave a message for another user.",
        "usage": "{prefix}tell <nick> <message>",
        "examples": ["{prefix}tell alice I fixed it"],
        "category": "utility",
    },
    "tools": {
        "short": "Enable, disable or show room access to utility commands.",
        "usage": "{prefix}tools <on|off|status>",
        "examples": ["{prefix}tools status"],
        "context": "room or MUC PM",
        "category": "utility",
    },
    "ping": {
        "short": "Check whether the bot is alive.",
        "usage": "{prefix}ping",
        "examples": ["{prefix}ping"],
        "category": "utility",
    },
    "echo": {
        "short": "Echo text back to you.",
        "usage": "{prefix}echo <text>",
        "examples": ["{prefix}echo hello"],
        "category": "utility",
    },
    "time": {
        "short": "Show the current time.",
        "usage": "{prefix}time [timezone]",
        "examples": ["{prefix}time Europe/Berlin"],
        "category": "utility",
    },
    "date": {
        "short": "Show the current date.",
        "usage": "{prefix}date [timezone]",
        "examples": ["{prefix}date"],
        "category": "utility",
    },
    "utc": {
        "short": "Show current UTC time.",
        "usage": "{prefix}utc",
        "examples": ["{prefix}utc"],
        "category": "utility",
    },
    "ts": {
        "short": "Convert or show Unix timestamps.",
        "usage": "{prefix}ts [timestamp]",
        "examples": ["{prefix}ts"],
        "category": "utility",
    },
    "seen": {
        "short": "Show when a user was last seen.",
        "usage": "{prefix}seen <nick|jid>",
        "examples": ["{prefix}seen alice"],
        "category": "utility",
    },
    "urlcheck": {
        "short": "Check URLs for status and metadata.",
        "usage": "{prefix}urlcheck <url>",
        "examples": ["{prefix}urlcheck https://envs.net"],
        "category": "utility",
    },
    "timezone set": {
        "short": "Set your timezone in the bot profile.",
        "usage": "{prefix}timezone set <IANA timezone>",
        "examples": ["{prefix}tz set Europe/Berlin"],
        "category": "profile",
    },
    "vcard": {
        "short": "Show your bot profile/vCard data.",
        "usage": "{prefix}vcard",
        "examples": ["{prefix}vcard"],
        "category": "profile",
    },
    "fullname": {
        "short": "Show or set your full name.",
        "usage": "{prefix}fullname [name]",
        "examples": ["{prefix}fullname Sven"],
        "category": "profile",
    },
    "nicknames": {
        "short": "Show or set profile nicknames.",
        "usage": "{prefix}nicknames [names]",
        "examples": ["{prefix}nicks Sven, creme"],
        "category": "profile",
    },
    "timezone": {
        "short": "Show your configured timezone.",
        "usage": "{prefix}timezone",
        "examples": ["{prefix}tz"],
        "category": "profile",
    },
    "organisations": {
        "short": "Show or set organisations in your profile.",
        "usage": "{prefix}organisations [text]",
        "examples": ["{prefix}orgs envs.net"],
        "category": "profile",
    },
    "notes": {
        "short": "Show or set profile notes.",
        "usage": "{prefix}notes [text]",
        "examples": ["{prefix}notes likes boring tech"],
        "category": "profile",
    },
    "emails": {
        "short": "Show or set profile emails.",
        "usage": "{prefix}emails [email]",
        "examples": ["{prefix}emails me@example.org"],
        "category": "profile",
    },
    "urls": {
        "short": "Show or set profile URLs.",
        "usage": "{prefix}urls [url]",
        "examples": ["{prefix}urls https://envs.net"],
        "category": "profile",
    },
    "birthday": {
        "short": "Show or set your birthday.",
        "usage": "{prefix}birthday [YYYY-MM-DD]",
        "examples": ["{prefix}birthday 1989-01-01"],
        "category": "profile",
    },
    "birthday_notify": {
        "short": "Enable, disable or show birthday notifications for a room.",
        "usage": "{prefix}birthday_notify <on|off|status>",
        "examples": ["{prefix}birthday_notify status"],
        "context": "room or MUC PM",
        "category": "rooms",
    },
    "weather": {
        "short": "Show weather for a location.",
        "usage": "{prefix}weather <location>",
        "examples": ["{prefix}weather Berlin"],
        "category": "utility",
    },
    "xkcd": {
        "short": "Show an XKCD comic.",
        "usage": "{prefix}xkcd [latest|random|number]",
        "examples": ["{prefix}xkcd random"],
        "category": "fun",
    },
    "xmpp": {
        "short": "Enable, disable or show room access to XMPP lookup commands.",
        "usage": "{prefix}xmpp <on|off|status>",
        "examples": ["{prefix}xmpp status"],
        "context": "room or MUC PM",
        "category": "xmpp",
    },
    "xmpp help": {
        "short": "Show help for XMPP lookup subcommands.",
        "usage": "{prefix}xmpp help",
        "examples": ["{prefix}x help"],
        "category": "xmpp",
    },
    "xmpp version": {
        "short": "Query XMPP software version via XEP-0092.",
        "usage": "{prefix}xmpp version <jid>",
        "examples": ["{prefix}x version envs.net"],
        "category": "xmpp",
    },
    "xmpp uptime": {
        "short": "Query XMPP entity uptime.",
        "usage": "{prefix}xmpp uptime <jid>",
        "examples": ["{prefix}x uptime envs.net"],
        "category": "xmpp",
    },
    "xmpp items": {
        "short": "List service discovery items.",
        "usage": "{prefix}xmpp items <jid>",
        "examples": ["{prefix}x items envs.net"],
        "category": "xmpp",
    },
    "xmpp contact": {
        "short": "Show contact addresses from service discovery.",
        "usage": "{prefix}xmpp contact <jid>",
        "examples": ["{prefix}x contact envs.net"],
        "category": "xmpp",
    },
    "xmpp info": {
        "short": "Show service discovery identity/features.",
        "usage": "{prefix}xmpp info <jid>",
        "examples": ["{prefix}x info conference.envs.net"],
        "category": "xmpp",
    },
    "xmpp ping": {
        "short": "Ping an XMPP entity.",
        "usage": "{prefix}xmpp ping <jid>",
        "examples": ["{prefix}x ping envs.net"],
        "category": "xmpp",
    },
    "xmpp srv": {
        "short": "Look up XMPP DNS SRV records.",
        "usage": "{prefix}xmpp srv <domain>",
        "examples": ["{prefix}x srv envs.net"],
        "category": "xmpp",
    },
    "xmpp compliance": {
        "short": "Check XMPP compliance features via disco.",
        "usage": "{prefix}xmpp compliance <jid>",
        "examples": ["{prefix}x compliance envs.net"],
        "category": "xmpp",
    },
}


def metadata_for(name: str) -> CommandMetadata:
    """Return structured metadata for a command name if known."""
    return CommandMetadata(**COMMAND_HELP.get(name.lower(), {}))
