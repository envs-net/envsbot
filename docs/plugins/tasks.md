# tasks plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

## Overview

Inspect supervised background tasks.

## Commands

### `,tasks`

Show supervised background task status.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,tasks [all|full|failed|stale|restarting|restarted|problems|running|done|cancelled] [scope|plugin <name>] [<page>|last] | ,tasks show <scope>/<task> | ,tasks restart <plugin>`

Aliases: `,bot tasks`

#### Subcommands

- `,tasks [all|full|failed|stale|restarting|restarted|problems] [scope <name>] [<page>|last]`
  - Description: Show a health overview or filtered supervised-task inventory.
  - Examples:
    - `,tasks` — Show task health, scopes and watchdog state.
    - `,tasks all` — Show the complete compact task inventory.
    - `,tasks problems` — Show only tasks needing attention.
    - `,tasks scope rss` — Show tasks owned by the RSS scope.
    - `,tasks show rss/feed-checker` — Show full detail for one task.

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
