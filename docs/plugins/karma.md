# karma plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `fun`

Room-local karma tracking with nick++ / nick--

## Commands

### `,karma`

Show room-local karma scores and rankings.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `fun`<br>
Usage: `,karma <on|off|status|top|bottom|nick>`

#### Subcommands

- `,karma top`
  - Description: Show the highest room-local karma scores.
  - Context: `groupchat`
  - Examples:
    - `,karma top` — List the users with the most karma in this room.

- `,karma bottom`
  - Description: Show the lowest room-local karma scores.
  - Context: `groupchat`
  - Examples:
    - `,karma bottom` — List the users with the least karma in this room.

- `,karma <nick>`
  - Description: Show one nickname's karma score.
  - Context: `groupchat`
  - Examples:
    - `,karma xmpp` — Show the karma score for the nickname 'xmpp'.

- `,karma on`
  - Description: Enable karma tracking in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,karma on` — Enable karma tracking for the current room or MUC PM.

- `,karma off`
  - Description: Disable karma tracking in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,karma off` — Disable karma tracking for the current room or MUC PM.

- `,karma status`
  - Description: Show whether karma tracking is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,karma status` — Inspect the current room setting for karma tracking.
