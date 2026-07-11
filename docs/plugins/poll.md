# poll plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

Room polls with voting, history and auto-close

## Commands

### `,poll`

Create and manage polls.

Role: `user`<br>
Context: `any`<br>
Category: `rooms`<br>
Usage: `,poll <on|off|status|create|list|show|result|history|vote|close|cancel|delete> ...`

Examples:

- `,poll status`
- `,poll create Tea? | yes | no`
- `,poll create multi:2 | Lunch? | Pizza | Döner | Falafel`
- `,poll list`
- `,poll list 2`
- `,rooms enable poll`
