# audit plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

## Overview

Admin audit log viewer

## Commands

### `,audit action`

Show recent audit events for one action/event type.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit action <event_type>`

Aliases: `,audit event`, `,audits action`, `,audits event`

Examples:

- `,audit action room_feature_changed` — Show recent audit events for one action/event type.

### `,audit errors`

Show audit events that look like errors or failures.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit errors [all|page|last]`

Aliases: `,audit failed`, `,audits errors`, `,audits failed`

Examples:

- `,audit errors` — Show audit events that look like errors or failures.
- `,audit errors all` — Show audit events that look like errors or failures.

### `,audit export`

Export recent audit events as JSON Lines.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit export [limit]`

Aliases: `,audits export`

Examples:

- `,audit export` — Export recent audit events as JSON Lines.
- `,audit export 100` — Export recent audit events as JSON Lines.

### `,audit last`

Show recent admin audit events.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit last [all|page|last|limit <n>]`

Aliases: `,audit`, `,audits last`

Examples:

- `,audit last` — Show recent admin audit events.
- `,audit last 2` — Show recent admin audit events.
- `,audit last limit 50` — Show recent admin audit events.

### `,audit prune`

Prune old audit events after confirmation.

Role: `owner`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit prune <days> [dry-run|confirm]`

Aliases: `,audits prune`

Examples:

- `,audit prune 90 dry-run` — Prune old audit events after confirmation.
- `,audit prune 90 confirm` — Prune old audit events after confirmation.

### `,audit summary`

Summarize audit activity for the last 24h or 7d.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit summary [24h|7d]`

Aliases: `,audit stats`, `,audits stats`, `,audits summary`

Examples:

- `,audit summary` — Summarize audit activity for the last 24h or 7d.
- `,audit summary 7d` — Summarize audit activity for the last 24h or 7d.

### `,audit target`

Show recent audit events for one target value.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit target <target>`

Aliases: `,audit room`, `,audits room`, `,audits target`

Examples:

- `,audit target room@conference.example.org` — Show recent audit events for one target value.

### `,audit user`

Show recent audit events for one actor JID.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,audit user <jid>`

Aliases: `,audits user`

Examples:

- `,audit user admin@example.org` — Show recent audit events for one actor JID.
