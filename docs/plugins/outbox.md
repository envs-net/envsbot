# outbox plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

## Overview

Inspect and retry durable outbound messages.

## Commands

### `,outbox`

Inspect pending and failed durable message deliveries.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,outbox <status|dead|retry>`

#### Subcommands

- `status`
  - Description: Show queue counts and worker state.
  - Examples:
    - `,outbox status` — Inspect pending delivery state.

- `dead`
  - Description: List dead-letter messages without bodies.
  - Examples:
    - `,outbox dead` — List permanently failed deliveries.

- `retry [category]`
  - Description: Retry dead letters.
  - Examples:
    - `,outbox retry rss` — Retry failed RSS deliveries.
