# vcard plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `info`

## Overview

Lookup and display vCard of a MUC occupant by MUC JID only

## Commands

### `,birthday`

Show birthday data from a user's vCard.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `profile`<br>
Usage: `,birthday [nick]`

Aliases: `,b`

Examples:

- `,birthday Alice` — Show birthday data from a user's vCard.

### `,emails`

Show email addresses from a user's vCard.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `profile`<br>
Usage: `,emails [nick]`

Aliases: `,e`

Examples:

- `,emails Alice` — Show email addresses from a user's vCard.

### `,fullname`

Show the full name from a user's vCard.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `profile`<br>
Usage: `,fullname [nick]`

Aliases: `,f`

Examples:

- `,fullname Alice` — Show the full name from a user's vCard.

### `,nicknames`

Show nicknames from a user's vCard.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `profile`<br>
Usage: `,nicknames [nick]`

Aliases: `,nicks`

Examples:

- `,nicks Alice` — Show nicknames from a user's vCard.

### `,notes`

Show notes from a user's vCard.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `profile`<br>
Usage: `,notes [nick]`

Examples:

- `,notes Alice` — Show notes from a user's vCard.

### `,organisations`

Show organisations from a user's vCard.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `profile`<br>
Usage: `,organisations [nick]`

Aliases: `,orgs`

Examples:

- `,orgs Alice` — Show organisations from a user's vCard.

### `,timezone`

Show your configured timezone.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `profile`<br>
Usage: `,timezone`

Aliases: `,tz`

Examples:

- `,tz` — Show your configured timezone.

### `,timezone set`

Set your timezone in the bot profile.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `profile`<br>
Usage: `,timezone set <IANA timezone>`

Aliases: `,tz set`

Examples:

- `,tz set Europe/Berlin` — Set your timezone in the bot profile.

### `,urls`

Show URLs from a user's vCard.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `profile`<br>
Usage: `,urls [nick]`

Aliases: `,u`

Examples:

- `,urls Alice` — Show URLs from a user's vCard.

### `,vcard`

Show vCard data or control room access to vCard lookups.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `profile`<br>
Usage: `,vcard [on|off|status|nick]`

Aliases: `,v`

#### Subcommands

- `,vcard [nick]`
  - Description: Show your own vCard or look up a room user's vCard by nickname.
  - Examples:
    - `,vcard` — Show your own vCard in a direct chat.
    - `,vcard Alice` — Show Alice's vCard in a shared room.

- `,vcard on`
  - Description: Enable vCard lookups in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,vcard on` — Enable vCard lookups for the current room or MUC PM.

- `,vcard off`
  - Description: Disable vCard lookups in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,vcard off` — Disable vCard lookups for the current room or MUC PM.

- `,vcard status`
  - Description: Show whether vCard lookups is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,vcard status` — Inspect the current room setting for vCard lookups.
