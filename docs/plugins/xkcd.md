# xkcd plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `fun`

## Overview

XKCD comic fetcher and broadcaster with full indexing

## Commands

### `,xkcd`

Show an XKCD comic or control room access to XKCD.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `fun`<br>
Usage: `,xkcd [on|off|status|random|number|search <term> [page]]`

#### Subcommands

- `,xkcd`
  - Description: Show the latest XKCD comic.
  - Examples:
    - `,xkcd` — Post the newest XKCD comic.

- `,xkcd random`
  - Description: Show a randomly selected XKCD comic.
  - Examples:
    - `,xkcd random` — Post a random comic from the XKCD archive.

- `,xkcd <number>`
  - Description: Show one XKCD comic by its numeric ID.
  - Examples:
    - `,xkcd 353` — Post XKCD comic number 353.

- `,xkcd search <term> [page]`
  - Description: Search XKCD titles, alt text and transcripts.
  - Examples:
    - `,xkcd search python 2` — Show page 2 of XKCD search results for 'python'.

- `,xkcd on`
  - Description: Enable XKCD posting in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,xkcd on` — Enable XKCD posting for the current room or MUC PM.

- `,xkcd off`
  - Description: Disable XKCD posting in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,xkcd off` — Disable XKCD posting for the current room or MUC PM.

- `,xkcd status`
  - Description: Show whether XKCD posting is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,xkcd status` — Inspect the current room setting for XKCD posting.
