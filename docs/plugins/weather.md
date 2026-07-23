# weather plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `info`

Gives weather according to users location or an explicit city/ZIP code

## Commands

### `,weather`

Show weather from a user's vCard location, a room nick, or an explicit city/ZIP code; or control room access.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,weather [on|off|status|nick|city|zip]`

Aliases: `,w`

#### Subcommands

- `,weather [nick|city|zip]`
  - Description: Show weather for your vCard location, a room nickname or an explicit place.
  - Examples:
    - `,weather` — Show weather for your own stored vCard location.
    - `,weather Alice` — Show weather for Alice's vCard location in a shared room.
    - `,weather Berlin` — Show weather for an explicitly named city.

- `,weather on`
  - Description: Enable weather lookups in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,weather on` — Enable weather lookups for the current room or MUC PM.

- `,weather off`
  - Description: Disable weather lookups in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,weather off` — Disable weather lookups for the current room or MUC PM.

- `,weather status`
  - Description: Show whether weather lookups is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,weather status` — Inspect the current room setting for weather lookups.
