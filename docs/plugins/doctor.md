# doctor plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

Operator health checks and runtime diagnostics.

## Commands

### `,doctor`

Run operator health checks for config, DB, rooms, plugins, tasks, backups, network, RSS and release readiness.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,doctor [config|database|rooms|plugins|tasks|backups|network|rss|release|all|full] [page|last|all]`

Aliases: `,bot doctor`, `,bot health`, `,healthcheck`

Examples:

- `,doctor`
- `,doctor full`
- `,doctor all`
- `,doctor rss`
- `,doctor tasks full`
- `,doctor release`

### `,doctor failed`

Show only failed doctor checks.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,doctor failed [page|last|all]`

Aliases: `,bot doctor failed`, `,doctor error`, `,doctor errors`

Examples:

- `,doctor failed`

### `,doctor release`

Run release-readiness checks for version, docs, config, syntax, DB, backups, tasks and plugin metadata.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,doctor release [page|last|all]`

Aliases: `,bot doctor preflight`, `,bot doctor release`, `,doctor preflight`

Examples:

- `,doctor release`
- `,doctor release all`

### `,doctor warnings`

Show only doctor warning lines.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,doctor warnings [page|last|all]`

Aliases: `,bot doctor warnings`, `,doctor warn`, `,doctor warning`

Examples:

- `,doctor warnings`
