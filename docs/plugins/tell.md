# tell plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

## Overview

Store and deliver messages for users when they join a room again.

## Commands

### `,tell`

Leave a message for another user.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,tell <on|off|status|nick: message>`

#### Subcommands

- `,tell <nick>: <message>`
  - Description: Store a message and deliver it when that user returns to the room.
  - Context: `groupchat`
  - Examples:
    - `,tell alice: I fixed it` — Leave a message for Alice to receive when she returns.

- `,tell on`
  - Description: Enable Tell message delivery in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,tell on` — Enable Tell message delivery for the current room or MUC PM.

- `,tell off`
  - Description: Disable Tell message delivery in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,tell off` — Disable Tell message delivery for the current room or MUC PM.

- `,tell status`
  - Description: Show whether Tell message delivery is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,tell status` — Inspect the current room setting for Tell message delivery.
