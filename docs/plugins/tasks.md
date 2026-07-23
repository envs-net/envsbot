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

#### Subcommands

- `,tasks [full] [plugin <name>] [running|failed|cancelled|done] [all|page|last]`
  - Description: List supervised tasks with optional detail, plugin and status filters.
  - Examples:
    - `,tasks` — Show a compact overview of supervised tasks.
    - `,tasks plugin rss` — Show only tasks owned by the RSS plugin.
    - `,tasks failed` — Show only failed background tasks.

- `,tasks restart <plugin>`
  - Description: Cancel and restart supervised tasks owned by one plugin.
  - Examples:
    - `,tasks restart rss` — Restart the RSS plugin's supervised tasks.

### `,tasks failed`

Show failed supervised background tasks.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,tasks failed [all|page|last]`

Aliases: `,task failed`, `,tasks errors`

Examples:

- `,tasks failed` — Show failed supervised background tasks.

### `,tasks list`

Show supervised background tasks.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,tasks list [all|page|last]`

Aliases: `,task list`

Examples:

- `,tasks list` — Show supervised background tasks.
- `,tasks list all` — Show supervised background tasks.

### `,tasks stale`

Show supervised tasks with stale heartbeats.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,tasks stale [all|page|last]`

Aliases: `,task stale`

Examples:

- `,tasks stale` — Show supervised tasks with stale heartbeats.
