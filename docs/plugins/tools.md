# tools plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

Utility commands: ping/pong, message echo, timezone-aware time/date lookups, Unix timestamp conversion, and HTTPS certificate checks

## Commands

### `,cert`

Check an HTTPS TLS certificate and its remaining lifetime.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,cert <domain[:port]|https-url>`

Aliases: `,certificate`, `,check`

Examples:

- `,cert example.org` — Check an HTTPS TLS certificate and its remaining lifetime.
- `,check https://example.org` — Check an HTTPS TLS certificate and its remaining lifetime.
- `,cert example.org:8443` — Check an HTTPS TLS certificate and its remaining lifetime.

### `,date`

Show the current date from a stored profile timezone.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,date [nick]`

Examples:

- `,date` — Show the current date from a stored profile timezone.
- `,date Alice` — Show the current date from a stored profile timezone.

### `,echo`

Echo text back to you.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,echo <text>`

Examples:

- `,echo hello` — Echo text back to you.

### `,ping`

Check whether the bot is alive.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,ping`

Aliases: `,pong`

Examples:

- `,ping` — Check whether the bot is alive.

### `,seen`

Show when a user was last seen.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,seen <nick|jid>`

Aliases: `,s`

Examples:

- `,seen alice` — Show when a user was last seen.

### `,time`

Show the current time from a stored profile timezone.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,time [nick]`

Aliases: `,t`

Examples:

- `,time` — Show the current time from a stored profile timezone.
- `,time Alice` — Show the current time from a stored profile timezone.

### `,tools`

Enable, disable or show room access to utility commands.

Role: `moderator`<br>
Context: `room or MUC PM`<br>
Category: `utility`<br>
Usage: `,tools <on|off|status>`

#### Subcommands

- `,tools on`
  - Description: Enable utility commands in the current room.
  - Examples:
    - `,tools on` — Enable utility commands for the current room or MUC PM.

- `,tools off`
  - Description: Disable utility commands in the current room.
  - Examples:
    - `,tools off` — Disable utility commands for the current room or MUC PM.

- `,tools status`
  - Description: Show whether utility commands is enabled in the current room.
  - Examples:
    - `,tools status` — Inspect the current room setting for utility commands.

### `,ts`

Convert a Unix timestamp to your configured timezone.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,ts <unix_timestamp>`

Examples:

- `,ts 1704067200` — Convert a Unix timestamp to your configured timezone.

### `,utc`

Show current UTC time.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,utc`

Examples:

- `,utc` — Show current UTC time.
