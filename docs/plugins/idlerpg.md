# idlerpg plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `games`

IdleRPG game for MUCs, inspired by the classic IRC game

## Commands

### `,idlerpg`

Play IdleRPG in a MUC

Role: `user`<br>
Context: `groupchat / MUC PM`<br>
Category: `fun`<br>
Usage: `,idlerpg <on|off|enabled|register|status|top|players|profile|duel|events|stats|map|season|...>`

Aliases: `,idle`, `,irpg`

#### Subcommands

##### Player commands

- `,idlerpg register <character> <class>`
  - Description: Create a new IdleRPG character in the current game room.
  - Examples:
    - `,idlerpg register Sven sysadmin` — Register the character Sven with the class 'sysadmin'.

- `,idlerpg login`
  - Description: Mark your registered character as online in the current game room.
  - Examples:
    - `,idlerpg login` — Log your IdleRPG character into the game.

- `,idlerpg logout`
  - Description: Mark your character as offline without deleting it.
  - Examples:
    - `,idlerpg logout` — Log your IdleRPG character out of the game.

- `,idlerpg status [character]`
  - Description: Show progress, level, online state and next-level time.
  - Aliases: `,idlerpg me`, `,idlerpg whoami`
  - Examples:
    - `,idlerpg status` — Show your own character status.

- `,idlerpg top [page|last|all]`
  - Description: Show the character leaderboard ordered by level and progress.
  - Examples:
    - `,idlerpg top` — Show the first leaderboard page.

- `,idlerpg players [page|last|all]`
  - Description: List registered characters and their online state.
  - Aliases: `,idlerpg list`
  - Examples:
    - `,idlerpg players all` — List every registered character in the room.

- `,idlerpg items [character]`
  - Description: Show equipment and item levels for a character.
  - Examples:
    - `,idlerpg items Sven` — Show Sven's current equipment.

- `,idlerpg profile [character]`
  - Description: Show a complete character profile and website link.
  - Aliases: `,idlerpg char`, `,idlerpg character`
  - Examples:
    - `,idlerpg profile Sven` — Show Sven's full character profile.

- `,idlerpg achievements [character|list]`
  - Description: Show earned achievements or list available achievements.
  - Aliases: `,idlerpg achievement`, `,idlerpg badges`
  - Examples:
    - `,idlerpg achievements Sven` — Show achievements earned by Sven.

- `,idlerpg title <achievement|none>`
  - Description: Select an earned achievement as your visible character title.
  - Examples:
    - `,idlerpg title veteran` — Use the earned 'veteran' achievement as your title.

- `,idlerpg events [page|last|all]`
  - Description: Show recent game events and character changes.
  - Aliases: `,idlerpg eventlog`, `,idlerpg news`
  - Examples:
    - `,idlerpg events` — Show the latest IdleRPG events.

- `,idlerpg duel <character>`
  - Description: Challenge another online character to a duel.
  - Aliases: `,idlerpg challenge`
  - Examples:
    - `,idlerpg duel Alice` — Challenge Alice to a duel.

- `,idlerpg align <good|neutral|evil>`
  - Description: Set your character alignment.
  - Examples:
    - `,idlerpg align neutral` — Set your alignment to neutral.

- `,idlerpg quest`
  - Description: Show the active quest, participants, deadline and website link.
  - Examples:
    - `,idlerpg quest` — Show the current room quest.

- `,idlerpg map`
  - Description: Show character positions and the public world-map link.
  - Examples:
    - `,idlerpg map` — Show the current IdleRPG map summary.

- `,idlerpg hof`
  - Description: Show the room's Hall of Fame.
  - Aliases: `,idlerpg hall`, `,idlerpg hall-of-fame`
  - Examples:
    - `,idlerpg hof` — Show the room's Hall of Fame.

- `,idlerpg season [status]`
  - Description: Show the current season, remaining time and Hall of Fame count.
  - Examples:
    - `,idlerpg season` — Show the current season and remaining time.

- `,idlerpg remove-me`
  - Description: Permanently delete your own IdleRPG character.
  - Aliases: `,idlerpg removeme`
  - Examples:
    - `,idlerpg remove-me` — Delete your own character after confirmation handling.

##### Room owner/admin commands

- `,idlerpg stats`
  - Description: Show room-wide game balance and runtime statistics as a room owner/admin.
  - Aliases: `,idlerpg balance`
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg stats` — Show statistics for the current IdleRPG room.

- `,idlerpg hof clear confirm`
  - Description: Clear all Hall of Fame entries as a room owner/admin.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg hof clear confirm` — Clear the room's Hall of Fame after explicit confirmation.

- `,idlerpg season end`
  - Description: Archive the current ranking and start a new season without resetting players.
  - Aliases: `,idlerpg season finish`
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg season end` — End the current season while keeping player progress.

- `,idlerpg season reset`
  - Description: Archive the current ranking, start a new season and reset player progress.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg season reset` — Start a fresh season and reset every room character.

- `,idlerpg season extend [duration|manual]`
  - Description: Extend the current season, use the configured default, or make it manual/endless.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg season extend 7d` — Extend the current season by seven days.

- `,idlerpg season clear-end`
  - Description: Remove the automatic season end and make the season manual/endless.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg season clear-end` — Remove the current season deadline.

- `,idlerpg push <character> <duration>`
  - Description: Remove time from a character's next-level clock as a room owner/admin.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg push Alice 10m` — Move Alice ten minutes closer to the next level.

- `,idlerpg setlevel <character> <level>`
  - Description: Set a character's level and recalculate its timer as a room owner/admin.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg setlevel Alice 25` — Set Alice to level 25.

- `,idlerpg reset <character>`
  - Description: Reset one character's progress, items and penalties as a room owner/admin.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg reset Alice` — Reset Alice's current character progress.

- `,idlerpg delete <character>`
  - Description: Permanently delete another character as a room owner/admin.
  - Aliases: `,idlerpg remove`
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg delete Alice` — Delete Alice's room character.

- `,idlerpg export`
  - Description: Refresh the room's public IdleRPG export as a room owner/admin.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg export` — Regenerate public website data for the room.

- `,idlerpg announce top`
  - Description: Post the current leaderboard to the room as a room owner/admin.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg announce top` — Announce the current top characters in the room.

- `,idlerpg topic update [custom text]`
  - Description: Refresh the room topic from game state as a room owner/admin.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg topic update IdleRPG` — Set the generated room topic with custom prefix text.

- `,idlerpg on`
  - Description: Enable IdleRPG in the current room.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg on` — Enable IdleRPG for the current room or MUC PM.

- `,idlerpg off`
  - Description: Disable IdleRPG in the current room.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg off` — Disable IdleRPG for the current room or MUC PM.

- `,idlerpg enabled`
  - Description: Show whether IdleRPG is enabled in the current room.
  - Context: `room or MUC PM; room owner/admin`
  - Examples:
    - `,idlerpg enabled` — Inspect the current room setting for IdleRPG.
