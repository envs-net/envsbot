# ducks plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `games`

Duck game for MUCs with room toggles and leaderboards

## Commands

### `,bef`

Befriend the current duck.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `fun`<br>
Usage: `,bef`

Examples:

- `,bef` — Befriend the current duck.

### `,duck`

Start or interact with the duck game.

Role: `user`<br>
Context: `room / MUC PM; use rooms enable with <room_jid> from private chat`<br>
Category: `fun`<br>
Usage: `,duck <on|off|status|befriend|trap|bang|friends|top|enemies|stats [jid|nickname]>`

#### Subcommands

- `,duck befriend`
  - Description: Befriend the active duck before it leaves.
  - Aliases: `,duck bef`
  - Context: `groupchat`
  - Examples:
    - `,duck befriend` — Attempt to befriend the current room duck.

- `,duck trap`
  - Description: Set a trap for the active duck.
  - Aliases: `,duck bang`
  - Context: `groupchat`
  - Examples:
    - `,duck trap` — Attempt to trap the current room duck.
    - `,duck bang` — Catch the current room duck with a bang.

- `,duck friends`
  - Description: List the room's most successful duck friends.
  - Context: `groupchat`
  - Examples:
    - `,duck friends` — Show the duck-friend leaderboard.

- `,duck top`
  - Description: Show the combined duck game leaderboard.
  - Context: `groupchat`
  - Examples:
    - `,duck top` — Show the best duck players in the room.

- `,duck enemies`
  - Description: List the room's most successful duck trappers.
  - Context: `groupchat`
  - Examples:
    - `,duck enemies` — Show the duck-enemy leaderboard.

- `,duck stats [jid|nickname]`
  - Description: Show duck game statistics for yourself or another player.
  - Context: `groupchat`
  - Examples:
    - `,duck stats` — Show your duck game statistics.

- `,duck on`
  - Description: Enable the duck game in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,duck on` — Enable the duck game for the current room or MUC PM.

- `,duck off`
  - Description: Disable the duck game in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,duck off` — Disable the duck game for the current room or MUC PM.

- `,duck status`
  - Description: Show whether the duck game is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,duck status` — Inspect the current room setting for the duck game.

### `,duckstats`

Show duck game stats.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `fun`<br>
Usage: `,duckstats [nick]`

Examples:

- `,duckstats` — Show duck game stats.

### `,trap`

Set a trap in the duck game.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `fun`<br>
Usage: `,trap`

Aliases: `,bang`

Examples:

- `,trap` — Set a trap in the duck game.
- `,bang` — Set a trap in the duck game.
