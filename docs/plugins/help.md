# help plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

## Overview

Dynamic help for plugins and commands.

## Commands

### `,help`

Show help for plugins and commands.

Role: `none`<br>
Context: `room, MUC PM or private chat`<br>
Category: `core`<br>
Usage: `,help [all|commands|plugins|roles|categories|category <name>|room settings|<plugin>|,<command>]`

Aliases: `,h`

#### Subcommands

- `,help`
  - Description: Show the main help overview and loaded plugins.
  - Examples:
    - `,help` — Open the main help page.

- `,help commands`
  - Description: List commands visible to your role, grouped by category.
  - Examples:
    - `,help commands` — Show the command overview for your role.

- `,help plugins`
  - Description: List loaded plugins and their descriptions.
  - Examples:
    - `,help plugins` — Show all plugins visible to you.

- `,help roles`
  - Description: Show the bot role hierarchy and command access model.
  - Examples:
    - `,help roles` — Show role meanings and privilege order.

- `,help categories`
  - Description: List available help categories.
  - Examples:
    - `,help categories` — Show every command category.

- `,help category <name>`
  - Description: List commands in one help category.
  - Examples:
    - `,help category admin` — Show commands in the admin category.

- `,help room settings`
  - Description: Show how room-scoped plugins are enabled, disabled and inspected.
  - Aliases: `,help rooms settings`, `,help room plugins`, `,help rooms plugins`
  - Examples:
    - `,help room settings` — Show room plugin toggle guidance.

- `,help <plugin>`
  - Description: Show detailed help for one plugin.
  - Examples:
    - `,help rss` — Show the RSS plugin commands, subcommands and examples.

- `,help ,<command>`
  - Description: Show focused help for one command or structured subcommand.
  - Examples:
    - `,help ,rss add` — Show focused help for the RSS add subcommand.

### `,help inroom`

Enable, disable or show room help availability.

Role: `user`<br>
Context: `room or MUC PM`<br>
Category: `core`<br>
Usage: `,help inroom <on|off|status>`

Aliases: `,h inroom`

Examples:

- `,help inroom on` — Enable, disable or show room help availability.
- `,help inroom status` — Enable, disable or show room help availability.
