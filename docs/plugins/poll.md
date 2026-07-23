# poll plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

Room polls with voting, history and auto-close

## Commands

### `,poll`

Create and manage polls.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `rooms`<br>
Usage: `,poll <on|off|status|create|list|show|result|history|vote|close|cancel|delete> ...`

#### Subcommands

- `,poll create [duration] | [multi[:max]] | question | option1 | option2 | ...`
  - Description: Create a single- or multiple-choice poll in the public room.
  - Context: `groupchat`
  - Examples:
    - `,poll create Tea? | yes | no` — Create a simple two-option poll.
    - `,poll create multi:2 | Lunch? | Pizza | Döner | Falafel` — Create a poll allowing up to two selected options.

- `,poll list [all|page|last]`
  - Description: List currently open polls in the room.
  - Context: `groupchat`
  - Examples:
    - `,poll list` — Show the first page of open polls.

- `,poll show <id>`
  - Description: Show one poll and its current result.
  - Aliases: `,poll result`
  - Context: `groupchat`
  - Examples:
    - `,poll show 3` — Display poll 3 and its current result.

- `,poll history [all|page|last]`
  - Description: List closed, cancelled and deleted polls.
  - Context: `groupchat`
  - Examples:
    - `,poll history` — Show recent completed polls.

- `,poll vote <id> <option-number>[,<option-number>...]`
  - Description: Cast or replace your vote in an open poll.
  - Context: `groupchat`
  - Examples:
    - `,poll vote 3 2` — Vote for option 2 in poll 3.

- `,poll close <id>`
  - Description: Close a poll and publish its final result.
  - Context: `groupchat`
  - Examples:
    - `,poll close 3` — Close poll 3 and announce the result.

- `,poll cancel <id>`
  - Description: Cancel an open poll without a normal final result.
  - Context: `groupchat`
  - Examples:
    - `,poll cancel 3` — Cancel poll 3.

- `,poll delete <id>`
  - Description: Delete one poll from the room's stored poll history.
  - Context: `groupchat`
  - Examples:
    - `,poll delete 3` — Delete poll 3 from stored history.

- `,poll on`
  - Description: Enable poll commands in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,poll on` — Enable poll commands for the current room or MUC PM.

- `,poll off`
  - Description: Disable poll commands in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,poll off` — Disable poll commands for the current room or MUC PM.

- `,poll status`
  - Description: Show whether poll commands is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,poll status` — Inspect the current room setting for poll commands.
