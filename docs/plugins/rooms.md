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

- `,rooms add test@conference.example.org EnvsBot true` — Add or update a stored room configuration.

### `,rooms delete`

Remove a stored room and leave it if currently joined.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms delete <room_jid>`

Aliases: `,room del`, `,room delete`, `,room remove`, `,room rm`, `,rooms del`, `,rooms remove`, `,rooms rm`

Examples:

- `,rooms delete test@conference.example.org` — Remove a stored room and leave it if currently joined.

### `,rooms diagnose`

Show operational diagnostics for one room.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms diagnose <room_jid>`

Aliases: `,room debug`, `,room diagnose`, `,rooms debug`

Examples:

- `,rooms diagnose room@conference.example.org` — Show operational diagnostics for one room.

### `,rooms disable`

Disable a room plugin toggle; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms disable [<room_jid>] <plugin>`

Aliases: `,room disable`, `,room feature disable`, `,rooms feature disable`

Examples:

- `,rooms disable ducks` — Disable a room plugin toggle; requires room admin/owner or bot moderator.
- `,rooms disable room@conference.example.org ducks` — Disable a room plugin toggle; requires room admin/owner or bot moderator.
- `,rooms disable xkcd` — Disable a room plugin toggle; requires room admin/owner or bot moderator.

### `,rooms enable`

Enable a room plugin toggle; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms enable [<room_jid>] <plugin>`

Aliases: `,room enable`, `,room feature enable`, `,rooms feature enable`

Examples:

- `,rooms enable ducks` — Enable a room plugin toggle; requires room admin/owner or bot moderator.
- `,rooms enable room@conference.example.org ducks` — Enable a room plugin toggle; requires room admin/owner or bot moderator.
- `,rooms enable weather` — Enable a room plugin toggle; requires room admin/owner or bot moderator.
- `,help room settings` — Enable a room plugin toggle; requires room admin/owner or bot moderator.

### `,rooms invite`

List, accept, decline or clean up pending room invites.

Role: `admin`<br>
Context: `private chat / MUC PM / invite notify room`<br>
Category: `rooms`<br>
Usage: `,rooms invite list [all|page|last] | ,rooms invite accept <id> | ,rooms invite decline <id> | ,rooms invite cleanup [all|expired]`

Aliases: `,room invite`

#### Subcommands

- `,rooms invite list [all|page|last]`
  - Description: List pending room invitations waiting for an admin decision.
  - Aliases: `,rooms invite ls`
  - Examples:
    - `,rooms invite list` — Show the first page of pending invitations.

- `,rooms invite accept <id>`
  - Description: Accept one pending invitation and join/store the room.
  - Examples:
    - `,rooms invite accept 1` — Accept pending invitation 1.

- `,rooms invite decline <id>`
  - Description: Decline and remove one pending room invitation.
  - Examples:
    - `,rooms invite decline 1` — Decline pending invitation 1.

- `,rooms invite cleanup [all|expired]`
  - Description: Remove all pending invites or only expired entries.
  - Examples:
    - `,rooms invite cleanup expired` — Delete only expired pending invitations.
    - `,rooms invite cleanup all` — Delete every pending invitation.

### `,rooms join`

Join a room immediately and store it if needed.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms join <room_jid> [nick]`

Aliases: `,room join`

Examples:

- `,rooms join test@conference.example.org` — Join a room immediately and store it if needed.

### `,rooms leave`

Leave a room without deleting its stored configuration.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms leave <room_jid>`

Aliases: `,room leave`

Examples:

- `,rooms leave test@conference.example.org` — Leave a room without deleting its stored configuration.

### `,rooms list`

List MUC rooms or direct XMPP contacts.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms list [muc|dm|1:1|direct|contacts] [<page>|last|all]`

Aliases: `,room list`

Examples:

- `,rooms list` — List MUC rooms or direct XMPP contacts.
- `,rooms list all` — List MUC rooms or direct XMPP contacts.
- `,rooms list dm` — List MUC rooms or direct XMPP contacts.
- `,rooms list 1:1 all` — List MUC rooms or direct XMPP contacts.
- `,rooms list direct` — List MUC rooms or direct XMPP contacts.
- `,rooms list contacts all` — List MUC rooms or direct XMPP contacts.

### `,rooms plugins`

Show room plugin toggles; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms plugins [<room_jid>] [all|page|last]`

Aliases: `,room feature list`, `,room features`, `,room features list`, `,room plugins`, `,room plugins list`, `,rooms feature list`, `,rooms features`, `,rooms features list`, `,rooms plugins list`

Examples:

- `,rooms plugins` — Show room plugin toggles; requires room admin/owner or bot moderator.
- `,rooms plugins all` — Show room plugin toggles; requires room admin/owner or bot moderator.
- `,rooms plugins room@conference.example.org all` — Show room plugin toggles; requires room admin/owner or bot moderator.
- `,help room settings` — Show room plugin toggles; requires room admin/owner or bot moderator.
- `,help rooms settings` — Show room plugin toggles; requires room admin/owner or bot moderator.

### `,rooms set_plugin_defaults`

Restore room plugin toggles for a room; requires room admin/owner or bot moderator.

Role: `user`<br>
Context: `room / MUC PM / private chat with <room_jid>`<br>
Category: `rooms`<br>
Usage: `,rooms set_plugin_defaults [<room_jid>]`

Aliases: `,room set_plugin_defaults`, `,room spd`, `,rooms spd`

Examples:

- `,rooms set_plugin_defaults` — Restore room plugin toggles for a room; requires room admin/owner or bot moderator.
- `,rooms spd` — Restore room plugin toggles for a room; requires room admin/owner or bot moderator.
- `,rooms set_plugin_defaults room@conference.example.org` — Restore room plugin toggles for a room; requires room admin/owner or bot moderator.

### `,rooms sync`

Synchronize joined rooms with stored autojoin settings.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms sync`

Aliases: `,room sync`

Examples:

- `,rooms sync` — Synchronize joined rooms with stored autojoin settings.

### `,rooms update`

Update one field of a stored room.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `rooms`<br>
Usage: `,rooms update <room_jid> <nick|autojoin|status> <value>`

Aliases: `,room update`

Examples:

- `,rooms update test@conference.example.org autojoin true` — Update one field of a stored room.
