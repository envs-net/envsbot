# pin plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

Pin room messages with paging, search, tags, important pins and non-reply fallback.

## Commands

### `,pin`

Pin, list, search, mark important, edit, tag or delete room pins.

Role: `user`<br>
Context: `any`<br>
Category: `rooms`<br>
Usage: `,pin <add|list|important|search|find|show|edit|tags|delete|on|off|status> ...`

Examples:

- `,pin status`
- `,pin list`
- `,pin search mail`
- `,pin search ssh key`
- `,pin edit 3 Updated room info`
- `,pin tags 3 mail support`
- `,pin important 3 on`
- `,pin important list`
- `,rooms enable pin`
