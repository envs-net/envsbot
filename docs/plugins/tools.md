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

Check the TLS certificate of an HTTPS website.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,cert <domain|https-url>`

Aliases: `,certificate`

Examples:

- `,cert example.org`
- `,cert https://example.org`

### `,date`

Show the current date from a stored profile timezone.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,date [nick]`

Examples:

- `,date`
- `,date Alice`

### `,echo`

Echo text back to you.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,echo <text>`

Examples:

- `,echo hello`

### `,ping`

Check whether the bot is alive.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,ping`

Aliases: `,pong`

Examples:

- `,ping`

### `,seen`

Show when a user was last seen.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,seen <nick|jid>`

Aliases: `,s`

Examples:

- `,seen alice`

### `,time`

Show the current time from a stored profile timezone.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,time [nick]`

Aliases: `,t`

Examples:

- `,time`
- `,time Alice`

### `,tools`

Enable, disable or show room access to utility commands.

Role: `moderator`<br>
Context: `room or MUC PM`<br>
Category: `utility`<br>
Usage: `,tools <on|off|status>`

Examples:

- `,tools status`

### `,ts`

Convert a Unix timestamp to your configured timezone.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,ts <unix_timestamp>`

Examples:

- `,ts 1704067200`

### `,utc`

Show current UTC time.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,utc`

Examples:

- `,utc`
