# tasks plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

Inspect supervised background tasks.

## Commands

### `,tasks`

Show supervised background task status.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,tasks [full] [plugin <name>] [running|failed|cancelled|done] [all|page|last] | ,tasks restart <plugin>`

Aliases: `,bot tasks`

Examples:

- `,tasks`
- `,tasks full`
- `,tasks plugin rss`
- `,tasks failed`
- `,tasks restart rss`

### `,tasks failed`

Show failed supervised background tasks.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,tasks failed [all|page|last]`

Aliases: `,task failed`, `,tasks errors`

Examples:

- `,tasks failed`

### `,tasks list`

Show supervised background tasks.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,tasks list [all|page|last]`

Aliases: `,task list`

Examples:

- `,tasks list`
- `,tasks list all`

### `,tasks stale`

Show supervised tasks with stale heartbeats.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,tasks stale [all|page|last]`

Aliases: `,task stale`

Examples:

- `,tasks stale`
