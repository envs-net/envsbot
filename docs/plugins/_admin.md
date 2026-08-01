# _admin plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

## Overview

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

- `,bot checkupdate` — Check whether a newer EnvsBot release is available.
- `,checkupdate` — Check whether a newer EnvsBot release is available.
- `,updatecheck` — Check whether a newer EnvsBot release is available.

### `,bot restart`

Restart the bot process gracefully.

Role: `owner`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot restart`

Aliases: `,restart`

Examples:

- `,bot restart` — Restart the bot process gracefully.

### `,bot shutdown`

Stop the bot gracefully, optionally using a configured command.

Role: `owner`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot shutdown`

Aliases: `,shutdown`

Examples:

- `,bot shutdown` — Stop the bot gracefully, optionally using a configured command.

### `,bot status`

Show bot, runtime, XMPP rooms/direct contacts, plugin and database status.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,bot status [full]`

Aliases: `,bot info`, `,status`

Examples:

- `,bot status` — Show bot, runtime, XMPP rooms/direct contacts, plugin and database status.
- `,status` — Show bot, runtime, XMPP rooms/direct contacts, plugin and database status.
- `,bot status full` — Show bot, runtime, XMPP rooms/direct contacts, plugin and database status.

### `,bot version`

Show the running EnvsBot version and latest checked release.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `core`<br>
Usage: `,bot version`

Aliases: `,version`

Examples:

- `,bot version` — Show the running EnvsBot version and latest checked release.
- `,version` — Show the running EnvsBot version and latest checked release.
