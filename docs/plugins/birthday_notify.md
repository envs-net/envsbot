# birthday_notify plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `info`

Automatic birthday notifications in rooms (opt-in per room)

## Commands

### `,birthday_notify`

Enable, disable or show birthday notifications for a room.

Role: `user`<br>
Context: `room or MUC PM`<br>
Category: `rooms`<br>
Usage: `,birthday_notify <on|off|status>`

#### Subcommands

- `,birthday_notify on`
  - Description: Enable birthday notifications in the current room.
  - Examples:
    - `,birthday_notify on` — Enable birthday notifications for the current room or MUC PM.

- `,birthday_notify off`
  - Description: Disable birthday notifications in the current room.
  - Examples:
    - `,birthday_notify off` — Disable birthday notifications for the current room or MUC PM.

- `,birthday_notify status`
  - Description: Show whether birthday notifications is enabled in the current room.
  - Examples:
    - `,birthday_notify status` — Inspect the current room setting for birthday notifications.
