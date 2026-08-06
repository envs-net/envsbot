# Plugin documentation

This file is generated from command metadata. Do not edit it by hand.

```bash
python scripts/generate_commands_md.py
```

`docs/commands.md` is the compact command overview. These plugin pages contain the detailed command usage, aliases and examples for each plugin.

| Plugin | Source | Category | Description |
| --- | --- | --- | --- |
| [`_admin`](_admin.md) | `core` | `core` | Bot administration commands |
| [`audit`](audit.md) | `core` | `core` | Admin audit log viewer |
| [`backups`](backups.md) | `core` | `core` | Managed ZIP backups and restore helpers. |
| [`config_cmd`](config_cmd.md) | `core` | `core` | Safe config inspection, validation and reload commands. |
| [`doctor`](doctor.md) | `core` | `core` | Operator health checks and runtime diagnostics. |
| [`help`](help.md) | `core` | `core` | Dynamic help for plugins and commands. |
| [`outbox`](outbox.md) | `core` | `core` | Inspect and retry durable outbound messages. |
| [`plugins`](plugins.md) | `core` | `core` | Runtime plugin management |
| [`presence`](presence.md) | `core` | `info` | Bot presence and status management |
| [`reports`](reports.md) | `core` | `core` | Optional daily admin health report. |
| [`rooms`](rooms.md) | `core` | `core` | Database-backed room management |
| [`tasks`](tasks.md) | `core` | `core` | Inspect supervised background tasks. |
| [`usage`](usage.md) | `core` | `core` | Inspect aggregate command usage and find unused commands. |
| [`users`](users.md) | `core` | `core` | User management with caching, nick lookup and logging |
| [`birthday_notify`](birthday_notify.md) | `plugins` | `info` | Automatic birthday notifications in rooms (opt-in per room) |
| [`dice`](dice.md) | `plugins` | `games` | Roll dice with optional modifiers and success conditions. |
| [`ducks`](ducks.md) | `plugins` | `games` | Spawns ducks after room activity so users can befriend or trap them, with persistent room leaderboards and configurable pacing. |
| [`idlerpg`](idlerpg.md) | `plugins` | `games` | IdleRPG game for MUCs, inspired by the classic IRC game |
| [`info`](info.md) | `plugins` | `info` | Wikipedia, Fediverse, Urban Dictionary and acronym lookup. |
| [`karma`](karma.md) | `plugins` | `fun` | Room-local karma tracking with nick++ / nick-- |
| [`pin`](pin.md) | `plugins` | `utility` | Pin room messages with paging, search, tags, important pins and non-reply fallback. |
| [`poll`](poll.md) | `plugins` | `utility` | Room polls with voting, history and auto-close |
| [`reminder`](reminder.md) | `plugins` | `utility` | Schedule and manage reminders |
| [`rss`](rss.md) | `plugins` | `info` | RSS/Atom feed watcher and poster |
| [`sed`](sed.md) | `plugins` | `tools` | Message correction using sed-like syntax |
| [`tell`](tell.md) | `plugins` | `utility` | Store and deliver messages for users when they join a room again. |
| [`tools`](tools.md) | `plugins` | `utility` | Utility commands: ping/pong, message echo, timezone-aware time/date lookups, Unix timestamp conversion, and HTTPS certificate checks |
| [`translate`](translate.md) | `plugins` | `utility` | Translate text or replied-to messages with optional source-language auto-detection. |
| [`urlcheck`](urlcheck.md) | `plugins` | `info` | URL title and YouTube info fetcher for groupchats |
| [`vcard`](vcard.md) | `plugins` | `info` | Lookup and display vCard of a MUC occupant by MUC JID only |
| [`weather`](weather.md) | `plugins` | `info` | Gives weather according to users location or an explicit city/ZIP code |
| [`xkcd`](xkcd.md) | `plugins` | `fun` | XKCD comic fetcher and broadcaster with full indexing |
| [`xmpp`](xmpp.md) | `plugins` | `tools` | XMPP utility tools (ping, diagnostics, service discovery, DNS SRV, etc.) |
