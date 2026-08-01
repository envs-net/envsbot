# reminder plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

## Overview

Schedule and manage reminders

## Reminders from replies

Reply to an existing message and provide only the reminder time. The replied-to message becomes the reminder text:

```text
,remind 1h
,remind 2026-07-10 13:23
,remind 2026-07-10 13:23 Europe/Berlin
```

The shared persistent message cache is used to resolve the XMPP reply target. A client-provided XEP-0461 plain-text fallback quote is used when the original message is no longer available in the cache.

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
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,remind <when> [text or reply]`

Aliases: `,rem`, `,reminder`

Examples:

- `,remind 10m check logs` — Create a reminder.
- `Reply to a message with ,remind 1h` — Create a reminder.
- `,remind 2026-05-01 14:30 Take a break` — Create a reminder.
- `Reply to a message with ,remind 2026-05-01 14:30` — Create a reminder.
- `,remind 2026-05-01 14:30 CEST Take a break` — Create a reminder.
- `,remind 2026-05-01 14:30 Europe/Berlin Take a break` — Create a reminder.
- `,remind 2026-05-01 14:30 +02:00 Take a break` — Create a reminder.
- `,timezone set Europe/Berlin` — Create a reminder.
- `,rooms enable reminder` — Create a reminder.

### `,remind delete`

Delete one reminder.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,remind delete <id>`

Aliases: `,remind cancel`, `,remind rm`

Examples:

- `,remind delete 12` — Delete one reminder.

### `,remind off`

Disable reminders globally or for the current room.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,remind off`

Aliases: `,rem off`, `,reminder off`

Examples:

- `,remind off` — Disable reminders globally or for the current room.
- `,rooms disable reminder` — Disable reminders globally or for the current room.

### `,remind on`

Enable reminders globally or for the current room.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,remind on`

Aliases: `,rem on`, `,reminder on`

Examples:

- `,remind on` — Enable reminders globally or for the current room.
- `,rooms enable reminder` — Enable reminders globally or for the current room.

### `,remind status`

Show whether reminders are enabled.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,remind status`

Aliases: `,rem status`, `,reminder status`

Examples:

- `,remind status` — Show whether reminders are enabled.

### `,reminders`

List your reminders.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,reminders [all|page|last]`

Aliases: `,remind list`, `,rems`

Examples:

- `,reminders` — List your reminders.
