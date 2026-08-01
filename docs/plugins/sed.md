# sed plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `tools`

## Overview

Message correction using sed-like syntax

## Commands

### `,sed`

Apply sed-style corrections or control room access to sed.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,s/old/new/ or ,sed <on|off|status>`

#### Subcommands

- `,s/old/new/[flags]`
  - Description: Correct your most recent matching message with sed-style syntax.
  - Examples:
    - `,s/teh/the/` — Replace 'teh' with 'the' in your latest matching message.

- `,sed on`
  - Description: Enable sed corrections in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,sed on` — Enable sed corrections for the current room or MUC PM.

- `,sed off`
  - Description: Disable sed corrections in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,sed off` — Disable sed corrections for the current room or MUC PM.

- `,sed status`
  - Description: Show whether sed corrections is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,sed status` — Inspect the current room setting for sed corrections.
