# IdleRPG plugin

The `idlerpg` plugin is an XMPP MUC adaptation of the classic IRC IdleRPG game.
Players register a character in a room, stay online, and level up by idling.
Normal room messages add penalty time to the player's timer.

The game is room-scoped. Each room has its own players, timers, items and quest
state.

## Enable the game

Room owners/admins can enable or disable IdleRPG like other room plugins:

```text
,rooms enable <room_jid> idlerpg
,rooms disable <room_jid> idlerpg
```

From a MUC private message to the bot, room admins can also use:

```text
,idlerpg on
,idlerpg off
,idlerpg enabled
```

By default, new rooms have IdleRPG disabled:

```python
ROOM_PLUGIN_DEFAULTS = {
    "idlerpg": False,
}
```

## Player commands

Use these in the game room or from a MUC private message to the bot:

```text
,idlerpg register <character> <class>
,idlerpg status [character]
,idlerpg whoami
,idlerpg top [page|last|all]
,idlerpg players [page|last|all]
,idlerpg items [character]
,idlerpg profile [character]
,idlerpg achievements [character]
,idlerpg title <achievement|none>
,idlerpg map
,idlerpg hof
,idlerpg events [page|last|all]
,idlerpg season
,idlerpg align <good|neutral|evil>
,idlerpg quest
,idlerpg login
,idlerpg logout
,idlerpg remove-me
```


`status` always shows character progress. Use `,idlerpg enabled` to inspect whether the game is enabled in the current room.

Aliases:

```text
,irpg ...
,idle ...
```

Examples:

```text
,idlerpg register Sven sysadmin
,idlerpg status
,idlerpg top
,idlerpg items Sven
,idlerpg profile Sven
,idlerpg events
,idlerpg map
,idlerpg align good
```

## How leveling works

A player levels up when their time-to-level reaches zero.

The default level timer follows the classic IdleRPG formula:

```text
TTL = rp_base * (rp_step ** current_level)
```

Defaults:

```python
IDLERPG = {
    "rp_base": 600,
    "rp_step": 1.16,
}
```

While the player is online in the room and not explicitly logged out, the bot
subtracts elapsed idle time from the timer on every game tick.

## Penalties

Normal room messages penalize registered players. By default, bot commands are
not counted as penalty messages.

```python
IDLERPG = {
    "message_penalty": 1,
    "penalty_step": 1.14,
    "logout_penalty": 20,
    "max_penalty": 604800,
    "count_command_messages": False,
}
```

The penalty formula is:

```text
penalty = base_penalty * (penalty_step ** current_level)
```

`max_penalty` caps a single penalty event. Set it to `0` to disable the cap.

## Random events, battles and items

On level-up, the player may find an item.

The game loop can also trigger rare classic IdleRPG-style events:

- PvP battles between online players
- team battles between two groups of online players
- critical strikes that add time to the defeated player's clock
- item drops and swaps after battles
- unique envs.net-flavoured items at higher levels
- item blessings that improve a random item
- item damage events that fairly reduce an existing item a little
- fair item swap/steal events where the old item is left behind
- calamities that add time to a player's timer
- godsends that remove time from a player's timer
- alignment bonuses that remove time for aligned players
- optional periodic top-player announcements and topic updates

Whenever an event changes a player's timer, the bot also prints the player's new
time to next level. Example output:

```text
Alice [42/111] has challenged Bob [13/96] in combat and won! 0 days, 00:12:10 is removed from Alice's clock.
Alice reaches next level in 0 days, 05:41:33.
Alice has dealt Bob a Critical Strike! 0 days, 00:03:20 is added to Bob's clock.
Bob reaches next level in 0 days, 09:12:44.
```

Relevant settings:

```python
IDLERPG = {
    "event_chance": 0.01,
    "item_chance": 0.20,
    "battle_event_weight": 0.55,
    "team_battle_event_weight": 0.08,
    "item_event_weight": 0.15,
    "item_damage_event_weight": 0.08,
    "item_steal_event_weight": 0.04,
    "alignment_event_weight": 0.10,
    "critical_strike_chance": 0.10,
    "item_drop_chance": 0.12,
    "unique_items_enabled": True,
    "unique_item_min_level": 25,
    "unique_item_chance": 0.025,
}
```

Battle, godsend, calamity and quest effects are configurable percentages:

```python
IDLERPG = {
    "battle_win_min_percent": 7,
    "battle_loss_min_percent": 7,
    "critical_min_percent": 5,
    "critical_max_percent": 25,
    "godsend_min_percent": 5,
    "godsend_max_percent": 12,
    "calamity_min_percent": 5,
    "calamity_max_percent": 12,
    "alignment_bonus_percent": 7,
    "quest_reward_percent": 25,
    "team_battle_percent": 20,
}
```

`battle_win_min_percent` and `battle_loss_min_percent` are minimum values. The
opponent's level can increase the final battle percentage. Critical strikes,
godsends and calamities use a random percentage within their configured range.

Unique items use predefined envs.net-themed names and are exported in each
player profile under `unique_items`. They never expose JIDs or private account
data.

## Event log

IdleRPG keeps a room-scoped recent event log. It records public game events such
as registrations, logins, level-ups, battles, critical strikes, item drops,
godsends, calamities, quest progress, team battles and season changes.

```text
,idlerpg events
,idlerpg events last
,idlerpg events all
```

Relevant settings:

```python
IDLERPG = {
    "event_log_limit": 200,
    "export_event_limit": 50,
}
```

`event_log_limit` controls how many events are kept in bot state per room.
`export_event_limit` controls how many recent events are written to
`events.json` for the website.

## Quests

When enough online players have reached the configured minimum level, the bot can
start a room quest. Quest completion removes 25% of the participating players'
remaining timer burden.

Relevant settings:

```python
IDLERPG = {
    "quest_min_level": 40,
    "quest_interval": 21600,
    "quest_min_duration": 43200,
    "quest_max_duration": 86400,
}
```

## Admin commands

Room owners/admins can adjust characters:

```text
,idlerpg push <character> <duration>
,idlerpg setlevel <character> <level>
,idlerpg reset <character>
,idlerpg delete <character>
```

Examples:

```text
,idlerpg push Sven 10m
,idlerpg setlevel Sven 12
,idlerpg reset Sven
,idlerpg delete Sven
```

## Diagnostics

IdleRPG exposes runtime state for plugin diagnostics:

```text
,plugins state idlerpg
,plugins state idlerpg <room_jid>
```

The state includes room count, player count, online player count, active quests
and running game-loop tasks.

The supervised game-loop tasks are also visible through:

```text
,tasks
,tasks all
```

## Profiles, achievements and titles

IdleRPG now tracks profile metadata and achievements per character.

```text
,idlerpg profile [character]
,idlerpg achievements [character]
,idlerpg title list
,idlerpg title <achievement-key>
,idlerpg title none
```

Achievements are unlocked by normal play, for example by registering, reaching
level milestones, winning battles, landing critical strikes, completing quests,
receiving godsends or suffering calamities.

A player can select one unlocked achievement as their public title. The title is
shown in profile/status output and in exported public JSON data.

## Live export for the website

The plugin can export public game state as JSON for a website or status page.
By default the files are written below `data/idlerpg` inside the bot checkout.
For an envs.net-style installation in `/srv/envsbot/envsbot`, that means:

```text
/srv/envsbot/envsbot/data/idlerpg/index.json
/srv/envsbot/envsbot/data/idlerpg/leaderboard.json
/srv/envsbot/envsbot/data/idlerpg/players.json
/srv/envsbot/envsbot/data/idlerpg/map.json
/srv/envsbot/envsbot/data/idlerpg/hall_of_fame.json
/srv/envsbot/envsbot/data/idlerpg/events.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/room.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/leaderboard.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/players.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/map.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/hall_of_fame.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/events.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/profiles/<character>.json
```

The top-level files mirror the first exported room for simple websites. The
room-specific directories are useful when IdleRPG is enabled in multiple rooms.

Public exports are intentionally privacy-reduced: they contain character names,
classes, public game state, events and map positions, but no raw JIDs and no
internal admin-only state. JSON files are written atomically to avoid half-written
files being read by the website.
For `idlerpg@conference.envs.net`, the room slug is usually:

```text
idlerpg_at_conference.envs.net
```

Manual refresh, limited to room owners/admins:

```text
,idlerpg export
```

### Export settings

```python
IDLERPG = {
    "export_enabled": True,
    "export_path": "data/idlerpg",
    "export_public_base_url": "",
    "export_top_limit": 50,
}
```

| Option | Default | Meaning |
| --- | ---: | --- |
| `export_enabled` | `True` | Writes public JSON files after game-state changes. Disable this when no website/status export is wanted. |
| `export_path` | `"data/idlerpg"` | Base directory for JSON exports. Relative paths are resolved from the bot checkout/base directory. Room-specific data is written below `<export_path>/<room-slug>/`. |
| `export_public_base_url` | `""` | Optional public URL for the export base. When set, commands such as `,idlerpg profile` and `,idlerpg map` can include public JSON links. |
| `export_top_limit` | `50` | Maximum number of players in exported leaderboard files. `players.json` still contains all exported players. |

### Generic website example

A standalone PHP example website is available in:

```text
contrib/idlerpg-site/index.php
```

It is intentionally generic and not tied to the envs.net website layout. Copy the
example into a PHP-capable webroot and either place exported JSON files below
`data/<room-slug>/` next to the page, or set `IDLERPG_DATA_DIR` to the export
base or room-specific directory.

Open the example with `?debug=1` to see which export paths are readable by PHP.
See `contrib/idlerpg-site/README.md` for deployment notes.

### Website data path

For the envs.net website the webroot is `/var/www/envs.net`.
There are two sane deployment variants.

Variant A: let the bot export directly into the website tree. This is usually the
simplest option because PHP/nginx only needs to read files below the webroot:

```python
IDLERPG = {
    "export_enabled": True,
    "export_path": "/var/www/envs.net/idlerpg/data",
    "export_public_base_url": "https://envs.net/idlerpg/data",
}
```

The files for the game room will then be written to:

```text
/var/www/envs.net/idlerpg/data/idlerpg_at_conference.envs.net/map.json
/var/www/envs.net/idlerpg/data/idlerpg_at_conference.envs.net/leaderboard.json
/var/www/envs.net/idlerpg/data/idlerpg_at_conference.envs.net/players.json
```

Make sure the bot can write there and the webserver can read there. Example:

```sh
sudo install -d -o envsbot -g www-data -m 0755 /var/www/envs.net/idlerpg/data
```

If the bot uses a restrictive umask, add default ACLs so newly created room
directories and JSON files stay readable by the webserver:

```sh
sudo setfacl -m u:envsbot:rwx,u:www-data:rx /var/www/envs.net/idlerpg/data
sudo setfacl -d -m u:envsbot:rwx,u:www-data:rx /var/www/envs.net/idlerpg/data
```

Variant B: keep the default bot runtime export below `/srv/envsbot/envsbot` and
let PHP read it from there. This works too, but only if the PHP/webserver user can
traverse every parent directory and read the JSON files. Test it with the actual
webserver user, for example `www-data`:

```sh
sudo -u www-data test -r /srv/envsbot/envsbot/data/idlerpg/idlerpg_at_conference.envs.net/map.json && echo readable
namei -l /srv/envsbot/envsbot/data/idlerpg/idlerpg_at_conference.envs.net/map.json
```

When using an absolute path in PHP, do not prepend `__DIR__`. This is wrong:

```php
__DIR__ . '/srv/envsbot/envsbot/data/idlerpg/idlerpg_at_conference.envs.net/map.json'
```

Use the absolute path directly instead:

```php
'/srv/envsbot/envsbot/data/idlerpg/idlerpg_at_conference.envs.net/map.json'
```

## Map

Each character has a coordinate on the room map. Online players move a little on
every game tick. Active quests include route coordinates that are exported in
`map.json` and can be rendered by the website.

```text
,idlerpg map
```

The XMPP command renders a compact text map with player markers and a legend.
The website uses the exported `map.json` for a visual map.

Example legend line:

```text
1 creme [293,133] lv.16 online
```

This means:

- `1` is the marker on the ASCII map.
- `creme` is the character name.
- `[293,133]` is the character position on the virtual map: `x=293`, `y=133`.
- `lv.16` means the character is level 16.
- `online` means the character is currently considered online by the game.

With the default map size of `500x500`, `[293,133]` is a point a little right of
the horizontal center and in the upper third of the map. These are game
coordinates only, not real-world locations.

Relevant settings:

```python
IDLERPG = {
    "map_x": 500,
    "map_y": 500,
    "map_step_per_tick": 5,
}
```

| Option | Default | Meaning |
| --- | ---: | --- |
| `map_x` | `500` | Width of the virtual game map. Exported as `width` in `map.json`. |
| `map_y` | `500` | Height of the virtual game map. Exported as `height` in `map.json`. |
| `map_step_per_tick` | `5` | Maximum movement step for online players per game tick. Set to `0` to keep coordinates static. |

## Seasons and Hall of Fame

IdleRPG can archive season winners into a room-scoped Hall of Fame.
Automatic season rollover is disabled by default to avoid surprising existing
players, but can be enabled in config.

```text
,idlerpg season
,idlerpg season hof
,idlerpg hof
```

Room owners/admins can manually end, reset or adjust a season:

```text
,idlerpg season end
,idlerpg season reset
,idlerpg season extend [duration|manual]
,idlerpg season clear-end
,idlerpg hof clear confirm
```

`season end` archives the current ranking and starts a new season without
resetting player progress. `season reset` archives the ranking and resets player
levels/items/timers for a fresh season. `season extend` extends the current
season by a duration such as `30d`, `12h` or by the configured season length
when no duration is given. `season extend manual` and `season clear-end` remove
the current end timestamp so the season runs until an admin ends or resets it.
`hof clear confirm` clears the room-scoped Hall of Fame without changing active
players.

Relevant settings:

```python
IDLERPG = {
    "season_enabled": False,
    "season_duration_days": 90,
    "season_reset_on_rollover": False,
    "season_hof_size": 10,
}
```

| Option | Default | Meaning |
| --- | ---: | --- |
| `season_enabled` | `False` | Enables automatic season rollover based on `season_duration_days`. Manual season commands are still available to room owners/admins. |
| `season_duration_days` | `90` | Season length for automatic rollover. Set to `0` to disable duration checks. |
| `season_reset_on_rollover` | `False` | If `True`, automatic rollover resets player progress after archiving the Hall of Fame entry. |
| `season_hof_size` | `10` | Number of completed seasons kept in Hall of Fame output/export. |

## Full configuration reference

All IdleRPG options live below `IDLERPG` in `config.py` / `config_sample.py`.

### Timer and leveling

| Option | Default | Meaning |
| --- | ---: | --- |
| `tick_seconds` | `60` | Game-loop interval in seconds. Each tick advances online players, moves map positions and may trigger random events. |
| `rp_base` | `600` | Base time-to-level in seconds. Level 0 starts with this value. |
| `rp_step` | `1.16` | Exponential level scaling. Higher values make later levels take longer. Formula: `TTL = rp_base * (rp_step ** current_level)`. |

### Penalties

| Option | Default | Meaning |
| --- | ---: | --- |
| `penalty_step` | `1.14` | Exponential scaling for message and logout penalties. |
| `message_penalty` | `1` | Base penalty in seconds for normal room messages. Formula: `max(1, len(body) * message_penalty) * (penalty_step ** current_level)`. |
| `logout_penalty` | `20` | Base penalty in seconds when a player logs out. |
| `logout_grace_seconds` | `300` | Grace period for short reconnects/logouts. If the player logs back in before this expires, the pending logout penalty is cleared. |
| `max_penalty` | `604800` | Maximum single penalty in seconds. The default is 7 days. Set to `0` to disable the cap. |
| `count_command_messages` | `False` | Whether bot commands also count as message penalties. Usually keep this disabled. |

### Paging and output

| Option | Default | Meaning |
| --- | ---: | --- |
| `page_size` | `10` | Number of entries per page for commands such as `top`, `players`, and some lists. |

### Random events and items

| Option | Default | Meaning |
| --- | ---: | --- |
| `event_chance` | `0.01` | Chance per room tick to trigger one random event. With a 60-second tick this is roughly a 1% chance per minute and room. |
| `item_chance` | `0.20` | Chance for a player to find an item on level-up. |
| `battle_event_weight` | `0.55` | Relative weight for PvP/random battle events when a random event is selected. |
| `team_battle_event_weight` | `0.08` | Relative weight for 3-vs-3 team battles when enough online players exist. |
| `item_event_weight` | `0.15` | Relative weight for item blessing events. |
| `item_damage_event_weight` | `0.08` | Relative weight for item damage events. |
| `item_steal_event_weight` | `0.04` | Relative weight for fair item swap/steal events. |
| `alignment_event_weight` | `0.10` | Relative weight for alignment-based group events. |
| `critical_strike_chance` | `0.10` | Chance after a battle that the winner lands a critical strike against the opponent. |
| `item_drop_chance` | `0.12` | Chance after a battle that an item is dropped/swapped. |
| `unique_items_enabled` | `True` | Enables rare named unique items. |
| `unique_item_min_level` | `25` | Minimum character level before unique items may appear. |
| `unique_item_chance` | `0.025` | Chance that a level-up item roll becomes a unique item. Unique items may grant small bonuses such as battle power, godsend rewards, reduced penalties or stronger quest rewards. |

The event weights are relative. Raising `battle_event_weight`, for example,
makes battle events more likely compared to item and alignment events.
`event_chance` still controls how often any random event starts at all.

### Events, achievements and retention

| Option | Default | Meaning |
| --- | ---: | --- |
| `event_log_limit` | `200` | Maximum number of room events kept in bot state. |
| `event_retention_days` | `90` | Maximum age for retained room events. Set to `0` to keep by count only. |
| `export_event_limit` | `50` | Maximum number of recent public events exported to `events.json`. |

Achievements are awarded automatically for long idling, level milestones,
battles, quests, unique items, godsends, calamities and item collection.
Players can inspect unlocked achievements with `,idlerpg achievements` and the
full catalog with `,idlerpg achievements list`. Room owners/admins can use
`,idlerpg stats` to inspect basic game statistics for a room.

### Quests

| Option | Default | Meaning |
| --- | ---: | --- |
| `quest_min_level` | `40` | Minimum level for players to be selected for quests. |
| `quest_interval` | `21600` | Minimum time in seconds between quest start attempts. The default is 6 hours. |
| `quest_min_duration` | `43200` | Minimum quest duration in seconds. The default is 12 hours. |
| `quest_max_duration` | `86400` | Maximum quest duration in seconds. The default is 24 hours. |

### Export, map and seasons

These options are documented in the sections above: `export_enabled`,
`export_path`, `export_public_base_url`, `export_top_limit`, `map_x`, `map_y`,
`map_step_per_tick`, `season_enabled`, `season_duration_days`,
`season_reset_on_rollover`, `season_hof_size`, `event_log_limit`,
`event_retention_days`, and `export_event_limit`.

## Room concept

There is no globally forced game room. IdleRPG is room-scoped and only active in
rooms where the plugin is enabled. Since the default is disabled, operators can
choose a dedicated game room or enable the game in selected community rooms.
