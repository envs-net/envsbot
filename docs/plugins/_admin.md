# _admin plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

Bot administration commands

## Commands

### `,bot checkupdate`

Check whether a newer EnvsBot release is available.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot checkupdate`

Aliases: `,bot updatecheck`, `,checkupdate`, `,updatecheck`

Examples:

- `,bot checkupdate`
- `,checkupdate`
- `,updatecheck`

### `,bot restart`

Restart the bot process gracefully.

Role: `owner`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot restart`

Aliases: `,restart`

Examples:

- `,bot restart`

### `,bot shutdown`

Stop the bot using the configured stop command.

Role: `owner`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot shutdown`

Aliases: `,shutdown`

Examples:

- `,bot shutdown`

### `,bot status`

Show bot, runtime, XMPP, plugin and database status.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot status [full]`

Aliases: `,bot info`, `,status`

Examples:

- `,bot status`
- `,status`
- `,bot status full`

### `,bot version`

Show the running EnvsBot version and latest checked release.

Role: `user`<br>
Context: `any`<br>
Category: `core`<br>
Usage: `,bot version`

Aliases: `,version`

Examples:

- `,bot version`
- `,version`
