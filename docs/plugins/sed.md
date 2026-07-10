# sed plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `tools`

Message correction using sed-like syntax

## Commands

### `,sed`

Apply sed-style corrections or control room access to sed.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,s/old/new/ or ,sed <on|off|status>`

Examples:

- `,s/teh/the/`
- `,sed status`
- `,rooms enable sed`
