# help plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

Dynamic help for plugins and commands.

## Commands

### `,help`

Show help for plugins and commands.

Role: `none`<br>
Context: `any`<br>
Category: `core`<br>
Usage: `,help [all|commands|plugins|roles|categories|category <name>|room settings|<plugin>|,<command>]`

Aliases: `,h`

Examples:

- `,help`
- `,help room settings`
- `,help rooms settings`
- `,help ducks`
- `,help rooms enable`
- `,help ,users role`
- `,help category admin`

### `,help inroom`

Enable, disable or show room help availability.

Role: `user`<br>
Context: `room or MUC PM`<br>
Category: `core`<br>
Usage: `,help inroom <on|off|status>`

Aliases: `,h inroom`

Examples:

- `,help inroom on`
- `,help inroom status`
