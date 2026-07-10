# reminder plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

Schedule and manage reminders

## Timezone-aware reminders

Relative reminders do not need a timezone:

```text
,remind 10m check the logs
,remind 1h30m restart the service
,remind 2d review the backup plan
```

Absolute reminders use the user's configured timezone, the bot fallback, or an explicit timezone token:

```text
,remind 2026-07-10 13:23 deploy window
,remind 2026-07-10 13:23 CEST deploy window
,remind 2026-07-10 13:23 Europe/Berlin deploy window
,remind 2026-07-10 13:23 +02:00 deploy window
```

For absolute dates without an explicit timezone, the plugin resolves the timezone in this order:

1. explicit timezone in the command, for example `CEST`, `Europe/Berlin` or `+02:00`
2. the user's stored `TIMEZONE`, set with `,timezone set Europe/Berlin`
3. `REMINDER_DEFAULT_TIMEZONE` from `config.py`
4. UTC as final fallback

Supported command timezone forms:

- `UTC`, `GMT`, `Z`
- `CET` / `MEZ`
- `CEST` / `MESZ`
- IANA timezone names such as `Europe/Berlin`
- fixed offsets such as `+02:00`, `+0200` or `-05:00`

Prefer IANA timezone names such as `Europe/Berlin` for user profiles and bot defaults because they handle daylight saving time automatically. `CET` and `CEST` are fixed offsets and mean exactly UTC+1 and UTC+2.

Configuration fallback:

```python
REMINDER_DEFAULT_TIMEZONE = "UTC"
```

## Commands

### `,remind`

Create a reminder.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,remind <on|off|status|when> [text]`

Aliases: `,rem`, `,reminder`

Examples:

- `,remind status`
- `,remind 10m check logs`
- `,remind 2026-05-01 14:30 Take a break`
- `,remind 2026-05-01 14:30 CEST Take a break`
- `,remind 2026-05-01 14:30 Europe/Berlin Take a break`
- `,remind 2026-05-01 14:30 +02:00 Take a break`
- `,timezone set Europe/Berlin`
- `,rooms enable reminder`

### `,remind delete`

Delete one reminder.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,remind delete <id>`

Aliases: `,remind cancel`, `,remind rm`

Examples:

- `,remind delete 12`

### `,reminders`

List your reminders.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,reminders [all|page|last]`

Aliases: `,remind list`, `,rems`

Examples:

- `,reminders`
