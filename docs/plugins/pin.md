# pin plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

## Overview

Pin room messages with paging, search, tags, important pins and non-reply fallback.

## Commands

### `,pin`

Pin, list, search, mark important, edit, tag or delete room pins.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `rooms`<br>
Usage: `,pin <add|list|important|search|find|show|edit|tags|delete|del|remove|rm|on|off|status> ...`

#### Subcommands

- `,pin add [last [n]]`
  - Description: Pin the replied-to message or a recent room message.
  - Context: `room or MUC PM`
  - Examples:
    - `,pin add` — Pin the message you replied to.
    - `,pin add last 2` — Pin the second most recent eligible room message.

- `,pin list [page|last|all]`
  - Description: List stored pins for the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,pin list` — Show the first page of pins for the room.

- `,pin search <query> [page|last|all]`
  - Description: Search pin text, tags, authors and metadata.
  - Aliases: `,pin find`
  - Context: `room or MUC PM`
  - Examples:
    - `,pin search ssh key` — Find room pins containing the words 'ssh key'.

- `,pin show <id>`
  - Description: Show one pin with its complete metadata.
  - Context: `room or MUC PM`
  - Examples:
    - `,pin show 3` — Display pin number 3.

- `,pin edit <id> <text>`
  - Description: Replace the stored text of a pin.
  - Context: `room or MUC PM`
  - Examples:
    - `,pin edit 3 Updated room info` — Replace pin 3 with updated text.

- `,pin tags <id> [tag ...]`
  - Description: Set or clear searchable tags on a pin.
  - Aliases: `,pin tag`
  - Context: `room or MUC PM`
  - Examples:
    - `,pin tags 3 mail support` — Set the tags 'mail' and 'support' on pin 3.

- `,pin important [list|<id> on|off]`
  - Description: List important pins or change a pin's important flag.
  - Aliases: `,pin star`, `,pin unstar`
  - Context: `room or MUC PM`
  - Examples:
    - `,pin important 3 on` — Mark pin 3 as important.
    - `,pin important list` — List only important room pins.

- `,pin delete <id>`
  - Description: Delete one stored room pin.
  - Aliases: `,pin del`, `,pin remove`, `,pin rm`
  - Context: `room or MUC PM`
  - Examples:
    - `,pin delete 3` — Delete pin number 3.

- `,pin on`
  - Description: Enable the pin plugin in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,pin on` — Enable the pin plugin for the current room or MUC PM.

- `,pin off`
  - Description: Disable the pin plugin in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,pin off` — Disable the pin plugin for the current room or MUC PM.

- `,pin status`
  - Description: Show whether the pin plugin is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,pin status` — Inspect the current room setting for the pin plugin.
