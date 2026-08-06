# usage plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

## Overview

Inspect aggregate command usage and find unused commands.

## Commands

### `,commandstats`

Show aggregate command usage and commands that have never been used.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,commandstats [top|rare|unused] [days]`

Aliases: `,cmdstats`, `,usage`

#### Subcommands

- `top [days]`
  - Description: Show the most-used commands.
  - Examples:
    - `,commandstats top 30` — Show the last 30 days.

- `rare [days]`
  - Description: Show the least-used commands in the period.
  - Examples:
    - `,commandstats rare 90` — Find rarely used commands.

- `unused`
  - Description: Show registered commands never recorded.
  - Examples:
    - `,commandstats unused` — Find never-used commands.
