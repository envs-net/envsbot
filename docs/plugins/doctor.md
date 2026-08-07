# doctor plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

## Overview

Operator health checks and runtime diagnostics.

## Commands

### `,doctor`

Run operator health checks for config, DB, rooms, plugins, tasks, performance, backups, network and release readiness.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,doctor [config|database|rooms|plugins|tasks|performance|backups|network|plugin-health|<plugin>|release|all|full] [page|last|all]`

Aliases: `,bot doctor`, `,bot health`, `,healthcheck`

#### Subcommands

- `,doctor config [page|last|all]`
  - Description: Check configuration validity, defaults and runtime consistency.
  - Examples:
    - `,doctor config` — Run configuration-specific diagnostics.

- `,doctor database [page|last|all]`
  - Description: Check database connectivity, migrations and persistence state.
  - Examples:
    - `,doctor database` — Run database-specific diagnostics.

- `,doctor rooms [page|last|all]`
  - Description: Check stored, joined and configured room state.
  - Examples:
    - `,doctor rooms` — Inspect room storage and join state.

- `,doctor plugins [page|last|all]`
  - Description: Check plugin loading, metadata and command registration.
  - Examples:
    - `,doctor plugins` — Inspect loaded plugin metadata and state.

- `,doctor tasks [full] [page|last|all]`
  - Description: Check supervised background tasks and heartbeat state.
  - Examples:
    - `,doctor tasks full` — Show detailed task diagnostics.

- `,doctor performance [full] [page|last|all]`
  - Description: Show event-loop, DB, IdleRPG, outbox, RSS and command latency diagnostics.
  - Aliases: `,doctor perf`
  - Examples:
    - `,doctor performance` — Inspect in-process performance counters.

- `,doctor backups [page|last|all]`
  - Description: Check managed backups, retention and latest archive state.
  - Examples:
    - `,doctor backups` — Inspect managed backup health.

- `,doctor network [page|last|all]`
  - Description: Check network and TLS-related runtime prerequisites.
  - Examples:
    - `,doctor network` — Run network-related health checks.

- `,doctor plugin-health [page|last|all]`
  - Description: Run every plugin-provided doctor check.
  - Examples:
    - `,doctor plugin-health` — Collect health results from all loaded plugins.

- `,doctor <plugin> [page|last|all]`
  - Description: Run doctor checks for one named plugin.
  - Examples:
    - `,doctor rss` — Run only the RSS plugin diagnostics.

- `,doctor full [page|last|all]`
  - Description: Run a detailed health sweep across all doctor sections.
  - Aliases: `,doctor all`, `,doctor details`
  - Examples:
    - `,doctor full` — Run the complete detailed health sweep.

- `,doctor release [page|last|all]`
  - Description: Run release-readiness checks for version, docs, config, syntax, database, backups and tasks.
  - Examples:
    - `,doctor release` — Run the release candidate checklist.

### `,doctor failed`

Show only failed doctor checks.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,doctor failed [page|last|all]`

Aliases: `,bot doctor failed`, `,doctor error`, `,doctor errors`

Examples:

- `,doctor failed` — Show only failed doctor checks.

### `,doctor release`

Run release-readiness checks for version, docs, config, syntax, DB, backups, tasks and plugin metadata.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,doctor release [page|last|all]`

Aliases: `,bot doctor preflight`, `,bot doctor release`, `,doctor preflight`

Examples:

- `,doctor release` — Run release-readiness checks for version, docs, config, syntax, DB, backups, tasks and plugin metadata.
- `,doctor release all` — Run release-readiness checks for version, docs, config, syntax, DB, backups, tasks and plugin metadata.

### `,doctor warnings`

Show only doctor warning lines.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,doctor warnings [page|last|all]`

Aliases: `,bot doctor warnings`, `,doctor warn`, `,doctor warning`

Examples:

- `,doctor warnings` — Show only doctor warning lines.
