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

`birthday_notify`, `dice`, `ducks`, `help`, `idlerpg`, `information`, `karma`, `pin`, `poll`, `presence`, `reminder`, `sed`, `tell`, `tools`, `translate`, `urlcheck`, `vcard`, `weather`, `xkcd`, `xmpp`

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

| Plugin | Source | Category | Description | Detailed docs |
| --- | --- | --- | --- | --- |
| `_admin` | `core` | `core` | Bot administration commands | [`docs/plugins/_admin.md`](plugins/_admin.md) |
| `audit` | `core` | `core` | Admin audit log viewer | [`docs/plugins/audit.md`](plugins/audit.md) |
| `backups` | `core` | `core` | Managed ZIP backups and restore helpers. | [`docs/plugins/backups.md`](plugins/backups.md) |
| `config_cmd` | `core` | `core` | Safe config inspection, validation and reload commands. | [`docs/plugins/config_cmd.md`](plugins/config_cmd.md) |
| `doctor` | `core` | `core` | Operator health checks and runtime diagnostics. | [`docs/plugins/doctor.md`](plugins/doctor.md) |
| `help` | `core` | `core` | Dynamic help for plugins and commands. | [`docs/plugins/help.md`](plugins/help.md) |
| `plugins` | `core` | `core` | Runtime plugin management | [`docs/plugins/plugins.md`](plugins/plugins.md) |
| `presence` | `core` | `info` | Bot presence and status management | [`docs/plugins/presence.md`](plugins/presence.md) |
| `rooms` | `core` | `core` | Database-backed room management | [`docs/plugins/rooms.md`](plugins/rooms.md) |
| `tasks` | `core` | `core` | Inspect supervised background tasks. | [`docs/plugins/tasks.md`](plugins/tasks.md) |
| `users` | `core` | `core` | User management with caching, nick lookup and logging | [`docs/plugins/users.md`](plugins/users.md) |
| `birthday_notify` | `plugins` | `info` | Automatic birthday notifications in rooms (opt-in per room) | [`docs/plugins/birthday_notify.md`](plugins/birthday_notify.md) |
| `dice` | `plugins` | `games` | Roll dice with optional modifiers and success conditions. | [`docs/plugins/dice.md`](plugins/dice.md) |
| `ducks` | `plugins` | `games` | Duck game for MUCs with room toggles and leaderboards | [`docs/plugins/ducks.md`](plugins/ducks.md) |
| `idlerpg` | `plugins` | `games` | IdleRPG game for MUCs, inspired by the classic IRC game | [`docs/plugins/idlerpg.md`](plugins/idlerpg.md) |
| `info` | `plugins` | `info` | Wikipedia, Fediverse, Urban Dictionary and acronym lookup. | [`docs/plugins/info.md`](plugins/info.md) |
| `karma` | `plugins` | `fun` | Room-local karma tracking with nick++ / nick-- | [`docs/plugins/karma.md`](plugins/karma.md) |
| `pin` | `plugins` | `utility` | Pin room messages with paging, search, tags, important pins and non-reply fallback. | [`docs/plugins/pin.md`](plugins/pin.md) |
| `poll` | `plugins` | `utility` | Room polls with voting, history and auto-close | [`docs/plugins/poll.md`](plugins/poll.md) |
| `reminder` | `plugins` | `utility` | Schedule and manage reminders | [`docs/plugins/reminder.md`](plugins/reminder.md) |
| `rss` | `plugins` | `info` | RSS/Atom feed watcher and poster | [`docs/plugins/rss.md`](plugins/rss.md) |
| `sed` | `plugins` | `tools` | Message correction using sed-like syntax | [`docs/plugins/sed.md`](plugins/sed.md) |
| `tell` | `plugins` | `utility` | Store and deliver messages for users when they join a room again. | [`docs/plugins/tell.md`](plugins/tell.md) |
| `tools` | `plugins` | `utility` | Utility commands: ping/pong, message echo, timezone-aware time/date lookups, and Unix timestamp conversion | [`docs/plugins/tools.md`](plugins/tools.md) |
| `translate` | `plugins` | `utility` | Translate text or replied-to messages with optional source-language auto-detection. | [`docs/plugins/translate.md`](plugins/translate.md) |
| `urlcheck` | `plugins` | `info` | URL title and YouTube info fetcher for groupchats | [`docs/plugins/urlcheck.md`](plugins/urlcheck.md) |
| `vcard` | `plugins` | `info` | Lookup and display vCard of a MUC occupant by MUC JID only | [`docs/plugins/vcard.md`](plugins/vcard.md) |
| `weather` | `plugins` | `info` | Gives weather according to users location or an explicit city/ZIP code | [`docs/plugins/weather.md`](plugins/weather.md) |
| `xkcd` | `plugins` | `fun` | XKCD comic fetcher and broadcaster with full indexing | [`docs/plugins/xkcd.md`](plugins/xkcd.md) |
| `xmpp` | `plugins` | `tools` | XMPP utility tools (ping, diagnostics, service discovery, DNS SRV, etc.) | [`docs/plugins/xmpp.md`](plugins/xmpp.md) |

## Commands by category

### Admin

| Command | Plugin | Role | Context | Description |
| --- | --- | --- | --- | --- |
| `,audit action` | [`audit`](plugins/audit.md) | `admin` | `private recommended` | Show recent audit events for one action/event type. |
| `,audit errors` | [`audit`](plugins/audit.md) | `admin` | `private recommended` | Show audit events that look like errors or failures. |
| `,audit export` | [`audit`](plugins/audit.md) | `admin` | `private recommended` | Export recent audit events as JSON Lines. |
| `,audit last` | [`audit`](plugins/audit.md) | `admin` | `private recommended` | Show recent admin audit events. |
| `,audit prune` | [`audit`](plugins/audit.md) | `owner` | `private recommended` | Prune old audit events after confirmation. |
| `,audit summary` | [`audit`](plugins/audit.md) | `admin` | `private recommended` | Summarize audit activity for the last 24h or 7d. |
| `,audit target` | [`audit`](plugins/audit.md) | `admin` | `private recommended` | Show recent audit events for one target value. |
| `,audit user` | [`audit`](plugins/audit.md) | `admin` | `private recommended` | Show recent audit events for one actor JID. |
| `,backup create` | [`backups`](plugins/backups.md) | `admin` | `private chat / MUC PM` | Create a managed ZIP backup archive. |
| `,backup list` | [`backups`](plugins/backups.md) | `admin` | `private chat / MUC PM` | List managed backup archives. |
| `,backup prune` | [`backups`](plugins/backups.md) | `admin` | `private chat / MUC PM` | Prune managed backup archives, with optional dry-run. |
| `,backup restore-plan` | [`backups`](plugins/backups.md) | `owner` | `private recommended` | Show what a restore would overwrite without writing files. |
| `,backup show` | [`backups`](plugins/backups.md) | `admin` | `private chat / MUC PM` | Show manifest details for one managed backup archive. |
| `,backup verify` | [`backups`](plugins/backups.md) | `admin` | `private recommended` | Verify one managed backup archive. |
| `,bot checkupdate` | [`_admin`](plugins/_admin.md) | `admin` | `private chat / MUC PM` | Check whether a newer EnvsBot release is available. |
| `,bot restart` | [`_admin`](plugins/_admin.md) | `owner` | `private chat / MUC PM` | Restart the bot process gracefully. |
| `,bot shutdown` | [`_admin`](plugins/_admin.md) | `owner` | `private chat / MUC PM` | Stop the bot using the configured stop command. |
| `,bot status` | [`_admin`](plugins/_admin.md) | `admin` | `private chat / MUC PM` | Show bot, runtime, XMPP, plugin and database status. |
| `,config diff` | [`config_cmd`](plugins/config_cmd.md) | `admin` | `private chat / MUC PM` | Show config values that differ from config_sample.py defaults. |
| `,config reload` | [`config_cmd`](plugins/config_cmd.md) | `admin` | `private chat / MUC PM` | Reload config.py into the running bot where possible. |
| `,config search` | [`config_cmd`](plugins/config_cmd.md) | `admin` | `private chat / MUC PM` | Search visible config keys and values. |
| `,config set` | [`config_cmd`](plugins/config_cmd.md) | `admin` | `private chat / MUC PM` | Persist and apply one runtime-writable config value. |
| `,config show` | [`config_cmd`](plugins/config_cmd.md) | `admin` | `private chat / MUC PM` | Show the effective config grouped like config_sample.py, with secrets redacted. |
| `,config unset` | [`config_cmd`](plugins/config_cmd.md) | `admin` | `private chat / MUC PM` | Reset one runtime-writable config value to the config_sample.py default. |
| `,config validate` | [`config_cmd`](plugins/config_cmd.md) | `admin` | `private chat / MUC PM` | Validate the current config.py file. |
| `,doctor` | [`doctor`](plugins/doctor.md) | `admin` | `private chat / MUC PM` | Run operator health checks for config, DB, rooms, plugins, tasks, backups, network and release readiness. |
| `,doctor failed` | [`doctor`](plugins/doctor.md) | `admin` | `private chat / MUC PM` | Show only failed doctor checks. |
| `,doctor release` | [`doctor`](plugins/doctor.md) | `admin` | `private chat / MUC PM` | Run release-readiness checks for version, docs, config, syntax, DB, backups, tasks and plugin metadata. |
| `,doctor warnings` | [`doctor`](plugins/doctor.md) | `admin` | `private chat / MUC PM` | Show only doctor warning lines. |
| `,plugin diagnose` | [`plugins`](plugins/plugins.md) | `admin` | `private chat / MUC PM` | Show diagnostics for one plugin, including hooks, commands and tasks. |
| `,plugin state` | [`plugins`](plugins/plugins.md) | `admin` | `private chat / MUC PM` | Show plugin-provided runtime state counters. |
| `,restore` | [`backups`](plugins/backups.md) | `owner` | `private chat / MUC PM` | Restore a managed backup after explicit confirmation. |
| `,tasks` | [`tasks`](plugins/tasks.md) | `admin` | `private chat / MUC PM` | Show supervised background task status. |
| `,tasks failed` | [`tasks`](plugins/tasks.md) | `admin` | `private recommended` | Show failed supervised background tasks. |
| `,tasks list` | [`tasks`](plugins/tasks.md) | `admin` | `private recommended` | Show supervised background tasks. |
| `,tasks stale` | [`tasks`](plugins/tasks.md) | `admin` | `private recommended` | Show supervised tasks with stale heartbeats. |

### Core

| Command | Plugin | Role | Context | Description |
| --- | --- | --- | --- | --- |
| `,bot version` | [`_admin`](plugins/_admin.md) | `user` | `any` | Show the running EnvsBot version and latest checked release. |
| `,help` | [`help`](plugins/help.md) | `none` | `any` | Show help for plugins and commands. |
| `,help inroom` | [`help`](plugins/help.md) | `user` | `room or MUC PM` | Enable, disable or show room help availability. |
| `,plugin info` | [`plugins`](plugins/plugins.md) | `admin` | `private chat / MUC PM` | Show metadata and source information for one plugin. |
| `,plugin list` | [`plugins`](plugins/plugins.md) | `admin` | `private chat / MUC PM` | List loaded and available core/optional plugins. |
| `,plugin load` | [`plugins`](plugins/plugins.md) | `admin` | `private chat / MUC PM` | Load one plugin or all plugins. |
| `,plugin reload` | [`plugins`](plugins/plugins.md) | `admin` | `private chat / MUC PM` | Reload one plugin or all plugins. |
| `,plugin unload` | [`plugins`](plugins/plugins.md) | `admin` | `private chat / MUC PM` | Unload one optional plugin; core plugins are protected. |

### Fun

| Command | Plugin | Role | Context | Description |
| --- | --- | --- | --- | --- |
| `,bef` | [`ducks`](plugins/ducks.md) | `user` | `any` | Befriend the current duck. |
| `,dice` | [`dice`](plugins/dice.md) | `user` | `any` | Roll dice using common dice notation. |
| `,duck` | [`ducks`](plugins/ducks.md) | `user` | `room / MUC PM; use rooms enable with <room_jid> from private chat` | Start or interact with the duck game. |
| `,duckstats` | [`ducks`](plugins/ducks.md) | `user` | `any` | Show duck game stats. |
| `,idlerpg` | [`idlerpg`](plugins/idlerpg.md) | `user` | `groupchat / MUC PM` | Play IdleRPG in a MUC |
| `,karma` | [`karma`](plugins/karma.md) | `user` | `any` | Show room-local karma scores and rankings. |
| `,trap` | [`ducks`](plugins/ducks.md) | `user` | `any` | Set a trap in the duck game. |
| `,xkcd` | [`xkcd`](plugins/xkcd.md) | `user` | `any` | Show an XKCD comic or control room access to XKCD. |

### Info

| Command | Plugin | Role | Context | Description |
| --- | --- | --- | --- | --- |
| `,acronyms` | [`info`](plugins/info.md) | `user` | `any` | Look up stored acronym definitions. |
| `,acronyms add` | [`info`](plugins/info.md) | `user` | `any` | Suggest a new acronym definition for admin review. |
| `,acronyms delete` | [`info`](plugins/info.md) | `admin` | `any` | Delete pending acronym suggestions by nick or definition. |
| `,acronyms list` | [`info`](plugins/info.md) | `admin` | `any` | List pending acronym additions and removals. |
| `,acronyms merge` | [`info`](plugins/info.md) | `admin` | `any` | Apply pending acronym additions and removals. |
| `,acronyms remove` | [`info`](plugins/info.md) | `user` | `any` | Suggest removing one acronym definition for admin review. |
| `,fediverse` | [`info`](plugins/info.md) | `user` | `any` | Show the latest public post from a Fediverse account. |
| `,info` | [`info`](plugins/info.md) | `moderator` | `room or MUC PM` | Enable, disable or show room access to information commands. |
| `,presence` | [`presence`](plugins/presence.md) | `none` | `any` | Show or control per-room access to presence lookup. |
| `,presence set` | [`presence`](plugins/presence.md) | `admin` | `private chat / MUC PM` | Set the bot presence state and status text. |
| `,udict` | [`info`](plugins/info.md) | `user` | `any` | Search Urban Dictionary. |
| `,wikipedia` | [`info`](plugins/info.md) | `user` | `any` | Search Wikipedia. |

### Profile

| Command | Plugin | Role | Context | Description |
| --- | --- | --- | --- | --- |
| `,birthday` | [`vcard`](plugins/vcard.md) | `user` | `any` | Show birthday data from a user's vCard. |
| `,emails` | [`vcard`](plugins/vcard.md) | `user` | `any` | Show email addresses from a user's vCard. |
| `,fullname` | [`vcard`](plugins/vcard.md) | `user` | `any` | Show the full name from a user's vCard. |
| `,nicknames` | [`vcard`](plugins/vcard.md) | `user` | `any` | Show nicknames from a user's vCard. |
| `,notes` | [`vcard`](plugins/vcard.md) | `user` | `any` | Show notes from a user's vCard. |
| `,organisations` | [`vcard`](plugins/vcard.md) | `user` | `any` | Show organisations from a user's vCard. |
| `,timezone` | [`vcard`](plugins/vcard.md) | `user` | `any` | Show your configured timezone. |
| `,timezone set` | [`vcard`](plugins/vcard.md) | `user` | `any` | Set your timezone in the bot profile. |
| `,urls` | [`vcard`](plugins/vcard.md) | `user` | `any` | Show URLs from a user's vCard. |
| `,vcard` | [`vcard`](plugins/vcard.md) | `user` | `any` | Show vCard data or control room access to vCard lookups. |

### Rooms

| Command | Plugin | Role | Context | Description |
| --- | --- | --- | --- | --- |
| `,birthday_notify` | [`birthday_notify`](plugins/birthday_notify.md) | `user` | `room or MUC PM` | Enable, disable or show birthday notifications for a room. |
| `,pin` | [`pin`](plugins/pin.md) | `user` | `any` | Pin, list, search, mark important, edit, tag or delete room pins. |
| `,poll` | [`poll`](plugins/poll.md) | `user` | `any` | Create and manage polls. |
| `,rooms add` | [`rooms`](plugins/rooms.md) | `admin` | `private chat / MUC PM` | Add or update a stored room configuration. |
| `,rooms delete` | [`rooms`](plugins/rooms.md) | `admin` | `private chat / MUC PM` | Remove a stored room and leave it if currently joined. |
| `,rooms diagnose` | [`rooms`](plugins/rooms.md) | `admin` | `private chat / MUC PM` | Show operational diagnostics for one room. |
| `,rooms disable` | [`rooms`](plugins/rooms.md) | `user` | `room / MUC PM / private chat with <room_jid>` | Disable a room plugin toggle; requires room admin/owner or bot moderator. |
| `,rooms enable` | [`rooms`](plugins/rooms.md) | `user` | `room / MUC PM / private chat with <room_jid>` | Enable a room plugin toggle; requires room admin/owner or bot moderator. |
| `,rooms invite` | [`rooms`](plugins/rooms.md) | `admin` | `private chat / MUC PM / invite notify room` | List, accept, decline or clean up pending room invites. |
| `,rooms join` | [`rooms`](plugins/rooms.md) | `admin` | `private chat / MUC PM` | Join a room immediately and store it if needed. |
| `,rooms leave` | [`rooms`](plugins/rooms.md) | `admin` | `private chat / MUC PM` | Leave a room without deleting its stored configuration. |
| `,rooms list` | [`rooms`](plugins/rooms.md) | `admin` | `private chat / MUC PM` | List stored rooms and currently joined rooms. |
| `,rooms plugins` | [`rooms`](plugins/rooms.md) | `user` | `room / MUC PM / private chat with <room_jid>` | Show room plugin toggles; requires room admin/owner or bot moderator. |
| `,rooms set_plugin_defaults` | [`rooms`](plugins/rooms.md) | `user` | `room / MUC PM / private chat with <room_jid>` | Restore room plugin toggles for a room; requires room admin/owner or bot moderator. |
| `,rooms sync` | [`rooms`](plugins/rooms.md) | `admin` | `private chat / MUC PM` | Synchronize joined rooms with stored autojoin settings. |
| `,rooms update` | [`rooms`](plugins/rooms.md) | `admin` | `private chat / MUC PM` | Update one field of a stored room. |
| `,rss` | [`rss`](plugins/rss.md) | `user` | `any` | Manage RSS feed subscriptions for rooms. |

### Users

| Command | Plugin | Role | Context | Description |
| --- | --- | --- | --- | --- |
| `,users admins` | [`users`](plugins/users.md) | `admin` | `private chat / MUC PM` | List users with admin-level roles. |
| `,users delete` | [`users`](plugins/users.md) | `admin` | `private chat / MUC PM` | Delete one non-privileged user record and its runtime data. |
| `,users grant` | [`users`](plugins/users.md) | `admin` | `private chat / MUC PM` | Grant room-scoped plugin permissions to a user. |
| `,users grants` | [`users`](plugins/users.md) | `admin` | `private chat / MUC PM` | Show a user's room-scoped plugin permissions. |
| `,users info` | [`users`](plugins/users.md) | `admin` | `private chat / MUC PM` | Show user info by JID or known nickname. |
| `,users list` | [`users`](plugins/users.md) | `admin` | `private chat only` | List users currently known in one joined room. |
| `,users permissions` | [`users`](plugins/users.md) | `admin` | `private chat / MUC PM` | Diagnose global, room and room-scoped plugin permissions. |
| `,users revoke` | [`users`](plugins/users.md) | `admin` | `private chat / MUC PM` | Revoke room-scoped plugin permissions from a user. |
| `,users role` | [`users`](plugins/users.md) | `admin` | `private chat / MUC PM` | Change a user's global bot role with hierarchy checks. |
| `,users roles` | [`users`](plugins/users.md) | `admin` | `private chat / MUC PM` | Show available roles and their ordering. |

### Utility

| Command | Plugin | Role | Context | Description |
| --- | --- | --- | --- | --- |
| `,date` | [`tools`](plugins/tools.md) | `user` | `any` | Show the current date from a stored profile timezone. |
| `,echo` | [`tools`](plugins/tools.md) | `user` | `any` | Echo text back to you. |
| `,ping` | [`tools`](plugins/tools.md) | `user` | `any` | Check whether the bot is alive. |
| `,remind` | [`reminder`](plugins/reminder.md) | `user` | `any` | Create a reminder. |
| `,remind delete` | [`reminder`](plugins/reminder.md) | `user` | `any` | Delete one reminder. |
| `,remind off` | [`reminder`](plugins/reminder.md) | `user` | `room, MUC PM or private chat` | Disable reminders globally or for the current room. |
| `,remind on` | [`reminder`](plugins/reminder.md) | `user` | `room, MUC PM or private chat` | Enable reminders globally or for the current room. |
| `,remind status` | [`reminder`](plugins/reminder.md) | `user` | `room, MUC PM or private chat` | Show whether reminders are enabled. |
| `,reminders` | [`reminder`](plugins/reminder.md) | `user` | `any` | List your reminders. |
| `,sed` | [`sed`](plugins/sed.md) | `user` | `any` | Apply sed-style corrections or control room access to sed. |
| `,seen` | [`tools`](plugins/tools.md) | `user` | `any` | Show when a user was last seen. |
| `,tell` | [`tell`](plugins/tell.md) | `user` | `any` | Leave a message for another user. |
| `,time` | [`tools`](plugins/tools.md) | `user` | `any` | Show the current time from a stored profile timezone. |
| `,tools` | [`tools`](plugins/tools.md) | `moderator` | `room or MUC PM` | Enable, disable or show room access to utility commands. |
| `,translate` | [`translate`](plugins/translate.md) | `user` | `any` | Translate text or a replied-to message. |
| `,ts` | [`tools`](plugins/tools.md) | `user` | `any` | Convert a Unix timestamp to your configured timezone. |
| `,urlcheck` | [`urlcheck`](plugins/urlcheck.md) | `user` | `room or MUC PM` | Enable, disable or show automatic URL checks in a room. |
| `,utc` | [`tools`](plugins/tools.md) | `user` | `any` | Show current UTC time. |
| `,weather` | [`weather`](plugins/weather.md) | `user` | `any` | Show weather from a user's vCard location, a room nick, or an explicit city/ZIP code; or control room access. |

### Xmpp

| Command | Plugin | Role | Context | Description |
| --- | --- | --- | --- | --- |
| `,xmpp` | [`xmpp`](plugins/xmpp.md) | `user` | `room or MUC PM` | Enable, disable or show room access to XMPP lookup commands. |
| `,xmpp cert` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | Check an XMPP server-to-server TLS certificate. |
| `,xmpp check` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | Run combined XMPP service and S2S TLS diagnostics. |
| `,xmpp compliance` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | Check XMPP compliance features via disco. |
| `,xmpp contact` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | Show contact addresses from service discovery. |
| `,xmpp help` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | Show help for XMPP lookup subcommands. |
| `,xmpp info` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | Show service discovery identity/features. |
| `,xmpp items` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | List service discovery items. |
| `,xmpp ping` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | Ping an XMPP entity. |
| `,xmpp srv` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | Look up XMPP DNS SRV records. |
| `,xmpp uptime` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | Query XMPP entity uptime. |
| `,xmpp version` | [`xmpp`](plugins/xmpp.md) | `user` | `any` | Query XMPP software version and diagnose S2S TLS failures. |

## Detailed plugin docs

This generated file is intentionally an overview. Detailed usage, aliases and examples are generated into dedicated plugin documents:

- [`docs/plugins/`](plugins/) - plugin command guides
