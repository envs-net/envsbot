# translate plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

Translate text or replied-to room messages with optional source-language auto-detection.

## Commands

### `,translate`

Translate text or a replied-to room message.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,tr [from] <to> [text or reply]`

Aliases: `,tr`

Examples:

- `,tr en uk Hello, world!`
- `,tr uk Hallo Welt!`
- `Reply to a message with ,tr en uk`
- `Reply to a message with ,tr uk`
- `,translate status`
- `,rooms enable translate`
