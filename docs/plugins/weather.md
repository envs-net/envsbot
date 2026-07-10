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
Context: `any`<br>
Category: `utility`<br>
Usage: `,weather [on|off|status|nick|city|zip]`

Aliases: `,w`

Examples:

- `,weather status`
- `,weather Alice`
- `,rooms enable weather`
