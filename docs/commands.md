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
- `,help ,<command>`

For paginated commands, `all` disables paging and `last` jumps to the final page.

## Context notes

- `private chat / MUC PM` means a normal 1:1 chat with the bot or a MUC private message through a room occupant JID.
- Room-scoped feature commands can infer the target room from a room message or MUC PM.
- When using a normal private chat, pass `<room_jid>` explicitly for room-scoped feature commands.
- EnvsBot has no separate fixed `ADMIN_ROOM` setting; global bot privileges come from `OWNER`, `ADMINS` and stored bot roles.

## Room plugin settings

Room-scoped plugin toggles are managed through the `rooms` commands:

- `,rooms plugins [<room_jid>] [all|page|last]`
- `,rooms enable [<room_jid>] <plugin>`
- `,rooms disable [<room_jid>] <plugin>`
- `,rooms set_plugin_defaults [<room_jid>]`

Examples:

- `,rooms enable ducks`
- `,rooms disable ducks`
- `,rooms enable room@conference.example.org ducks`
- `,rooms plugins room@conference.example.org all`

In a room or MUC PM the target room can usually be inferred. In a normal private chat, pass `<room_jid>` explicitly. The sender must be room owner/admin or have a bot moderator/admin role.
Defaults shown by these commands come from `ROOM_PLUGIN_DEFAULTS` in `config.py` merged with internal fallbacks. Existing per-room overrides stay in the database until `,rooms set_plugin_defaults` is used for that room.

Known room feature names:

`birthday_notify`, `dice`, `ducks`, `help`, `idlerpg`, `information`, `karma`, `pin`, `poll`, `presence`, `reminder`, `sed`, `tell`, `tools`, `urlcheck`, `vcard`, `weather`, `xkcd`, `xmpp`

`information` can also be addressed as `info`.

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

| Plugin | Source | Category | Description |
| --- | --- | --- | --- |
| `_admin` | `core` | `core` | Bot administration commands |
| `audit` | `core` | `core` | Admin audit log viewer |
| `backups` | `core` | `core` | Managed ZIP backups and restore helpers. |
| `config_cmd` | `core` | `core` | Safe config inspection, validation and reload commands. |
| `doctor` | `core` | `core` | Operator health checks and runtime diagnostics. |
| `help` | `core` | `core` | Dynamic help for plugins and commands. |
| `plugins` | `core` | `core` | Runtime plugin management |
| `presence` | `core` | `info` | Bot presence and status management |
| `rooms` | `core` | `core` | Database-backed room management |
| `tasks` | `core` | `core` | Inspect supervised background tasks. |
| `users` | `core` | `core` | User management with caching, nick lookup and logging |
| `birthday_notify` | `plugins` | `fun` | Automatic birthday notifications in rooms (opt-in per room) |
| `dice` | `plugins` | `games` | Roll dice with optional modifiers and success conditions. |
| `ducks` | `plugins` | `fun` | Duck game for MUCs with room toggles and leaderboards |
| `idlerpg` | `plugins` | `fun` | IdleRPG game for MUCs, inspired by the classic IRC game |
| `info` | `plugins` | `info` | Wikipedia, Fediverse, Urban Dictionary and acronym lookup. |
| `karma` | `plugins` | `fun` | Room-local karma tracking with nick++ / nick-- |
| `pin` | `plugins` | `utility` | Pin room messages with paging and non-reply fallback. |
| `poll` | `plugins` | `utility` | Room polls with voting, history and auto-close |
| `reminder` | `plugins` | `utility` | Schedule and manage reminders |
| `rss` | `plugins` | `info` | RSS/Atom feed watcher and poster |
| `sed` | `plugins` | `tools` | Message correction using sed-like syntax |
| `tell` | `plugins` | `utility` | Store and deliver messages for users when they join a room again. |
| `tools` | `plugins` | `utility` | Utility commands: ping/pong, message echo, timezone-aware time/date lookups, and Unix timestamp conversion |
| `urlcheck` | `plugins` | `info` | URL title and YouTube info fetcher for groupchats |
| `vcard` | `plugins` | `info` | Lookup and display vCard of a MUC occupant by MUC JID only |
| `weather` | `plugins` | `info` | Gives weather according to users location (supports MUCs and MUC DMs) |
| `xkcd` | `plugins` | `fun` | XKCD comic fetcher and broadcaster with full indexing |
| `xmpp` | `plugins` | `tools` | XMPP utility tools (ping, diagnostics, service discovery, DNS SRV, etc.) |

## Commands by category

### Admin

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,audit action` | `admin` | `private recommended` | Show recent audit events for one action/event type. |
| `,audit last` | `admin` | `private recommended` | Show recent admin audit events. |
| `,audit target` | `admin` | `private recommended` | Show recent audit events for one target value. |
| `,audit user` | `admin` | `private recommended` | Show recent audit events for one actor JID. |
| `,backup create` | `admin` | `private chat / MUC PM` | Create a managed ZIP backup archive. |
| `,backup list` | `admin` | `private chat / MUC PM` | List managed backup archives. |
| `,backup prune` | `admin` | `private chat / MUC PM` | Prune managed backup archives, with optional dry-run. |
| `,backup show` | `admin` | `private chat / MUC PM` | Show manifest details for one managed backup archive. |
| `,bot checkupdate` | `admin` | `private chat / MUC PM` | Check whether a newer EnvsBot release is available. |
| `,bot restart` | `owner` | `private chat / MUC PM` | Restart the bot process gracefully. |
| `,bot shutdown` | `owner` | `private chat / MUC PM` | Stop the bot using the configured stop command. |
| `,bot status` | `admin` | `private chat / MUC PM` | Show bot, runtime, XMPP, plugin and database status. |
| `,config diff` | `admin` | `private chat / MUC PM` | Show config values that differ from config_sample.py defaults. |
| `,config reload` | `admin` | `private chat / MUC PM` | Reload config.py into the running bot where possible. |
| `,config show` | `admin` | `private chat / MUC PM` | Show the effective config grouped like config_sample.py, with secrets redacted. |
| `,config validate` | `admin` | `private chat / MUC PM` | Validate the current config.py file. |
| `,doctor` | `admin` | `private chat / MUC PM` | Run operator health checks for config, DB, rooms, plugins, tasks and backups. |
| `,plugin diagnose` | `admin` | `private chat / MUC PM` | Show diagnostics for one plugin, including hooks, commands and tasks. |
| `,plugin state` | `admin` | `private chat / MUC PM` | Show plugin-provided runtime state counters. |
| `,restore` | `owner` | `private chat / MUC PM` | Restore a managed backup after explicit confirmation. |
| `,tasks` | `admin` | `private chat / MUC PM` | Show supervised background task status. |

### Core

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,bot version` | `user` | `any` | Show the running EnvsBot version and latest checked release. |
| `,help` | `none` | `any` | Show help for plugins and commands. |
| `,help inroom` | `user` | `room or MUC PM` | Enable, disable or show room help availability. |
| `,plugin info` | `admin` | `private chat / MUC PM` | Show metadata and source information for one plugin. |
| `,plugin list` | `admin` | `private chat / MUC PM` | List loaded and available core/optional plugins. |
| `,plugin load` | `admin` | `private chat / MUC PM` | Load one plugin or all plugins. |
| `,plugin reload` | `admin` | `private chat / MUC PM` | Reload one plugin or all plugins. |
| `,plugin unload` | `admin` | `private chat / MUC PM` | Unload one optional plugin; core plugins are protected. |

### Fun

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,bef` | `user` | `any` | Befriend the current duck. |
| `,dice` | `user` | `any` | Roll dice using common dice notation. |
| `,duck` | `user` | `room / MUC PM; use rooms enable with <room_jid> from private chat` | Start or interact with the duck game. |
| `,duckstats` | `user` | `any` | Show duck game stats. |
| `,idlerpg` | `user` | `groupchat / MUC PM` | Play IdleRPG in a MUC |
| `,karma` | `user` | `any` | Show room-local karma scores and rankings. |
| `,trap` | `user` | `any` | Set a trap in the duck game. |
| `,xkcd` | `user` | `any` | Show an XKCD comic or control room access to XKCD. |

### Info

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,acronyms` | `user` | `any` | Look up stored acronym definitions. |
| `,acronyms add` | `user` | `any` | Suggest a new acronym definition for admin review. |
| `,acronyms delete` | `admin` | `any` | Delete pending acronym suggestions by nick or definition. |
| `,acronyms list` | `admin` | `any` | List pending acronym additions and removals. |
| `,acronyms merge` | `admin` | `any` | Apply pending acronym additions and removals. |
| `,acronyms remove` | `user` | `any` | Suggest removing one acronym definition for admin review. |
| `,fediverse` | `user` | `any` | Show the latest public post from a Fediverse account. |
| `,info` | `moderator` | `room or MUC PM` | Enable, disable or show room access to information commands. |
| `,presence` | `none` | `any` | Show or control per-room access to presence lookup. |
| `,presence set` | `admin` | `private chat / MUC PM` | Set the bot presence state and status text. |
| `,udict` | `user` | `any` | Search Urban Dictionary. |
| `,wikipedia` | `user` | `any` | Search Wikipedia. |

### Profile

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,birthday` | `user` | `any` | Show birthday data from a user's vCard. |
| `,emails` | `user` | `any` | Show email addresses from a user's vCard. |
| `,fullname` | `user` | `any` | Show the full name from a user's vCard. |
| `,nicknames` | `user` | `any` | Show nicknames from a user's vCard. |
| `,notes` | `user` | `any` | Show notes from a user's vCard. |
| `,organisations` | `user` | `any` | Show organisations from a user's vCard. |
| `,timezone` | `user` | `any` | Show your configured timezone. |
| `,timezone set` | `user` | `any` | Set your timezone in the bot profile. |
| `,urls` | `user` | `any` | Show URLs from a user's vCard. |
| `,vcard` | `user` | `any` | Show vCard data or control room access to vCard lookups. |

### Rooms

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,birthday_notify` | `user` | `room or MUC PM` | Enable, disable or show birthday notifications for a room. |
| `,pin` | `user` | `any` | Pin, list or delete room pins. |
| `,poll` | `user` | `any` | Create and manage polls. |
| `,rooms add` | `admin` | `private chat / MUC PM` | Add or update a stored room configuration. |
| `,rooms delete` | `admin` | `private chat / MUC PM` | Remove a stored room and leave it if currently joined. |
| `,rooms diagnose` | `admin` | `private chat / MUC PM` | Show operational diagnostics for one room. |
| `,rooms disable` | `user` | `room / MUC PM / private chat with <room_jid>` | Disable a room plugin toggle; requires room admin/owner or bot moderator. |
| `,rooms enable` | `user` | `room / MUC PM / private chat with <room_jid>` | Enable a room plugin toggle; requires room admin/owner or bot moderator. |
| `,rooms invite` | `admin` | `private chat / MUC PM / invite notify room` | List, accept, decline or clean up pending room invites. |
| `,rooms join` | `admin` | `private chat / MUC PM` | Join a room immediately and store it if needed. |
| `,rooms leave` | `admin` | `private chat / MUC PM` | Leave a room without deleting its stored configuration. |
| `,rooms list` | `admin` | `private chat / MUC PM` | List stored rooms and currently joined rooms. |
| `,rooms plugins` | `user` | `room / MUC PM / private chat with <room_jid>` | Show room plugin toggles; requires room admin/owner or bot moderator. |
| `,rooms set_plugin_defaults` | `user` | `room / MUC PM / private chat with <room_jid>` | Restore room plugin toggles for a room; requires room admin/owner or bot moderator. |
| `,rooms sync` | `admin` | `private chat / MUC PM` | Synchronize joined rooms with stored autojoin settings. |
| `,rooms update` | `admin` | `private chat / MUC PM` | Update one field of a stored room. |
| `,rss` | `user` | `any` | Manage RSS feed subscriptions for rooms. |

### Users

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,users admins` | `admin` | `private chat / MUC PM` | List users with admin-level roles. |
| `,users delete` | `admin` | `private chat / MUC PM` | Delete one non-privileged user record and its runtime data. |
| `,users grant` | `admin` | `private chat / MUC PM` | Grant room-scoped plugin permissions to a user. |
| `,users grants` | `admin` | `private chat / MUC PM` | Show a user's room-scoped plugin permissions. |
| `,users info` | `admin` | `private chat / MUC PM` | Show user info by JID or known nickname. |
| `,users list` | `admin` | `private chat only` | List users currently known in one joined room. |
| `,users permissions` | `admin` | `private chat / MUC PM` | Diagnose global, room and room-scoped plugin permissions. |
| `,users revoke` | `admin` | `private chat / MUC PM` | Revoke room-scoped plugin permissions from a user. |
| `,users role` | `admin` | `private chat / MUC PM` | Change a user's global bot role with hierarchy checks. |
| `,users roles` | `admin` | `private chat / MUC PM` | Show available roles and their ordering. |

### Utility

| Command | Role | Context | Description |
| --- | --- | --- | --- |
| `,date` | `user` | `any` | Show the current date from a stored profile timezone. |
| `,echo` | `user` | `any` | Echo text back to you. |
| `,ping` | `user` | `any` | Check whether the bot is alive. |
| `,remind` | `user` | `any` | Create a reminder. |
| `,remind delete` | `user` | `any` | Delete one reminder. |
| `,reminders` | `user` | `any` | List your reminders. |
| `,sed` | `user` | `any` | Apply sed-style corrections or control room access to sed. |
| `,seen` | `user` | `any` | Show when a user was last seen. |
| `,tell` | `user` | `any` | Leave a message for another user. |
| `,time` | `user` | `any` | Show the current time from a stored profile timezone. |
| `,tools` | `moderator` | `room or MUC PM` | Enable, disable or show room access to utility commands. |
| `,ts` | `user` | `any` | Convert a Unix timestamp to your configured timezone. |
| `,urlcheck` | `user` | `room or MUC PM` | Enable, disable or show automatic URL checks in a room. |
| `,utc` | `user` | `any` | Show current UTC time. |
| `,weather` | `user` | `any` | Show weather from a user's vCard location or control room access. |

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

Source: `core`
Category: `core`

Bot administration commands

#### `,bot checkupdate`

Check whether a newer EnvsBot release is available.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot checkupdate`

Aliases: `,bot updatecheck`, `,checkupdate`, `,updatecheck`

Examples:

- `,bot checkupdate`
- `,checkupdate`
- `,updatecheck`

#### `,bot restart`

Restart the bot process gracefully.

Role: `owner`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot restart`

Aliases: `,restart`

Examples:

- `,bot restart`

#### `,bot shutdown`

Stop the bot using the configured stop command.

Role: `owner`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot shutdown`

Aliases: `,shutdown`

Examples:

- `,bot shutdown`

#### `,bot status`

Show bot, runtime, XMPP, plugin and database status.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot status [full]`

Aliases: `,bot info`, `,status`

Examples:

- `,bot status`
- `,status`
- `,bot status full`

#### `,bot version`

Show the running EnvsBot version and latest checked release.

Role: `user`<br>
Context: `any`<br>
Category: `core`<br>
Usage: `,bot version`

Aliases: `,version`

Examples:

- `,bot version`
- `,version`

### audit

Source: `core`
Category: `core`

Admin audit log viewer

#### `,audit action`

Show recent audit events for one action/event type.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit action <event_type>`

Aliases: `,audit event`, `,audits action`, `,audits event`

Examples:

- `,audit action room_feature_changed`

#### `,audit last`

Show recent admin audit events.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit last [all|page|last|limit]`

Aliases: `,audit`, `,audits last`

Examples:

- `,audit last`
- `,audit last 2`

#### `,audit target`

Show recent audit events for one target value.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit target <target>`

Aliases: `,audit room`, `,audits room`, `,audits target`

Examples:

- `,audit target room@conference.example.org`

#### `,audit user`

Show recent audit events for one actor JID.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit user <jid>`

Aliases: `,audits user`

Examples:

- `,audit user admin@example.org`

### backups

Source: `core`
Category: `core`

Managed ZIP backups and restore helpers.

#### `,backup create`

Create a managed ZIP backup archive.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,backup create [reason]`

Aliases: `,backup`

Examples:

- `,backup create`
- `,backup create before config change`
- `,backup`

#### `,backup list`

List managed backup archives.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,backup list [all|page|last]`

Aliases: `,backup ls`, `,backups`

Examples:

- `,backup list`
- `,backup list all`

#### `,backup prune`

Prune managed backup archives, with optional dry-run.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,backup prune [dry-run] [keep <n>] [days <n>]`

Examples:

- `,backup prune dry-run`
- `,backup prune keep 20 days 30`

#### `,backup show`

Show manifest details for one managed backup archive.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,backup show <archive|last>`

Examples:

- `,backup show last`

#### `,restore`

Restore a managed backup after explicit confirmation.

Role: `owner`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,restore <archive|last> confirm`

Aliases: `,backup restore`

Examples:

- `,restore last confirm`

### config_cmd

Source: `core`
Category: `core`

Safe config inspection, validation and reload commands.

#### `,config diff`

Show config values that differ from config_sample.py defaults.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config diff [all|page|last]`

Examples:

- `,config diff`
- `,config diff all`

#### `,config reload`

Reload config.py into the running bot where possible.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config reload`

Examples:

- `,config reload`

#### `,config show`

Show the effective config grouped like config_sample.py, with secrets redacted.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config show [all|page|last]`

Aliases: `,config`

Examples:

- `,config show`
- `,config show all`

#### `,config validate`

Validate the current config.py file.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config validate`

Examples:

- `,config validate`

### doctor

Source: `core`
Category: `core`

Operator health checks and runtime diagnostics.

#### `,doctor`

Run operator health checks for config, DB, rooms, plugins, tasks and backups.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,doctor [full] [all|page|last]`

Aliases: `,bot doctor`, `,bot health`, `,healthcheck`

Examples:

- `,doctor`
- `,doctor full`

### help

Source: `core`
Category: `core`

Dynamic help for plugins and commands.

#### `,help`

Show help for plugins and commands.

Role: `none`<br>
Context: `any`<br>
Category: `core`<br>
Usage: `,help [all|commands|plugins|roles|categories|category <name>|room settings|<plugin>|,<command>]`

Aliases: `,h`

Examples:

- `,help`
- `,help room settings`
- `,help rooms settings`
- `,help ducks`
- `,help rooms enable`
- `,help ,users role`
- `,help category admin`

#### `,help inroom`

Enable, disable or show room help availability.

Role: `user`<br>
Context: `room or MUC PM`<br>
Category: `core`<br>
Usage: `,help inroom <on|off|status>`

Aliases: `,h inroom`

Examples:

- `,help inroom on`
- `,help inroom status`

### plugins

Source: `core`
Category: `core`

Runtime plugin management

#### `,plugin diagnose`

Show diagnostics for one plugin, including hooks, commands and tasks.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,plugin diagnose <plugin>`

Aliases: `,plugins diagnose`

Examples:

- `,plugin diagnose rss`

#### `,plugin info`

Show metadata and source information for one plugin.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `core`<br>
Usage: `,plugin info <plugin>`

Aliases: `,plugins info`

Examples:

- `,plugin info rooms`

#### `,plugin list`

List loaded and available core/optional plugins.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `core`<br>
Usage: `,plugins [all|page|last]`

Aliases: `,plugins`, `,plugins list`

Examples:

- `,plugins`
- `,plugins all`
- `,plugins list`

#### `,plugin load`

Load one plugin or all plugins.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `core`<br>
Usage: `,plugin load <plugin|all>`

Aliases: `,plugins load`

Examples:

- `,plugin load weather`

#### `,plugin reload`

Reload one plugin or all plugins.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `core`<br>
Usage: `,plugin reload <plugin|all> [auto]`

Aliases: `,plugins reload`

Examples:

- `,plugin reload help`
- `,plugin reload all auto`

#### `,plugin state`

Show plugin-provided runtime state counters.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,plugin state <plugin> [room_jid]`

Aliases: `,plugins state`

Examples:

- `,plugin state rss`
- `,plugin state poll room@conference.example.org`

#### `,plugin unload`

Unload one optional plugin; core plugins are protected.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `core`<br>
Usage: `,plugin unload <plugin> [force]`

Aliases: `,plugins unload`

Examples:

- `,plugin unload weather`

### presence

Source: `core`
Category: `info`

Bot presence and status management

#### `,presence`

Show or control per-room access to presence lookup.

Role: `none`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,presence [on|off|status]`

Examples:

- `,presence`
- `,presence status`

#### `,presence set`

Set the bot presence state and status text.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `info`<br>
Usage: `,presence set <online|chat|away|xa|dnd> [message]`

Examples:

- `,presence set away maintenance`

### rooms

Source: `core`
Category: `core`

Database-backed room management

#### `,rooms add`

Add or update a stored room configuration.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms add <room_jid> [nick] [autojoin]`

Aliases: `,room add`

Examples:

- `,rooms add test@conference.example.org EnvsBot true`

#### `,rooms delete`

Remove a stored room and leave it if currently joined.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms delete <room_jid>`

Aliases: `,room delete`

Examples:

- `,rooms delete test@conference.example.org`

#### `,rooms diagnose`

Show operational diagnostics for one room.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms diagnose <room_jid>`

Aliases: `,room debug`, `,room diagnose`, `,rooms debug`

Examples:

- `,rooms diagnose room@conference.example.org`

#### `,rooms disable`

Disable a room plugin toggle; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms disable [<room_jid>] <plugin>`

Aliases: `,room disable`, `,room feature disable`, `,rooms feature disable`

Examples:

- `,rooms disable ducks`
- `,rooms disable room@conference.example.org ducks`
- `,rooms disable xkcd`

#### `,rooms enable`

Enable a room plugin toggle; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms enable [<room_jid>] <plugin>`

Aliases: `,room enable`, `,room feature enable`, `,rooms feature enable`

Examples:

- `,rooms enable ducks`
- `,rooms enable room@conference.example.org ducks`
- `,rooms enable weather`
- `,help room settings`

#### `,rooms invite`

List, accept, decline or clean up pending room invites.

Role: `admin`<br>
Context: `private chat / MUC PM / invite notify room`<br>
Category: `rooms`<br>
Usage: `,rooms invite list [all|page|last] | ,rooms invite accept <id> | ,rooms invite decline <id> | ,rooms invite cleanup [all|expired]`

Aliases: `,room invite`

Examples:

- `,rooms invite list`
- `,rooms invite list all`
- `,rooms invite accept 1`
- `,rooms invite decline 1`
- `,rooms invite cleanup`
- `,rooms invite cleanup all`
- `,rooms invite cleanup expired`

#### `,rooms join`

Join a room immediately and store it if needed.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms join <room_jid> [nick]`

Aliases: `,room join`

Examples:

- `,rooms join test@conference.example.org`

#### `,rooms leave`

Leave a room without deleting its stored configuration.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms leave <room_jid>`

Aliases: `,room leave`

Examples:

- `,rooms leave test@conference.example.org`

#### `,rooms list`

List stored rooms and currently joined rooms.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms list [all|page|last]`

Aliases: `,room list`

Examples:

- `,rooms list`
- `,rooms list all`

#### `,rooms plugins`

Show room plugin toggles; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms plugins [<room_jid>] [all|page|last]`

Aliases: `,room feature list`, `,room features`, `,room features list`, `,room plugins`, `,room plugins list`, `,rooms feature list`, `,rooms features`, `,rooms features list`, `,rooms plugins list`

Examples:

- `,rooms plugins`
- `,rooms plugins all`
- `,rooms plugins room@conference.example.org all`
- `,help room settings`
- `,help rooms settings`

#### `,rooms set_plugin_defaults`

Restore room plugin toggles for a room; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms set_plugin_defaults [<room_jid>]`

Aliases: `,room set_plugin_defaults`, `,room spd`, `,rooms spd`

Examples:

- `,rooms set_plugin_defaults`
- `,rooms spd`
- `,rooms set_plugin_defaults room@conference.example.org`

#### `,rooms sync`

Synchronize joined rooms with stored autojoin settings.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms sync`

Aliases: `,room sync`

Examples:

- `,rooms sync`

#### `,rooms update`

Update one field of a stored room.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms update <room_jid> <nick|autojoin|status> <value>`

Aliases: `,room update`

Examples:

- `,rooms update test@conference.example.org autojoin true`

### tasks

Source: `core`
Category: `core`

Inspect supervised background tasks.

#### `,tasks`

Show supervised background task status.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,tasks [full] [plugin <name>] [running|failed|cancelled|done] [all|page|last] | ,tasks restart <plugin>`

Aliases: `,bot tasks`

Examples:

- `,tasks`
- `,tasks full`
- `,tasks plugin rss`
- `,tasks failed`
- `,tasks restart rss`

### users

Source: `core`
Category: `core`

User management with caching, nick lookup and logging

#### `,users admins`

List users with admin-level roles.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users admins [all|page|last]`

Aliases: `,user admin`, `,user admins`, `,users admin`

Examples:

- `,users admins`

#### `,users delete`

Delete one non-privileged user record and its runtime data.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users delete <jid>`

Aliases: `,user delete`

Examples:

- `,users delete alice@example.org`

#### `,users grant`

Grant room-scoped plugin permissions to a user.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users grant <jid> <plugin> [plugin ...]`

Aliases: `,user grant`, `,user plugin grant`, `,users plugin grant`

Examples:

- `,users grant alice@example.org rss pin poll`

#### `,users grants`

Show a user's room-scoped plugin permissions.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users grants <jid>`

Aliases: `,user grants`, `,user plugin grants`, `,users plugin grants`

Examples:

- `,users grants alice@example.org`

#### `,users info`

Show user info by JID or known nickname.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users info <jid|nick>`

Aliases: `,user info`

Examples:

- `,users info alice@example.org`

#### `,users list`

List users currently known in one joined room.

Role: `admin`<br>
Context: `private chat only`<br>
Category: `users`<br>
Usage: `,users list [room_jid]`

Aliases: `,user list`

Examples:

- `,users list test@conference.example.org`

#### `,users permissions`

Diagnose global, room and room-scoped plugin permissions.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users permissions <jid|nick> [room_jid]`

Aliases: `,user permissions`, `,user perms`, `,users perms`

Examples:

- `,users permissions alice@example.org`
- `,users permissions alice@example.org room@conference.example.org`
- `,users perms alice room@conference.example.org`

#### `,users revoke`

Revoke room-scoped plugin permissions from a user.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users revoke <jid> <plugin> [plugin ...]`

Aliases: `,user plugin revoke`, `,user revoke`, `,users plugin revoke`

Examples:

- `,users revoke alice@example.org rss`

#### `,users role`

Change a user's global bot role with hierarchy checks.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users role <jid> <role>`

Aliases: `,user role`

Examples:

- `,users role alice@example.org trusted`

#### `,users roles`

Show available roles and their ordering.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users roles`

Aliases: `,user roles`

Examples:

- `,users roles`

### birthday_notify

Source: `plugins`
Category: `fun`

Automatic birthday notifications in rooms (opt-in per room)

#### `,birthday_notify`

Enable, disable or show birthday notifications for a room.

Role: `user`<br>
Context: `room or MUC PM`<br>
Category: `rooms`<br>
Usage: `,birthday_notify <on|off|status>`

Examples:

- `,birthday_notify status`

### dice

Source: `plugins`
Category: `games`

Roll dice with optional modifiers and success conditions.

#### `,dice`

Roll dice using common dice notation.

Role: `user`<br>
Context: `any`<br>
Category: `fun`<br>
Usage: `,dice <on|off|status|NdM [modifier] [operator] [target]>`

Aliases: `,r`, `,roll`

Examples:

- `,dice status`
- `,dice 2d6`
- `,rooms enable dice`

### ducks

Source: `plugins`
Category: `fun`

Duck game for MUCs with room toggles and leaderboards

#### `,bef`

Befriend the current duck.

Role: `user`<br>
Context: `any`<br>
Category: `fun`<br>
Usage: `,bef`

Examples:

- `,bef`

#### `,duck`

Start or interact with the duck game.

Role: `user`<br>
Context: `room / MUC PM; use rooms enable with <room_jid> from private chat`<br>
Category: `fun`<br>
Usage: `,duck <on|off|status|befriend|trap|friends|top|enemies|stats [jid|nickname]>`

Examples:

- `,duck status`
- `,duck on`
- `,duck befriend`
- `,duck stats`
- `,rooms enable ducks`
- `,rooms enable room@conference.example.org ducks`

#### `,duckstats`

Show duck game stats.

Role: `user`<br>
Context: `any`<br>
Category: `fun`<br>
Usage: `,duckstats [nick]`

Examples:

- `,duckstats`

#### `,trap`

Set a trap in the duck game.

Role: `user`<br>
Context: `any`<br>
Category: `fun`<br>
Usage: `,trap`

Examples:

- `,trap`

### idlerpg

Source: `plugins`
Category: `fun`

IdleRPG game for MUCs, inspired by the classic IRC game

#### `,idlerpg`

Play IdleRPG in a MUC

Role: `user`<br>
Context: `groupchat / MUC PM`<br>
Category: `fun`<br>
Usage: `,idlerpg <on|off|enabled|register|status|top|players|profile|events|achievements|balance|map|season|...>`

Aliases: `,idle`, `,irpg`

Examples:

- `,idlerpg register Sven sysadmin`
- `,idlerpg enabled`
- `,idlerpg status`
- `,idlerpg top`
- `,idlerpg quest`
- `,idlerpg map`
- `,idlerpg profile Sven`
- `,idlerpg events`
- `,idlerpg achievements list`
- `,idlerpg balance`

### info

Source: `plugins`
Category: `info`

Wikipedia, Fediverse, Urban Dictionary and acronym lookup.

#### `,acronyms`

Look up stored acronym definitions.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms <acronym>`

Aliases: `,acro`, `,acronym`

Examples:

- `,acro XMPP`

#### `,acronyms add`

Suggest a new acronym definition for admin review.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms add <acronym> <description>`

Aliases: `,acro add`, `,acronym add`

Examples:

- `,acro add XMPP Extensible Messaging and Presence Protocol`

#### `,acronyms delete`

Delete pending acronym suggestions by nick or definition.

Role: `admin`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms delete <nick|acronym description>`

Aliases: `,acro delete`, `,acronym delete`

Examples:

- `,acro delete Alice`
- `,acro delete XMPP old definition`

#### `,acronyms list`

List pending acronym additions and removals.

Role: `admin`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms list`

Aliases: `,acro list`, `,acronym list`

Examples:

- `,acro list`

#### `,acronyms merge`

Apply pending acronym additions and removals.

Role: `admin`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms merge`

Aliases: `,acro merge`, `,acronym merge`

Examples:

- `,acro merge`

#### `,acronyms remove`

Suggest removing one acronym definition for admin review.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms remove <acronym> <description>`

Aliases: `,acro remove`, `,acronym remove`

Examples:

- `,acro remove XMPP old definition`

#### `,fediverse`

Show the latest public post from a Fediverse account.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,fediverse <@user@instance>`

Aliases: `,fedi`

Examples:

- `,fedi @user@example.org`

#### `,info`

Enable, disable or show room access to information commands.

Role: `moderator`<br>
Context: `room or MUC PM`<br>
Category: `info`<br>
Usage: `,info <on|off|status>`

Examples:

- `,info status`

#### `,udict`

Search Urban Dictionary.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,udict <term>`

Aliases: `,ud`

Examples:

- `,ud xmpp`

#### `,wikipedia`

Search Wikipedia.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,wikipedia <term>`

Aliases: `,wiki`

Examples:

- `,wiki XMPP`

### karma

Source: `plugins`
Category: `fun`

Room-local karma tracking with nick++ / nick--

#### `,karma`

Show room-local karma scores and rankings.

Role: `user`<br>
Context: `any`<br>
Category: `fun`<br>
Usage: `,karma <on|off|status|top|bottom|nick>`

Examples:

- `,karma status`
- `,karma top`
- `,karma xmpp`

### pin

Source: `plugins`
Category: `utility`

Pin room messages with paging and non-reply fallback.

#### `,pin`

Pin, list or delete room pins.

Role: `user`<br>
Context: `any`<br>
Category: `rooms`<br>
Usage: `,pin <add|list|show|delete|on|off|status> ...`

Examples:

- `,pin status`
- `,pin list`
- `,rooms enable pin`

### poll

Source: `plugins`
Category: `utility`

Room polls with voting, history and auto-close

#### `,poll`

Create and manage polls.

Role: `user`<br>
Context: `any`<br>
Category: `rooms`<br>
Usage: `,poll <on|off|status|create|list|show|result|history|vote|close|cancel|delete> ...`

Examples:

- `,poll status`
- `,poll create Tea? | yes | no`
- `,poll list`
- `,rooms enable poll`

### reminder

Source: `plugins`
Category: `utility`

Schedule and manage reminders

#### `,remind`

Create a reminder.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,remind <on|off|status|when> [text]`

Aliases: `,rem`, `,reminder`

Examples:

- `,remind status`
- `,remind 10m check logs`
- `,rooms enable reminder`

#### `,remind delete`

Delete one reminder.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,remind delete <id>`

Aliases: `,remind cancel`, `,remind rm`

Examples:

- `,remind delete 12`

#### `,reminders`

List your reminders.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,reminders [all|page|last]`

Aliases: `,remind list`, `,rems`

Examples:

- `,reminders`

### rss

Source: `plugins`
Category: `info`

RSS/Atom feed watcher and poster

#### `,rss`

Manage RSS feed subscriptions for rooms.

Role: `user`<br>
Context: `any`<br>
Category: `rooms`<br>
Usage: `,rss <add|delete|remove|del|rm|retry|reset|list> ...`

Examples:

- `,rss add https://example.org/feed.rss room@conference.example.org`
- `,rss list room@conference.example.org`
- `,rss list 2`
- `,rss list all`
- `,rss retry all`
- `,rss reset all`
- `,rss retry https://example.org/feed.rss room@conference.example.org`
- `,rss delete https://example.org/feed.rss`
- `,rss remove https://example.org/feed.rss old@conference.example.org`

### sed

Source: `plugins`
Category: `tools`

Message correction using sed-like syntax

#### `,sed`

Apply sed-style corrections or control room access to sed.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,s/old/new/ or ,sed <on|off|status>`

Examples:

- `,s/teh/the/`
- `,sed status`
- `,rooms enable sed`

### tell

Source: `plugins`
Category: `utility`

Store and deliver messages for users when they join a room again.

#### `,tell`

Leave a message for another user.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,tell <on|off|status|nick: message>`

Examples:

- `,tell status`
- `,tell alice: I fixed it`

### tools

Source: `plugins`
Category: `utility`

Utility commands: ping/pong, message echo, timezone-aware time/date lookups, and Unix timestamp conversion

#### `,date`

Show the current date from a stored profile timezone.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,date [nick]`

Examples:

- `,date`
- `,date Alice`

#### `,echo`

Echo text back to you.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,echo <text>`

Examples:

- `,echo hello`

#### `,ping`

Check whether the bot is alive.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,ping`

Aliases: `,pong`

Examples:

- `,ping`

#### `,seen`

Show when a user was last seen.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,seen <nick|jid>`

Aliases: `,s`

Examples:

- `,seen alice`

#### `,time`

Show the current time from a stored profile timezone.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,time [nick]`

Aliases: `,t`

Examples:

- `,time`
- `,time Alice`

#### `,tools`

Enable, disable or show room access to utility commands.

Role: `moderator`<br>
Context: `room or MUC PM`<br>
Category: `utility`<br>
Usage: `,tools <on|off|status>`

Examples:

- `,tools status`

#### `,ts`

Convert a Unix timestamp to your configured timezone.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,ts <unix_timestamp>`

Examples:

- `,ts 1704067200`

#### `,utc`

Show current UTC time.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,utc`

Examples:

- `,utc`

### urlcheck

Source: `plugins`
Category: `info`

URL title and YouTube info fetcher for groupchats

#### `,urlcheck`

Enable, disable or show automatic URL checks in a room.

Role: `user`<br>
Context: `room or MUC PM`<br>
Category: `utility`<br>
Usage: `,urlcheck <on|off|status>`

Examples:

- `,urlcheck status`
- `,rooms enable urlcheck`

### vcard

Source: `plugins`
Category: `info`

Lookup and display vCard of a MUC occupant by MUC JID only

#### `,birthday`

Show birthday data from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,birthday [nick]`

Aliases: `,b`

Examples:

- `,birthday Alice`

#### `,emails`

Show email addresses from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,emails [nick]`

Aliases: `,e`

Examples:

- `,emails Alice`

#### `,fullname`

Show the full name from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,fullname [nick]`

Aliases: `,f`

Examples:

- `,fullname Alice`

#### `,nicknames`

Show nicknames from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,nicknames [nick]`

Aliases: `,nicks`

Examples:

- `,nicks Alice`

#### `,notes`

Show notes from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,notes [nick]`

Examples:

- `,notes Alice`

#### `,organisations`

Show organisations from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,organisations [nick]`

Aliases: `,orgs`

Examples:

- `,orgs Alice`

#### `,timezone`

Show your configured timezone.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,timezone`

Aliases: `,tz`

Examples:

- `,tz`

#### `,timezone set`

Set your timezone in the bot profile.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,timezone set <IANA timezone>`

Aliases: `,tz set`

Examples:

- `,tz set Europe/Berlin`

#### `,urls`

Show URLs from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,urls [nick]`

Aliases: `,u`

Examples:

- `,urls Alice`

#### `,vcard`

Show vCard data or control room access to vCard lookups.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,vcard [on|off|status|nick]`

Aliases: `,v`

Examples:

- `,vcard`
- `,vcard status`
- `,rooms enable vcard`

### weather

Source: `plugins`
Category: `info`

Gives weather according to users location or an explicit city/ZIP code

#### `,weather`

Show weather from a user's vCard location, a room nick, or an explicit city/ZIP code.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,weather [on|off|status|nick|city|zip]`

Aliases: `,w`

Examples:

- `,weather status`
- `,weather Alice`
- `,w Dresden`
- `,w 01067`
- `,rooms enable weather`

### xkcd

Source: `plugins`
Category: `fun`

XKCD comic fetcher and broadcaster with full indexing

#### `,xkcd`

Show an XKCD comic or control room access to XKCD.

Role: `user`<br>
Context: `any`<br>
Category: `fun`<br>
Usage: `,xkcd [on|off|status|random|number|search <term> [page]]`

Examples:

- `,xkcd`
- `,xkcd random`
- `,xkcd search python 2`
- `,rooms enable xkcd`

### xmpp

Source: `plugins`
Category: `tools`

XMPP utility tools (ping, diagnostics, service discovery, DNS SRV, etc.)

#### `,xmpp`

Enable, disable or show room access to XMPP lookup commands.

Role: `user`<br>
Context: `room or MUC PM`<br>
Category: `xmpp`<br>
Usage: `,xmpp <on|off|status>`

Aliases: `,x`

Examples:

- `,xmpp status`

#### `,xmpp compliance`

Check XMPP compliance features via disco.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp compliance <jid>`

Aliases: `,x compliance`

Examples:

- `,x compliance envs.net`

#### `,xmpp contact`

Show contact addresses from service discovery.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp contact <jid>`

Aliases: `,x contact`

Examples:

- `,x contact envs.net`

#### `,xmpp help`

Show help for XMPP lookup subcommands.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp help`

Aliases: `,x help`

Examples:

- `,x help`

#### `,xmpp info`

Show service discovery identity/features.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp info <jid>`

Aliases: `,x info`

Examples:

- `,x info conference.envs.net`

#### `,xmpp items`

List service discovery items.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp items <jid>`

Aliases: `,x items`

Examples:

- `,x items envs.net`

#### `,xmpp ping`

Ping an XMPP entity.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp ping <jid>`

Aliases: `,x ping`

Examples:

- `,x ping envs.net`

#### `,xmpp srv`

Look up XMPP DNS SRV records.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp srv <domain>`

Aliases: `,x srv`

Examples:

- `,x srv envs.net`

#### `,xmpp uptime`

Query XMPP entity uptime.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp uptime <jid>`

Aliases: `,x uptime`

Examples:

- `,x uptime envs.net`

#### `,xmpp version`

Query XMPP software version via XEP-0092.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp version <jid>`

Aliases: `,x version`

Examples:

- `,x version envs.net`
