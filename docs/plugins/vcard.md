# vcard plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `info`

Lookup and display vCard of a MUC occupant by MUC JID only

## Commands

### `,birthday`

Show birthday data from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,birthday [nick]`

Aliases: `,b`

Examples:

- `,birthday Alice`

### `,emails`

Show email addresses from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,emails [nick]`

Aliases: `,e`

Examples:

- `,emails Alice`

### `,fullname`

Show the full name from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,fullname [nick]`

Aliases: `,f`

Examples:

- `,fullname Alice`

### `,nicknames`

Show nicknames from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,nicknames [nick]`

Aliases: `,nicks`

Examples:

- `,nicks Alice`

### `,notes`

Show notes from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,notes [nick]`

Examples:

- `,notes Alice`

### `,organisations`

Show organisations from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,organisations [nick]`

Aliases: `,orgs`

Examples:

- `,orgs Alice`

### `,timezone`

Show your configured timezone.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,timezone`

Aliases: `,tz`

Examples:

- `,tz`

### `,timezone set`

Set your timezone in the bot profile.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,timezone set <IANA timezone>`

Aliases: `,tz set`

Examples:

- `,tz set Europe/Berlin`

### `,urls`

Show URLs from a user's vCard.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,urls [nick]`

Aliases: `,u`

Examples:

- `,urls Alice`

### `,vcard`

Show vCard data or control room access to vCard lookups.

Role: `user`<br>
Context: `any`<br>
Category: `profile`<br>
Usage: `,vcard [on|off|status|nick]`

Aliases: `,v`

Examples:

- `,vcard`
- `,vcard status`
- `,rooms enable vcard`
