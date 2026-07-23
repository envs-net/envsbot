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

- `,users admins` — List users with admin-level roles.

### `,users delete`

Delete one non-privileged user record and its runtime data.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users delete <jid>`

Aliases: `,user del`, `,user delete`, `,user remove`, `,user rm`, `,users del`, `,users remove`, `,users rm`

Examples:

- `,users delete alice@example.org` — Delete one non-privileged user record and its runtime data.

### `,users grant`

Grant room-scoped plugin permissions to a user.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users grant <jid> <plugin> [plugin ...]`

Aliases: `,user grant`, `,user plugin grant`, `,users plugin grant`

Examples:

- `,users grant alice@example.org rss pin poll` — Grant room-scoped plugin permissions to a user.

### `,users grants`

Show a user's room-scoped plugin permissions.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users grants <jid>`

Aliases: `,user grants`, `,user plugin grants`, `,users plugin grants`

Examples:

- `,users grants alice@example.org` — Show a user's room-scoped plugin permissions.

### `,users info`

Show your user info, or inspect another user as an admin.

Role: `user`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users info [jid|nick]`

Aliases: `,user info`

Examples:

- `,users info` — Show your user info, or inspect another user as an admin.
- `,users info alice@example.org` — Show your user info, or inspect another user as an admin.

### `,users list`

List known users by direct, room-observed or stored-only source.

Role: `admin`<br>
Context: `private chat only`<br>
Category: `users`<br>
Usage: `,users list [active|passive|known|room_jid] [all|page|last]`

Aliases: `,user list`

Examples:

- `,users list` — List known users by direct, room-observed or stored-only source.
- `,users list active` — List known users by direct, room-observed or stored-only source.
- `,users list passive all` — List known users by direct, room-observed or stored-only source.
- `,users list test@conference.example.org 2` — List known users by direct, room-observed or stored-only source.

### `,users permissions`

Diagnose global, room and room-scoped plugin permissions.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users permissions <jid|nick> [room_jid]`

Aliases: `,user permissions`, `,user perms`, `,users perms`

Examples:

- `,users permissions alice@example.org` — Diagnose global, room and room-scoped plugin permissions.
- `,users permissions alice@example.org room@conference.example.org` — Diagnose global, room and room-scoped plugin permissions.
- `,users perms alice room@conference.example.org` — Diagnose global, room and room-scoped plugin permissions.

### `,users revoke`

Revoke room-scoped plugin permissions from a user.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users revoke <jid> <plugin> [plugin ...]`

Aliases: `,user plugin revoke`, `,user revoke`, `,users plugin revoke`

Examples:

- `,users revoke alice@example.org rss` — Revoke room-scoped plugin permissions from a user.

### `,users role`

Create or change a user's global bot role with hierarchy checks.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users role <jid> <role>`

Aliases: `,user role`

Examples:

- `,users role alice@example.org trusted` — Create or change a user's global bot role with hierarchy checks.

### `,users roles`

Show available roles and their ordering.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `users`<br>
Usage: `,users roles`

Aliases: `,user roles`

Examples:

- `,users roles` — Show available roles and their ordering.
