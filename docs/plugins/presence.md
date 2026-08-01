# presence plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `info`

## Overview

Bot presence and status management

## Commands

### `,presence`

Show or control per-room access to presence lookup.

Role: `none`<br>
Context: `room, MUC PM or private chat`<br>
Category: `info`<br>
Usage: `,presence [on|off|status]`

#### Subcommands

- `,presence`
  - Description: Show the bot's current presence state and status message.
  - Examples:
    - `,presence` — Display the current presence state and status text.

- `,presence on`
  - Description: Enable presence lookup in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,presence on` — Enable presence lookup for the current room or MUC PM.

- `,presence off`
  - Description: Disable presence lookup in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,presence off` — Disable presence lookup for the current room or MUC PM.

- `,presence status`
  - Description: Show whether presence lookup is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,presence status` — Inspect the current room setting for presence lookup.

### `,presence set`

Set the bot presence state and status text.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `info`<br>
Usage: `,presence set <online|chat|away|xa|dnd> [message]`

Examples:

- `,presence set away maintenance` — Set the bot presence state and status text.
