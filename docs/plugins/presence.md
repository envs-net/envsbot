# presence plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `info`

Bot presence and status management

## Commands

### `,presence`

Show or control per-room access to presence lookup.

Role: `none`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,presence [on|off|status]`

Examples:

- `,presence`
- `,presence status`

### `,presence set`

Set the bot presence state and status text.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `info`<br>
Usage: `,presence set <online|chat|away|xa|dnd> [message]`

Examples:

- `,presence set away maintenance`
