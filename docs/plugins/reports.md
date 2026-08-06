# reports plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

## Overview

Optional daily admin health report.

## Commands

### `,report`

Show or send the optional daily operational report.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,report <now|status>`

#### Subcommands

- `now`
  - Description: Generate and send the report now.
  - Examples:
    - `,report now` — Send the report immediately.

- `status`
  - Description: Show report scheduling and destination.
  - Examples:
    - `,report status` — Inspect the daily schedule.
