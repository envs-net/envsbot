# xmpp plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `tools`

XMPP utility tools (ping, diagnostics, service discovery, DNS SRV, etc.)

## Commands

### `,xmpp`

Enable, disable or show room access to XMPP lookup commands.

Role: `user`<br>
Context: `room or MUC PM`<br>
Category: `xmpp`<br>
Usage: `,xmpp <on|off|status>`

Aliases: `,x`

Examples:

- `,xmpp status`

### `,xmpp check`

Run combined XMPP service diagnostics.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp check <domain|jid>`

Aliases: `,x check`

Examples:

- `,x check envs.net`
- `,x check conference.envs.net`

### `,xmpp compliance`

Check XMPP compliance features via disco.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp compliance <jid>`

Aliases: `,x compliance`

Examples:

- `,x compliance envs.net`

### `,xmpp contact`

Show contact addresses from service discovery.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp contact <jid>`

Aliases: `,x contact`

Examples:

- `,x contact envs.net`

### `,xmpp help`

Show help for XMPP lookup subcommands.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp help`

Aliases: `,x help`

Examples:

- `,x help`

### `,xmpp info`

Show service discovery identity/features.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp info <jid>`

Aliases: `,x info`

Examples:

- `,x info conference.envs.net`

### `,xmpp items`

List service discovery items.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp items <jid>`

Aliases: `,x items`

Examples:

- `,x items envs.net`

### `,xmpp ping`

Ping an XMPP entity.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp ping <jid>`

Aliases: `,x ping`

Examples:

- `,x ping envs.net`

### `,xmpp srv`

Look up XMPP DNS SRV records.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp srv <domain>`

Aliases: `,x srv`

Examples:

- `,x srv envs.net`

### `,xmpp uptime`

Query XMPP entity uptime.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp uptime <jid>`

Aliases: `,x uptime`

Examples:

- `,x uptime envs.net`

### `,xmpp version`

Query XMPP software version via XEP-0092.

Role: `user`<br>
Context: `any`<br>
Category: `xmpp`<br>
Usage: `,xmpp version <jid>`

Aliases: `,x version`

Examples:

- `,x version envs.net`
