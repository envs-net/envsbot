# info plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `info`

## Overview

Wikipedia, Fediverse, Urban Dictionary and acronym lookup.

## Commands

### `,acronyms`

Look up stored acronym definitions.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `info`<br>
Usage: `,acronyms <acronym>`

Aliases: `,acro`, `,acronym`

Examples:

- `,acro XMPP` — Look up stored acronym definitions.

### `,acronyms add`

Suggest a new acronym definition for admin review.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `info`<br>
Usage: `,acronyms add <acronym> <description>`

Aliases: `,acro add`, `,acronym add`

Examples:

- `,acro add XMPP Extensible Messaging and Presence Protocol` — Suggest a new acronym definition for admin review.

### `,acronyms delete`

Delete pending acronym suggestions by nick or definition.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `info`<br>
Usage: `,acronyms delete <nick|acronym description>`

Aliases: `,acro del`, `,acro delete`, `,acronym del`, `,acronym delete`, `,acronyms del`

Examples:

- `,acro delete Alice` — Delete pending acronym suggestions by nick or definition.
- `,acro delete XMPP old definition` — Delete pending acronym suggestions by nick or definition.

### `,acronyms list`

List pending acronym additions and removals.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `info`<br>
Usage: `,acronyms list [all|page|last]`

Aliases: `,acro list`, `,acronym list`

Examples:

- `,acro list` — List pending acronym additions and removals.
- `,acro list 2` — List pending acronym additions and removals.

### `,acronyms merge`

Apply pending acronym additions and removals.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `info`<br>
Usage: `,acronyms merge`

Aliases: `,acro merge`, `,acronym merge`

Examples:

- `,acro merge` — Apply pending acronym additions and removals.

### `,acronyms remove`

Suggest removing one acronym definition for admin review.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `info`<br>
Usage: `,acronyms remove <acronym> <description>`

Aliases: `,acro remove`, `,acro rm`, `,acronym remove`, `,acronym rm`, `,acronyms rm`

Examples:

- `,acro remove XMPP old definition` — Suggest removing one acronym definition for admin review.

### `,fediverse`

Show the latest public post from a Fediverse account.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `info`<br>
Usage: `,fediverse <@user@instance>`

Aliases: `,fedi`

Examples:

- `,fedi @user@example.org` — Show the latest public post from a Fediverse account.

### `,info`

Enable, disable or show room access to information commands.

Role: `moderator`<br>
Context: `room or MUC PM`<br>
Category: `info`<br>
Usage: `,info <on|off|status>`

#### Subcommands

- `,info on`
  - Description: Enable information commands in the current room.
  - Examples:
    - `,info on` — Enable information commands for the current room or MUC PM.

- `,info off`
  - Description: Disable information commands in the current room.
  - Examples:
    - `,info off` — Disable information commands for the current room or MUC PM.

- `,info status`
  - Description: Show whether information commands is enabled in the current room.
  - Examples:
    - `,info status` — Inspect the current room setting for information commands.

### `,udict`

Search Urban Dictionary.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `info`<br>
Usage: `,udict <term>`

Aliases: `,ud`

Examples:

- `,ud xmpp` — Search Urban Dictionary.

### `,wikipedia`

Search Wikipedia.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `info`<br>
Usage: `,wikipedia <term>`

Aliases: `,wiki`

Examples:

- `,wiki XMPP` — Search Wikipedia.
