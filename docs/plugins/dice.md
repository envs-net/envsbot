# dice plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `games`

## Overview

Roll dice with optional modifiers and success conditions.

## Commands

### `,dice`

Roll dice using common dice notation.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `fun`<br>
Usage: `,dice <on|off|status|NdM [modifier] [operator] [target]>`

Aliases: `,r`, `,roll`

#### Subcommands

- `,dice <NdM> [modifier] [operator] [target]`
  - Description: Roll one or more dice with an optional modifier and success test.
  - Examples:
    - `,dice 2d6` — Roll two six-sided dice.
    - `,dice 3d20 -5 >= 30` — Roll three d20, subtract five and compare the total with 30.

- `,dice on`
  - Description: Enable dice rolling in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,dice on` — Enable dice rolling for the current room or MUC PM.

- `,dice off`
  - Description: Disable dice rolling in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,dice off` — Disable dice rolling for the current room or MUC PM.

- `,dice status`
  - Description: Show whether dice rolling is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,dice status` — Inspect the current room setting for dice rolling.
