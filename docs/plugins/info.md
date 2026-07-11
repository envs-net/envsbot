# info plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `info`

Wikipedia, Fediverse, Urban Dictionary and acronym lookup.

## Commands

### `,acronyms`

Look up stored acronym definitions.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms <acronym>`

Aliases: `,acro`, `,acronym`

Examples:

- `,acro XMPP`

### `,acronyms add`

Suggest a new acronym definition for admin review.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms add <acronym> <description>`

Aliases: `,acro add`, `,acronym add`

Examples:

- `,acro add XMPP Extensible Messaging and Presence Protocol`

### `,acronyms delete`

Delete pending acronym suggestions by nick or definition.

Role: `admin`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms delete <nick|acronym description>`

Aliases: `,acro delete`, `,acronym delete`

Examples:

- `,acro delete Alice`
- `,acro delete XMPP old definition`

### `,acronyms list`

List pending acronym additions and removals.

Role: `admin`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms list [all|page|last]`

Aliases: `,acro list`, `,acronym list`

Examples:

- `,acro list`
- `,acro list 2`

### `,acronyms merge`

Apply pending acronym additions and removals.

Role: `admin`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms merge`

Aliases: `,acro merge`, `,acronym merge`

Examples:

- `,acro merge`

### `,acronyms remove`

Suggest removing one acronym definition for admin review.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,acronyms remove <acronym> <description>`

Aliases: `,acro remove`, `,acronym remove`

Examples:

- `,acro remove XMPP old definition`

### `,fediverse`

Show the latest public post from a Fediverse account.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,fediverse <@user@instance>`

Aliases: `,fedi`

Examples:

- `,fedi @user@example.org`

### `,info`

Enable, disable or show room access to information commands.

Role: `moderator`<br>
Context: `room or MUC PM`<br>
Category: `info`<br>
Usage: `,info <on|off|status>`

Examples:

- `,info status`

### `,udict`

Search Urban Dictionary.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,udict <term>`

Aliases: `,ud`

Examples:

- `,ud xmpp`

### `,wikipedia`

Search Wikipedia.

Role: `user`<br>
Context: `any`<br>
Category: `info`<br>
Usage: `,wikipedia <term>`

Aliases: `,wiki`

Examples:

- `,wiki XMPP`
