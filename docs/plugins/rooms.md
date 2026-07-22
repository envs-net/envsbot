# rooms plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

Database-backed room management

## Commands

### `,rooms add`

Add or update a stored room configuration.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms add <room_jid> [nick] [autojoin]`

Aliases: `,room add`

Examples:

- `,rooms add test@conference.example.org EnvsBot true`

### `,rooms delete`

Remove a stored room and leave it if currently joined.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms delete <room_jid>`

Aliases: `,room delete`

Examples:

- `,rooms delete test@conference.example.org`

### `,rooms diagnose`

Show operational diagnostics for one room.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms diagnose <room_jid>`

Aliases: `,room debug`, `,room diagnose`, `,rooms debug`

Examples:

- `,rooms diagnose room@conference.example.org`

### `,rooms disable`

Disable a room plugin toggle; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms disable [<room_jid>] <plugin>`

Aliases: `,room disable`, `,room feature disable`, `,rooms feature disable`

Examples:

- `,rooms disable ducks`
- `,rooms disable room@conference.example.org ducks`
- `,rooms disable xkcd`

### `,rooms enable`

Enable a room plugin toggle; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms enable [<room_jid>] <plugin>`

Aliases: `,room enable`, `,room feature enable`, `,rooms feature enable`

Examples:

- `,rooms enable ducks`
- `,rooms enable room@conference.example.org ducks`
- `,rooms enable weather`
- `,help room settings`

### `,rooms invite`

List, accept, decline or clean up pending room invites.

Role: `admin`<br>
Context: `private chat / MUC PM / invite notify room`<br>
Category: `rooms`<br>
Usage: `,rooms invite list [all|page|last] | ,rooms invite accept <id> | ,rooms invite decline <id> | ,rooms invite cleanup [all|expired]`

Aliases: `,room invite`

Examples:

- `,rooms invite list`
- `,rooms invite list all`
- `,rooms invite accept 1`
- `,rooms invite decline 1`
- `,rooms invite cleanup`
- `,rooms invite cleanup all`
- `,rooms invite cleanup expired`

### `,rooms join`

Join a room immediately and store it if needed.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms join <room_jid> [nick]`

Aliases: `,room join`

Examples:

- `,rooms join test@conference.example.org`

### `,rooms leave`

Leave a room without deleting its stored configuration.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms leave <room_jid>`

Aliases: `,room leave`

Examples:

- `,rooms leave test@conference.example.org`

### `,rooms list`

List MUC rooms or direct XMPP contacts.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms list [muc|dm|1:1] [<page>|last|all]`

Aliases: `,room list`

Examples:

- `,rooms list`
- `,rooms list all`
- `,rooms list dm`
- `,rooms list 1:1 all`
- `,rooms list direct`
- `,rooms list contacts all`

### `,rooms plugins`

Show room plugin toggles; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms plugins [<room_jid>] [all|page|last]`

Aliases: `,room feature list`, `,room features`, `,room features list`, `,room plugins`, `,room plugins list`, `,rooms feature list`, `,rooms features`, `,rooms features list`, `,rooms plugins list`

Examples:

- `,rooms plugins`
- `,rooms plugins all`
- `,rooms plugins room@conference.example.org all`
- `,help room settings`
- `,help rooms settings`

### `,rooms set_plugin_defaults`

Restore room plugin toggles for a room; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms set_plugin_defaults [<room_jid>]`

Aliases: `,room set_plugin_defaults`, `,room spd`, `,rooms spd`

Examples:

- `,rooms set_plugin_defaults`
- `,rooms spd`
- `,rooms set_plugin_defaults room@conference.example.org`

### `,rooms sync`

Synchronize joined rooms with stored autojoin settings.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms sync`

Aliases: `,room sync`

Examples:

- `,rooms sync`

### `,rooms update`

Update one field of a stored room.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms update <room_jid> <nick|autojoin|status> <value>`

Aliases: `,room update`

Examples:

- `,rooms update test@conference.example.org autojoin true`
