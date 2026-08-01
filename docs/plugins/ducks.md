# ducks plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `games`

## Overview

Spawns ducks after room activity so users can befriend or trap them, with persistent room leaderboards and configurable pacing.

## Duck pacing and configuration

The duck game counts normal room messages. After a random threshold is reached, each additional eligible message gets a 1-in-`spawn_chance` roll until a duck is scheduled. `timeout = 0` keeps an active duck in the room until somebody befriends or traps it.

The defaults are intended for a medium-sized room:

```python
DUCKS = {
    "min_messages": 150,
    "max_messages": 500,
    "spawn_chance": 20,
    "max_ducks_per_day": 3,
    "timeout": 0,
    "count_commands": False,
    "state_save_every": 1,
}
```

### Example for a small or quiet room

```python
DUCKS = {
    "min_messages": 40,
    "max_messages": 150,
    "spawn_chance": 10,
    "max_ducks_per_day": 2,
    "timeout": 0,
    "count_commands": False,
    "state_save_every": 1,
}
```

### Example for a large or very active room

```python
DUCKS = {
    "min_messages": 500,
    "max_messages": 1500,
    "spawn_chance": 30,
    "max_ducks_per_day": 5,
    "timeout": 300,
    "count_commands": False,
    "state_save_every": 10,
}
```

The examples are starting points rather than strict room-size rules. A lower threshold and smaller `spawn_chance` value make ducks appear more frequently. `state_save_every` controls persistence frequency globally and is useful for reducing database writes in very active rooms.

### Per-room overrides through MUC PM

Room owners/admins and bot moderators can override gameplay pacing without changing `config.py`. Open a MUC private chat with the bot from the target room:

```text
,duck config
,duck config set min_messages 40
,duck config set max_messages 150
,duck config set spawn_chance 10
,duck config set max_ducks_per_day 2
,duck config set timeout 0
,duck config set count_commands false
,duck config unset min_messages
,duck config reset
```

Room overrides are stored persistently and survive bot restarts. `unset` removes one override; `reset` removes all overrides for the room. The operational `state_save_every` value remains global and cannot be overridden per room.

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
Usage: `,duck <on|off|status|config|befriend|trap|bang|friends|top|enemies|stats [jid|nickname]>`

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

- `,duck config [show|set <setting> <value>|unset <setting>|reset]`
  - Description: Show or override duck pacing for this room.
  - Context: `MUC PM`
  - Examples:
    - `,duck config` — Show effective duck settings for this room.
    - `,duck config set min_messages 40` — Override one room setting.
    - `,duck config unset min_messages` — Return one setting to the global default.
    - `,duck config reset` — Remove every room-specific duck override.

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
