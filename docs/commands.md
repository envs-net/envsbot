# envsbot command reference

This file is generated from command metadata. Do not edit it by hand.

```bash
python scripts/generate_commands_md.py
```

## Usage notes

Examples use the default command prefix `,`.
Runtime help is available through:

- `,help`
- `,help commands`
- `,help categories`
- `,help category <name>`
- `,help <plugin>`
- `,help <command>`

For paginated commands, `all` disables paging and `last` jumps to the final page.

## Role legend

Lower role values have more privileges. A command is visible when your role is strong enough.

| Role | Meaning |
| --- | --- |
| `owner` | Configured owner JID with full control |
| `superadmin` | High-level administration |
| `admin` | Normal bot administration |
| `moderator` | Room/plugin moderation commands |
| `trusted` | Trusted user commands |
| `user` | Normal user commands |
| `new` / `none` | Limited or unknown users |
| `banned` | No command access |

## Plugin overview

| Plugin | Category | Description |
| --- | --- | --- |
| `_admin` | `core` | Bot administration commands |
| `audit` | `core` | Admin audit log viewer |
| `backups` | `core` | Managed ZIP backups and restore helpers. |
| `birthday_notify` | `fun` | Automatic birthday notifications in rooms (opt-in per room) |
| `config_cmd` | `core` | Safe config inspection, validation and reload commands. |
| `db` | `core` | SQLite status and integrity inspection helpers. |
| `dice` | `games` | Roll dice with optional modifiers and success conditions. |
| `ducks` | `fun` | Duck game for MUCs with room toggles and leaderboards |
| `help` | `core` | Dynamic help for plugins and commands. |
| `info` | `info` | Wikipedia, Fediverse, Urban Dictionary and acronym lookup. |
| `karma` | `fun` | Room-local karma tracking with nick++ / nick-- |
| `pin` | `utility` | Pin room messages with paging and non-reply fallback. |
| `plugins` | `core` | Runtime plugin management |
| `poll` | `utility` | Room polls with voting, history and auto-close |
| `presence` | `info` | Bot presence and status management |
| `reminder` | `utility` | Schedule and manage reminders |
| `rooms` | `core` | Database-backed room management |
| `rss` | `info` | RSS/Atom feed watcher and poster |
| `sed` | `tools` | Message correction using sed-like syntax |
| `tasks` | `core` | Inspect supervised background tasks. |
| `tell` | `utility` | Store and deliver messages for users when they join a room again. |
| `tools` | `utility` | Utility commands: ping/pong, message echo, timezone-aware time/date lookups, and Unix timestamp conversion |
| `urlcheck` | `info` | URL title and YouTube info fetcher for groupchats |
| `users` | `core` | User management with caching, nick lookup and logging |
| `vcard` | `info` | Lookup and display vCard of a MUC occupant by MUC JID only |
| `weather` | `info` | Gives weather according to users location (supports MUCs and MUC DMs) |
| `xkcd` | `fun` | XKCD comic fetcher and broadcaster with full indexing |
| `xmpp` | `tools` | XMPP utility tools (ping, diagnostics, service discovery, DNS SRV, etc.) |

## Commands by category

### Admin

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,audit last` | `admin` | `private recommended` | Show recent admin audit events. |
| `,audit user` | `admin` | `private recommended` | Show recent audit events for one actor JID. |
| `,backup create` | `admin` | `private chat / MUC PM` | Create a managed ZIP backup archive. |
| `,backup list` | `admin` | `private chat / MUC PM` | List managed backup archives. |
| `,backup show` | `admin` | `private chat / MUC PM` | Show manifest details for one managed backup archive. |
| `,bot checkupdate` | `admin` | `private chat / MUC PM` | Check whether a newer EnvsBot release is available. |
| `,bot restart` | `owner` | `private chat / MUC PM` | Restart the bot process gracefully. |
| `,bot shutdown` | `owner` | `private chat / MUC PM` | Stop the bot using the configured stop command. |
| `,bot status` | `admin` | `private chat / MUC PM` | Show bot, runtime, XMPP, plugin and database status. |
| `,config diff` | `admin` | `private chat / MUC PM` | Show config values that differ from config_sample.py defaults. |
| `,config reload` | `admin` | `private chat / MUC PM` | Reload config.py into the running bot where possible. |
| `,config show` | `admin` | `private chat / MUC PM` | Show the effective config grouped like config_sample.py, with secrets redacted. |
| `,config validate` | `admin` | `private chat / MUC PM` | Validate the current config.py file. |
| `,db status` | `admin` | `private chat / MUC PM` | Show SQLite database path, size and integrity status. |
| `,restore` | `owner` | `private chat / MUC PM` | Restore a managed backup after explicit confirmation. |
| `,tasks` | `admin` | `private chat / MUC PM` | Show supervised background task status. |

### Core

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,bot version` | `user` | `any` | Show the running EnvsBot version and latest checked release. |
| `,help` | `none` | `any` | Show help for plugins and commands. |
| `,help inroom` | `user` | `room or MUC PM` | Enable, disable or show room help availability. |
| `,plugin info` | `admin` | `private chat / MUC PM` | Show metadata for one plugin. |
| `,plugin list` | `admin` | `private chat / MUC PM` | List loaded and available plugins by category. |
| `,plugin load` | `admin` | `private chat / MUC PM` | Load one plugin or all plugins. |
| `,plugin reload` | `admin` | `private chat / MUC PM` | Reload one plugin or all plugins. |
| `,plugin unload` | `admin` | `private chat / MUC PM` | Unload one plugin, optionally forced. |

### Fun

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,bef` | `user` | `any` | Befriend the current duck. |
| `,dice` | `user` | `any` | Roll dice using common dice notation. |
| `,duck` | `user` | `any` | Start or interact with the duck game. |
| `,duckstats` | `user` | `any` | Show duck game stats. |
| `,karma` | `user` | `any` | Show or update karma for a term. |
| `,trap` | `user` | `any` | Set a trap in the duck game. |
| `,xkcd` | `user` | `any` | Show an XKCD comic. |

### Info

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,acronyms` | `user` | `any` | Look up stored acronym definitions. |
| `,acronyms add` | `user` | `any` | Add a definition to an acronym. |
| `,acronyms delete` | `admin` | `any` | Delete an acronym completely. |
| `,acronyms list` | `admin` | `any` | List known acronyms. |
| `,acronyms merge` | `admin` | `any` | Merge one acronym into another. |
| `,acronyms remove` | `user` | `any` | Remove one acronym definition. |
| `,fediverse` | `user` | `any` | Look up Fediverse account or instance information. |
| `,info` | `moderator` | `room or MUC PM` | Enable, disable or show room access to information commands. |
| `,presence` | `none` | `any` | Show or control per-room access to presence lookup. |
| `,presence set` | `admin` | `private chat / MUC PM` | Set the bot presence state and status text. |
| `,udict` | `user` | `any` | Search Urban Dictionary. |
| `,wikipedia` | `user` | `any` | Search Wikipedia. |

### Profile

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,birthday` | `user` | `any` | Show or set your birthday. |
| `,emails` | `user` | `any` | Show or set profile emails. |
| `,fullname` | `user` | `any` | Show or set your full name. |
| `,nicknames` | `user` | `any` | Show or set profile nicknames. |
| `,notes` | `user` | `any` | Show or set profile notes. |
| `,organisations` | `user` | `any` | Show or set organisations in your profile. |
| `,timezone` | `user` | `any` | Show your configured timezone. |
| `,timezone set` | `user` | `any` | Set your timezone in the bot profile. |
| `,urls` | `user` | `any` | Show or set profile URLs. |
| `,vcard` | `user` | `any` | Show your bot profile/vCard data. |

### Rooms

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,birthday_notify` | `user` | `room or MUC PM` | Enable, disable or show birthday notifications for a room. |
| `,pin` | `user` | `any` | Pin, list or delete room pins. |
| `,poll` | `user` | `any` | Create and manage polls. |
| `,rooms add` | `admin` | `private chat / MUC PM` | Add or update a stored room configuration. |
| `,rooms delete` | `admin` | `private chat / MUC PM` | Remove a stored room and leave it if currently joined. |
| `,rooms disable` | `moderator` | `MUC PM only` | Disable a room-scoped plugin for the current room. |
| `,rooms enable` | `moderator` | `MUC PM only` | Enable a room-scoped plugin for the current room. |
| `,rooms join` | `admin` | `private chat / MUC PM` | Join a room immediately and store it if needed. |
| `,rooms leave` | `admin` | `private chat / MUC PM` | Leave a room without deleting its stored configuration. |
| `,rooms list` | `admin` | `private chat / MUC PM` | List stored rooms and currently joined rooms. |
| `,rooms plugins` | `moderator` | `MUC PM only` | Show plugin toggle state for the current room. |
| `,rooms set_plugin_defaults` | `moderator` | `MUC PM only` | Restore room plugin toggles to default values. |
| `,rooms sync` | `admin` | `private chat / MUC PM` | Synchronize joined rooms with stored autojoin settings. |
| `,rooms update` | `admin` | `private chat / MUC PM` | Update one field of a stored room. |
| `,rss` | `moderator` | `any` | Manage RSS feed subscriptions for a room. |

### Users

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,users admins` | `admin` | `private chat / MUC PM` | List users with admin-level roles. |
| `,users delete` | `admin` | `private chat / MUC PM` | Delete one user record and its runtime data. |
| `,users info` | `admin` | `private chat / MUC PM` | Show user info by JID or known nickname. |
| `,users list` | `admin` | `private chat only` | List users currently known in one joined room. |
| `,users role` | `admin` | `private chat / MUC PM` | Change a user's global bot role. |
| `,users roles` | `admin` | `private chat / MUC PM` | Show available roles and their ordering. |

### Utility

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,date` | `user` | `any` | Show the current date. |
| `,echo` | `user` | `any` | Echo text back to you. |
| `,ping` | `user` | `any` | Check whether the bot is alive. |
| `,remind` | `user` | `any` | Create a reminder. |
| `,remind delete` | `user` | `any` | Delete one reminder. |
| `,reminders` | `user` | `any` | List your reminders. |
| `,sed` | `user` | `any` | Apply sed-style corrections to recent messages. |
| `,seen` | `user` | `any` | Show when a user was last seen. |
| `,tell` | `user` | `any` | Leave a message for another user. |
| `,time` | `user` | `any` | Show the current time. |
| `,tools` | `moderator` | `room or MUC PM` | Enable, disable or show room access to utility commands. |
| `,ts` | `user` | `any` | Convert or show Unix timestamps. |
| `,urlcheck` | `user` | `any` | Check URLs for status and metadata. |
| `,utc` | `user` | `any` | Show current UTC time. |
| `,weather` | `user` | `any` | Show weather for a location. |

### Xmpp

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,xmpp` | `user` | `room or MUC PM` | Enable, disable or show room access to XMPP lookup commands. |
| `,xmpp compliance` | `user` | `any` | Check XMPP compliance features via disco. |
| `,xmpp contact` | `user` | `any` | Show contact addresses from service discovery. |
| `,xmpp help` | `user` | `any` | Show help for XMPP lookup subcommands. |
| `,xmpp info` | `user` | `any` | Show service discovery identity/features. |
| `,xmpp items` | `user` | `any` | List service discovery items. |
| `,xmpp ping` | `user` | `any` | Ping an XMPP entity. |
| `,xmpp srv` | `user` | `any` | Look up XMPP DNS SRV records. |
| `,xmpp uptime` | `user` | `any` | Query XMPP entity uptime. |
| `,xmpp version` | `user` | `any` | Query XMPP software version via XEP-0092. |

## Plugin command details

### admin

Category: `core`

Bot administration commands

#### `,bot checkupdate`

Check whether a newer EnvsBot release is available.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,bot checkupdate`

Aliases: `,bot updatecheck`, `,checkupdate`, `,updatecheck`

Examples:

- `,bot checkupdate`
- `,checkupdate`
- `,updatecheck`

#### `,bot restart`

Restart the bot process gracefully.

Role: `owner`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,bot restart`

Aliases: `,restart`

Examples:

- `,bot restart`

#### `,bot shutdown`

Stop the bot using the configured stop command.

Role: `owner`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,bot shutdown`

Aliases: `,shutdown`

Examples:

- `,bot shutdown`

#### `,bot status`

Show bot, runtime, XMPP, plugin and database status.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,bot status [full]`

Aliases: `,bot info`, `,status`

Examples:

- `,bot status`
- `,status`
- `,bot status full`

#### `,bot version`

Show the running EnvsBot version and latest checked release.

Role: `user`  
Context: `any`  
Category: `core`  
Usage: `,bot version`

Aliases: `,version`

Examples:

- `,bot version`
- `,version`

### audit

Category: `core`

Admin audit log viewer

#### `,audit last`

Show recent admin audit events.

Role: `admin`  
Context: `private recommended`  
Category: `admin`  
Usage: `,audit last [all|page|last|limit]`

Aliases: `,audit`, `,audits last`

Examples:

- `,audit last`
- `,audit last 2`

#### `,audit user`

Show recent audit events for one actor JID.

Role: `admin`  
Context: `private recommended`  
Category: `admin`  
Usage: `,audit user <jid>`

Aliases: `,audits user`

Examples:

- `,audit user admin@example.org`

### backups

Category: `core`

Managed ZIP backups and restore helpers.

#### `,backup create`

Create a managed ZIP backup archive.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,backup [reason]`

Aliases: `,backup`

Examples:

- `,backup`
- `,backup before config change`

#### `,backup list`

List managed backup archives.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,backup list [all|page|last]`

Aliases: `,backup ls`, `,backups`

Examples:

- `,backup list`
- `,backup list all`

#### `,backup show`

Show manifest details for one managed backup archive.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,backup show <archive|last>`

Examples:

- `,backup show last`

#### `,restore`

Restore a managed backup after explicit confirmation.

Role: `owner`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,restore <archive|last> confirm`

Aliases: `,backup restore`

Examples:

- `,restore last confirm`

### birthday_notify

Category: `fun`

Automatic birthday notifications in rooms (opt-in per room)

#### `,birthday_notify`

Enable, disable or show birthday notifications for a room.

Role: `user`  
Context: `room or MUC PM`  
Category: `rooms`  
Usage: `,birthday_notify <on|off|status>`

Examples:

- `,birthday_notify status`

### config_cmd

Category: `core`

Safe config inspection, validation and reload commands.

#### `,config diff`

Show config values that differ from config_sample.py defaults.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,config diff [all|page|last]`

Examples:

- `,config diff`
- `,config diff all`

#### `,config reload`

Reload config.py into the running bot where possible.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,config reload`

Examples:

- `,config reload`

#### `,config show`

Show the effective config grouped like config_sample.py, with secrets redacted.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,config show [all|page|last]`

Aliases: `,config`

Examples:

- `,config show`
- `,config show all`

#### `,config validate`

Validate the current config.py file.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,config validate`

Examples:

- `,config validate`

### db

Category: `core`

SQLite status and integrity inspection helpers.

#### `,db status`

Show SQLite database path, size and integrity status.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,db status`

Aliases: `,database status`

Examples:

- `,db status`

### dice

Category: `games`

Roll dice with optional modifiers and success conditions.

#### `,dice`

Roll dice using common dice notation.

Role: `user`  
Context: `any`  
Category: `fun`  
Usage: `,dice [NdM]`

Aliases: `,r`, `,roll`

Examples:

- `,dice`
- `,dice 2d6`

### ducks

Category: `fun`

Duck game for MUCs with room toggles and leaderboards

#### `,bef`

Befriend the current duck.

Role: `user`  
Context: `any`  
Category: `fun`  
Usage: `,bef`

Examples:

- `,bef`

#### `,duck`

Start or interact with the duck game.

Role: `user`  
Context: `any`  
Category: `fun`  
Usage: `,duck`

Examples:

- `,duck`

#### `,duckstats`

Show duck game stats.

Role: `user`  
Context: `any`  
Category: `fun`  
Usage: `,duckstats [nick]`

Examples:

- `,duckstats`

#### `,trap`

Set a trap in the duck game.

Role: `user`  
Context: `any`  
Category: `fun`  
Usage: `,trap`

Examples:

- `,trap`

### help

Category: `core`

Dynamic help for plugins and commands.

#### `,help`

Show help for plugins and commands.

Role: `none`  
Context: `any`  
Category: `core`  
Usage: `,help [all|commands|plugins|roles|categories|category <name>|<plugin>|<command>]`

Aliases: `,h`

Examples:

- `,help`
- `,help rooms`
- `,help rooms add`
- `,help ,users role`
- `,help category rooms`

#### `,help inroom`

Enable, disable or show room help availability.

Role: `user`  
Context: `room or MUC PM`  
Category: `core`  
Usage: `,help inroom <on|off|status>`

Aliases: `,h inroom`

Examples:

- `,help inroom on`
- `,help inroom status`

### info

Category: `info`

Wikipedia, Fediverse, Urban Dictionary and acronym lookup.

#### `,acronyms`

Look up stored acronym definitions.

Role: `user`  
Context: `any`  
Category: `info`  
Usage: `,acronyms <term>`

Aliases: `,acro`, `,acronym`

Examples:

- `,acro XMPP`

#### `,acronyms add`

Add a definition to an acronym.

Role: `user`  
Context: `any`  
Category: `info`  
Usage: `,acronyms add <term> <definition>`

Aliases: `,acro add`, `,acronym add`

Examples:

- `,acro add XMPP Extensible Messaging and Presence Protocol`

#### `,acronyms delete`

Delete an acronym completely.

Role: `admin`  
Context: `any`  
Category: `info`  
Usage: `,acronyms delete <term>`

Aliases: `,acro delete`, `,acronym delete`

Examples:

- `,acro delete XMPP`

#### `,acronyms list`

List known acronyms.

Role: `admin`  
Context: `any`  
Category: `info`  
Usage: `,acronyms list [all|page|last]`

Aliases: `,acro list`, `,acronym list`

Examples:

- `,acro list`

#### `,acronyms merge`

Merge one acronym into another.

Role: `admin`  
Context: `any`  
Category: `info`  
Usage: `,acronyms merge <source> <target>`

Aliases: `,acro merge`, `,acronym merge`

Examples:

- `,acro merge xmpp XMPP`

#### `,acronyms remove`

Remove one acronym definition.

Role: `user`  
Context: `any`  
Category: `info`  
Usage: `,acronyms remove <term> <number>`

Aliases: `,acro remove`, `,acronym remove`

Examples:

- `,acro remove XMPP 1`

#### `,fediverse`

Look up Fediverse account or instance information.

Role: `user`  
Context: `any`  
Category: `info`  
Usage: `,fediverse <account|instance>`

Aliases: `,fedi`

Examples:

- `,fedi @user@example.org`

#### `,info`

Enable, disable or show room access to information commands.

Role: `moderator`  
Context: `room or MUC PM`  
Category: `info`  
Usage: `,info <on|off|status>`

Examples:

- `,info status`

#### `,udict`

Search Urban Dictionary.

Role: `user`  
Context: `any`  
Category: `info`  
Usage: `,udict <term>`

Aliases: `,ud`

Examples:

- `,ud xmpp`

#### `,wikipedia`

Search Wikipedia.

Role: `user`  
Context: `any`  
Category: `info`  
Usage: `,wikipedia <term>`

Aliases: `,wiki`

Examples:

- `,wiki XMPP`

### karma

Category: `fun`

Room-local karma tracking with nick++ / nick--

#### `,karma`

Show or update karma for a term.

Role: `user`  
Context: `any`  
Category: `fun`  
Usage: `,karma [term|term++|term--]`

Examples:

- `,karma xmpp++`
- `,karma xmpp`

### pin

Category: `utility`

Pin room messages with paging and non-reply fallback.

#### `,pin`

Pin, list or delete room pins.

Role: `user`  
Context: `any`  
Category: `rooms`  
Usage: `,pin <add|list|delete|on|off|status> ...`

Examples:

- `,pin list`

### plugins

Category: `core`

Runtime plugin management

#### `,plugin info`

Show metadata for one plugin.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `core`  
Usage: `,plugin info <plugin>`

Aliases: `,plugins info`

Examples:

- `,plugin info rooms`

#### `,plugin list`

List loaded and available plugins by category.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `core`  
Usage: `,plugins list [all|page|last]`

Aliases: `,plugins list`

Examples:

- `,plugins list`
- `,plugins list all`

#### `,plugin load`

Load one plugin or all plugins.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `core`  
Usage: `,plugin load <plugin|all>`

Aliases: `,plugins load`

Examples:

- `,plugin load weather`

#### `,plugin reload`

Reload one plugin or all plugins.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `core`  
Usage: `,plugin reload <plugin|all> [auto]`

Aliases: `,plugins reload`

Examples:

- `,plugin reload help`
- `,plugin reload all auto`

#### `,plugin unload`

Unload one plugin, optionally forced.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `core`  
Usage: `,plugin unload <plugin> [force]`

Aliases: `,plugins unload`

Examples:

- `,plugin unload weather`

### poll

Category: `utility`

Room polls with voting, history and auto-close

#### `,poll`

Create and manage polls.

Role: `user`  
Context: `any`  
Category: `rooms`  
Usage: `,poll <new|vote|list|close|on|off|status> ...`

Examples:

- `,poll list`

### presence

Category: `info`

Bot presence and status management

#### `,presence`

Show or control per-room access to presence lookup.

Role: `none`  
Context: `any`  
Category: `info`  
Usage: `,presence [on|off|status]`

Examples:

- `,presence`
- `,presence status`

#### `,presence set`

Set the bot presence state and status text.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `info`  
Usage: `,presence set <online|chat|away|xa|dnd> [message]`

Examples:

- `,presence set away maintenance`

### reminder

Category: `utility`

Schedule and manage reminders

#### `,remind`

Create a reminder.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,remind <when> <text>`

Aliases: `,rem`, `,reminder`

Examples:

- `,remind 10m check logs`

#### `,remind delete`

Delete one reminder.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,remind delete <id>`

Aliases: `,remind cancel`, `,remind rm`

Examples:

- `,remind delete 12`

#### `,reminders`

List your reminders.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,reminders [all|page|last]`

Aliases: `,remind list`, `,rems`

Examples:

- `,reminders`

### rooms

Category: `core`

Database-backed room management

#### `,rooms add`

Add or update a stored room configuration.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `rooms`  
Usage: `,rooms add <room_jid> [nick] [autojoin]`

Aliases: `,room add`

Examples:

- `,rooms add test@conference.example.org EnvsBot true`

#### `,rooms delete`

Remove a stored room and leave it if currently joined.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `rooms`  
Usage: `,rooms delete <room_jid>`

Aliases: `,room delete`

Examples:

- `,rooms delete test@conference.example.org`

#### `,rooms disable`

Disable a room-scoped plugin for the current room.

Role: `moderator`  
Context: `MUC PM only`  
Category: `rooms`  
Usage: `,rooms disable <plugin>`

Aliases: `,room disable`

Examples:

- `,rooms disable xkcd`

#### `,rooms enable`

Enable a room-scoped plugin for the current room.

Role: `moderator`  
Context: `MUC PM only`  
Category: `rooms`  
Usage: `,rooms enable <plugin>`

Aliases: `,room enable`

Examples:

- `,rooms enable weather`

#### `,rooms join`

Join a room immediately and store it if needed.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `rooms`  
Usage: `,rooms join <room_jid> [nick]`

Aliases: `,room join`

Examples:

- `,rooms join test@conference.example.org`

#### `,rooms leave`

Leave a room without deleting its stored configuration.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `rooms`  
Usage: `,rooms leave <room_jid>`

Aliases: `,room leave`

Examples:

- `,rooms leave test@conference.example.org`

#### `,rooms list`

List stored rooms and currently joined rooms.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `rooms`  
Usage: `,rooms list [all|page|last]`

Aliases: `,room list`

Examples:

- `,rooms list`
- `,rooms list all`

#### `,rooms plugins`

Show plugin toggle state for the current room.

Role: `moderator`  
Context: `MUC PM only`  
Category: `rooms`  
Usage: `,rooms plugins [all|page|last]`

Aliases: `,room plugins`

Examples:

- `,rooms plugins`
- `,rooms plugins all`

#### `,rooms set_plugin_defaults`

Restore room plugin toggles to default values.

Role: `moderator`  
Context: `MUC PM only`  
Category: `rooms`  
Usage: `,rooms set_plugin_defaults`

Aliases: `,room set_plugin_defaults`, `,room spd`, `,rooms spd`

Examples:

- `,rooms spd`

#### `,rooms sync`

Synchronize joined rooms with stored autojoin settings.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `rooms`  
Usage: `,rooms sync`

Aliases: `,room sync`

Examples:

- `,rooms sync`

#### `,rooms update`

Update one field of a stored room.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `rooms`  
Usage: `,rooms update <room_jid> <nick|autojoin|status> <value>`

Aliases: `,room update`

Examples:

- `,rooms update test@conference.example.org autojoin true`

### rss

Category: `info`

RSS/Atom feed watcher and poster

#### `,rss`

Manage RSS feed subscriptions for a room.

Role: `moderator`  
Context: `any`  
Category: `rooms`  
Usage: `,rss <add|list|delete|on|off|status> ...`

Examples:

- `,rss list`

### sed

Category: `tools`

Message correction using sed-like syntax

#### `,sed`

Apply sed-style corrections to recent messages.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,s/old/new/`

Examples:

- `,s/teh/the/`

### tasks

Category: `core`

Inspect supervised background tasks.

#### `,tasks`

Show supervised background task status.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `admin`  
Usage: `,tasks [full] [plugin <name>] [running|failed|cancelled|done] [all|page|last]`

Aliases: `,bot tasks`

Examples:

- `,tasks`
- `,tasks full`
- `,tasks plugin rss`
- `,tasks failed`

### tell

Category: `utility`

Store and deliver messages for users when they join a room again.

#### `,tell`

Leave a message for another user.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,tell <nick> <message>`

Examples:

- `,tell alice I fixed it`

### tools

Category: `utility`

Utility commands: ping/pong, message echo, timezone-aware time/date lookups, and Unix timestamp conversion

#### `,date`

Show the current date.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,date [timezone]`

Examples:

- `,date`

#### `,echo`

Echo text back to you.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,echo <text>`

Examples:

- `,echo hello`

#### `,ping`

Check whether the bot is alive.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,ping`

Aliases: `,pong`

Examples:

- `,ping`

#### `,seen`

Show when a user was last seen.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,seen <nick|jid>`

Aliases: `,s`

Examples:

- `,seen alice`

#### `,time`

Show the current time.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,time [timezone]`

Aliases: `,t`

Examples:

- `,time Europe/Berlin`

#### `,tools`

Enable, disable or show room access to utility commands.

Role: `moderator`  
Context: `room or MUC PM`  
Category: `utility`  
Usage: `,tools <on|off|status>`

Examples:

- `,tools status`

#### `,ts`

Convert or show Unix timestamps.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,ts [timestamp]`

Examples:

- `,ts`

#### `,utc`

Show current UTC time.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,utc`

Examples:

- `,utc`

### urlcheck

Category: `info`

URL title and YouTube info fetcher for groupchats

#### `,urlcheck`

Check URLs for status and metadata.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,urlcheck <url>`

Examples:

- `,urlcheck https://envs.net`

### users

Category: `core`

User management with caching, nick lookup and logging

#### `,users admins`

List users with admin-level roles.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `users`  
Usage: `,users admins [all|page|last]`

Aliases: `,user admin`, `,user admins`, `,users admin`

Examples:

- `,users admins`

#### `,users delete`

Delete one user record and its runtime data.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `users`  
Usage: `,users delete <jid>`

Aliases: `,user delete`

Examples:

- `,users delete alice@example.org`

#### `,users info`

Show user info by JID or known nickname.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `users`  
Usage: `,users info <jid|nick>`

Aliases: `,user info`

Examples:

- `,users info alice@example.org`

#### `,users list`

List users currently known in one joined room.

Role: `admin`  
Context: `private chat only`  
Category: `users`  
Usage: `,users list [room_jid]`

Aliases: `,user list`

Examples:

- `,users list test@conference.example.org`

#### `,users role`

Change a user's global bot role.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `users`  
Usage: `,users role <jid> <role>`

Aliases: `,user role`

Examples:

- `,users role alice@example.org trusted`

#### `,users roles`

Show available roles and their ordering.

Role: `admin`  
Context: `private chat / MUC PM`  
Category: `users`  
Usage: `,users roles`

Aliases: `,user roles`

Examples:

- `,users roles`

### vcard

Category: `info`

Lookup and display vCard of a MUC occupant by MUC JID only

#### `,birthday`

Show or set your birthday.

Role: `user`  
Context: `any`  
Category: `profile`  
Usage: `,birthday [YYYY-MM-DD]`

Aliases: `,b`

Examples:

- `,birthday 1989-01-01`

#### `,emails`

Show or set profile emails.

Role: `user`  
Context: `any`  
Category: `profile`  
Usage: `,emails [email]`

Aliases: `,e`

Examples:

- `,emails me@example.org`

#### `,fullname`

Show or set your full name.

Role: `user`  
Context: `any`  
Category: `profile`  
Usage: `,fullname [name]`

Aliases: `,f`

Examples:

- `,fullname Sven`

#### `,nicknames`

Show or set profile nicknames.

Role: `user`  
Context: `any`  
Category: `profile`  
Usage: `,nicknames [names]`

Aliases: `,nicks`

Examples:

- `,nicks Sven, creme`

#### `,notes`

Show or set profile notes.

Role: `user`  
Context: `any`  
Category: `profile`  
Usage: `,notes [text]`

Examples:

- `,notes likes boring tech`

#### `,organisations`

Show or set organisations in your profile.

Role: `user`  
Context: `any`  
Category: `profile`  
Usage: `,organisations [text]`

Aliases: `,orgs`

Examples:

- `,orgs envs.net`

#### `,timezone`

Show your configured timezone.

Role: `user`  
Context: `any`  
Category: `profile`  
Usage: `,timezone`

Aliases: `,tz`

Examples:

- `,tz`

#### `,timezone set`

Set your timezone in the bot profile.

Role: `user`  
Context: `any`  
Category: `profile`  
Usage: `,timezone set <IANA timezone>`

Aliases: `,tz set`

Examples:

- `,tz set Europe/Berlin`

#### `,urls`

Show or set profile URLs.

Role: `user`  
Context: `any`  
Category: `profile`  
Usage: `,urls [url]`

Aliases: `,u`

Examples:

- `,urls https://envs.net`

#### `,vcard`

Show your bot profile/vCard data.

Role: `user`  
Context: `any`  
Category: `profile`  
Usage: `,vcard`

Aliases: `,v`

Examples:

- `,vcard`

### weather

Category: `info`

Gives weather according to users location (supports MUCs and MUC DMs)

#### `,weather`

Show weather for a location.

Role: `user`  
Context: `any`  
Category: `utility`  
Usage: `,weather <location>`

Aliases: `,w`

Examples:

- `,weather Berlin`

### xkcd

Category: `fun`

XKCD comic fetcher and broadcaster with full indexing

#### `,xkcd`

Show an XKCD comic.

Role: `user`  
Context: `any`  
Category: `fun`  
Usage: `,xkcd [latest|random|number]`

Examples:

- `,xkcd random`

### xmpp

Category: `tools`

XMPP utility tools (ping, diagnostics, service discovery, DNS SRV, etc.)

#### `,xmpp`

Enable, disable or show room access to XMPP lookup commands.

Role: `user`  
Context: `room or MUC PM`  
Category: `xmpp`  
Usage: `,xmpp <on|off|status>`

Aliases: `,x`

Examples:

- `,xmpp status`

#### `,xmpp compliance`

Check XMPP compliance features via disco.

Role: `user`  
Context: `any`  
Category: `xmpp`  
Usage: `,xmpp compliance <jid>`

Aliases: `,x compliance`

Examples:

- `,x compliance envs.net`

#### `,xmpp contact`

Show contact addresses from service discovery.

Role: `user`  
Context: `any`  
Category: `xmpp`  
Usage: `,xmpp contact <jid>`

Aliases: `,x contact`

Examples:

- `,x contact envs.net`

#### `,xmpp help`

Show help for XMPP lookup subcommands.

Role: `user`  
Context: `any`  
Category: `xmpp`  
Usage: `,xmpp help`

Aliases: `,x help`

Examples:

- `,x help`

#### `,xmpp info`

Show service discovery identity/features.

Role: `user`  
Context: `any`  
Category: `xmpp`  
Usage: `,xmpp info <jid>`

Aliases: `,x info`

Examples:

- `,x info conference.envs.net`

#### `,xmpp items`

List service discovery items.

Role: `user`  
Context: `any`  
Category: `xmpp`  
Usage: `,xmpp items <jid>`

Aliases: `,x items`

Examples:

- `,x items envs.net`

#### `,xmpp ping`

Ping an XMPP entity.

Role: `user`  
Context: `any`  
Category: `xmpp`  
Usage: `,xmpp ping <jid>`

Aliases: `,x ping`

Examples:

- `,x ping envs.net`

#### `,xmpp srv`

Look up XMPP DNS SRV records.

Role: `user`  
Context: `any`  
Category: `xmpp`  
Usage: `,xmpp srv <domain>`

Aliases: `,x srv`

Examples:

- `,x srv envs.net`

#### `,xmpp uptime`

Query XMPP entity uptime.

Role: `user`  
Context: `any`  
Category: `xmpp`  
Usage: `,xmpp uptime <jid>`

Aliases: `,x uptime`

Examples:

- `,x uptime envs.net`

#### `,xmpp version`

Query XMPP software version via XEP-0092.

Role: `user`  
Context: `any`  
Category: `xmpp`  
Usage: `,xmpp version <jid>`

Aliases: `,x version`

Examples:

- `,x version envs.net`
