# EnvsBot documentation

This directory contains the operator and command documentation for EnvsBot.

## Index

- [`commands.md`](commands.md) - generated command reference from the live command metadata
- [`help.md`](help.md) - runtime help behavior and usage examples
- [`tutorial.md`](tutorial.md) - practical walkthrough for first setup, rooms, reminders, RSS and grants
- [`maintenance.md`](maintenance.md) - offline SQLite maintenance workflow
- [`deployment.md`](deployment.md) - install layout, console entrypoint and systemd unit
- [`diagnostics.md`](diagnostics.md) - doctor checks, plugin state, task restart, audit filters and rate limits
- [`architecture.md`](architecture.md) - runtime module layout, command flow and core responsibilities
- [`idlerpg.md`](idlerpg.md) - IdleRPG game commands, configuration and diagnostics
- [`plugin-development.md`](plugin-development.md) - plugin structure, hooks, stores, grants and diagnostics
- [`release-checklist.md`](release-checklist.md) - release preparation and tagging checklist

Operational notes:

- Core/admin plugins live in `core_plugins/`; optional feature plugins live in `plugins/`. Core plugins keep stable public names but cannot be unloaded at runtime.
- Production installations should use the latest tagged release, not the moving `main` branch.
- New operators should start with [`tutorial.md`](tutorial.md) before using the full command reference.
- Runtime help should use `,help <plugin>` for plugin help and `,help ,<command>` for unambiguous command help.
- Runtime configuration lives in `config.py`; copy `config_sample.py` and keep the file private.
- Managed backups live in `data/backups` by default; optional startup backups are controlled by `BACKUP_ON_START`.
- Operator-tunable plugin limits, timeouts and reminder timezone defaults are documented directly in `config_sample.py`.
- `,config diff` shows effective values that differ from `config_sample.py` defaults.
- `,status full` includes supervised background-task state.
- `,tasks` shows supervised background tasks without the rest of the status output.
- `,doctor` runs a compact operator health check; `,doctor full` includes more runtime detail.
- `,plugin state <plugin> [room_jid]` shows plugin-provided runtime counters.
- `,rooms diagnose <room_jid>` shows room, invite, plugin-toggle and plugin-state diagnostics.
- `,version` shows the running EnvsBot version and the latest checked release.
- `,checkupdate` / `,updatecheck` performs a manual GitHub release check.
  Automatic update notifications go to `VERSION_CHECK_NOTIFY_JID`, or to `OWNER` when unset.
  When the notification target is a MUC room, the bot joins it before sending.
- EnvsBot has no separate fixed `ADMIN_ROOM`; global bot privileges are controlled by `OWNER`, `ADMINS` and stored bot roles.
- Incoming MUC invites are stored as pending room invites when `ROOM_INVITES_ENABLED` is enabled.
  They are announced to `ROOM_INVITE_NOTIFY_JID`, `VERSION_CHECK_NOTIFY_JID`, or `OWNER` and can be accepted or declined with `,rooms invite`.
- `,audit last` shows recent administrative changes such as role updates, room changes, plugin reloads and config reloads.
  Use `,audit user`, `,audit target` or `,audit action` to filter the log.
- Role changes are guarded so the configured owner and superadmins cannot be modified by lower roles.

## Regenerate command reference

Run this after changing command decorators:

```bash
python scripts/generate_commands_md.py
```

## Room plugin settings

Room-scoped plugin toggles can be managed from a MUC PM, directly in the room, or from a normal private chat when the target room JID is provided explicitly. Runtime help has a dedicated overview:

```text
,help room settings
,help rooms enable
,help ducks
```

Examples:

```text
,rooms plugins room@conference.example.org all
,rooms enable room@conference.example.org ducks
,rooms disable room@conference.example.org xkcd
,rooms set_plugin_defaults room@conference.example.org
```

The sender must be a room admin/owner in the target room or have a bot moderator/admin role. This allows clients without MUC-PM support to manage room settings safely. If you use a notification room as an operational/admin room, pass the target room JID explicitly in room-setting commands. `ROOM_PLUGIN_DEFAULTS` in `config.py` defines the defaults for newly added rooms and for `,rooms set_plugin_defaults`; existing per-room settings are not changed until that command is used.

## Reminder timezones

Absolute reminders can include an explicit timezone token after the time:

```text
,remind 2026-07-10 13:23 CEST deploy window
,remind 2026-07-10 13:23 Europe/Berlin deploy window
,remind 2026-07-10 13:23 +02:00 deploy window
```

When no timezone is given, reminders use the user's stored `TIMEZONE` from `,timezone set <IANA timezone>`, then `REMINDER_DEFAULT_TIMEZONE` from `config.py`, then UTC.
