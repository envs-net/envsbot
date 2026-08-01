# plugins plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

## Overview

Runtime plugin management

## Commands

### `,plugin diagnose`

Show diagnostics for one plugin, including hooks, commands and tasks.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,plugin diagnose <plugin>`

Aliases: `,plugins diagnose`

Examples:

- `,plugin diagnose rss` — Show diagnostics for one plugin, including hooks, commands and tasks.

### `,plugin info`

Show metadata and source information for one plugin.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `core`<br>
Usage: `,plugin info <plugin>`

Aliases: `,plugins info`

Examples:

- `,plugin info rooms` — Show metadata and source information for one plugin.

### `,plugin list`

List loaded and available core/optional plugins.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `core`<br>
Usage: `,plugin list [all|page|last]`

Aliases: `,plugin health`, `,plugins`, `,plugins health`, `,plugins list`

Examples:

- `,plugins` — List loaded and available core/optional plugins.
- `,plugins health all` — List loaded and available core/optional plugins.
- `,plugins list` — List loaded and available core/optional plugins.

### `,plugin load`

Load one plugin or all plugins.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `core`<br>
Usage: `,plugin load <plugin|all>`

Aliases: `,plugins load`

Examples:

- `,plugin load weather` — Load one plugin or all plugins.

### `,plugin reload`

Reload one plugin or all plugins.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `core`<br>
Usage: `,plugin reload <plugin|all> [auto]`

Aliases: `,plugins reload`

Examples:

- `,plugin reload help` — Reload one plugin or all plugins.
- `,plugin reload all auto` — Reload one plugin or all plugins.

### `,plugin state`

Show plugin-provided runtime state counters.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,plugin state <plugin> [room_jid]`

Aliases: `,plugins state`

Examples:

- `,plugin state rss` — Show plugin-provided runtime state counters.
- `,plugin state poll room@conference.example.org` — Show plugin-provided runtime state counters.

### `,plugin unload`

Unload one optional plugin; core plugins are protected.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `core`<br>
Usage: `,plugin unload <plugin> [force]`

Aliases: `,plugins unload`

Examples:

- `,plugin unload weather` — Unload one optional plugin; core plugins are protected.
