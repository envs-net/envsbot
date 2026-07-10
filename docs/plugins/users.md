# users plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

User management with caching, nick lookup and logging

## Commands

### `,users admins`

List users with admin-level roles.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users admins [all|page|last]`

Aliases: `,user admin`, `,user admins`, `,users admin`

Examples:

- `,users admins`

### `,users delete`

Delete one non-privileged user record and its runtime data.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users delete <jid>`

Aliases: `,user delete`

Examples:

- `,users delete alice@example.org`

### `,users grant`

Grant room-scoped plugin permissions to a user.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users grant <jid> <plugin> [plugin ...]`

Aliases: `,user grant`, `,user plugin grant`, `,users plugin grant`

Examples:

- `,users grant alice@example.org rss pin poll`

### `,users grants`

Show a user's room-scoped plugin permissions.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users grants <jid>`

Aliases: `,user grants`, `,user plugin grants`, `,users plugin grants`

Examples:

- `,users grants alice@example.org`

### `,users info`

Show user info by JID or known nickname.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users info <jid|nick>`

Aliases: `,user info`

Examples:

- `,users info alice@example.org`

### `,users list`

List users currently known in one joined room.

Role: `admin`<br>
Context: `private chat only`<br>
Category: `users`<br>
Usage: `,users list [room_jid]`

Aliases: `,user list`

Examples:

- `,users list test@conference.example.org`

### `,users permissions`

Diagnose global, room and room-scoped plugin permissions.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users permissions <jid|nick> [room_jid]`

Aliases: `,user permissions`, `,user perms`, `,users perms`

Examples:

- `,users permissions alice@example.org`
- `,users permissions alice@example.org room@conference.example.org`
- `,users perms alice room@conference.example.org`

### `,users revoke`

Revoke room-scoped plugin permissions from a user.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users revoke <jid> <plugin> [plugin ...]`

Aliases: `,user plugin revoke`, `,user revoke`, `,users plugin revoke`

Examples:

- `,users revoke alice@example.org rss`

### `,users role`

Change a user's global bot role with hierarchy checks.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users role <jid> <role>`

Aliases: `,user role`

Examples:

- `,users role alice@example.org trusted`

### `,users roles`

Show available roles and their ordering.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users roles`

Aliases: `,user roles`

Examples:

- `,users roles`
