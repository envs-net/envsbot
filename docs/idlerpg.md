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
,idlerpg duel <character>
,idlerpg quest
,idlerpg login
,idlerpg logout
,idlerpg remove-me
```


`status` always shows character progress. Use `,idlerpg enabled` to inspect whether the game is enabled in the current room.

Manual duels are optional player-triggered battles. Both characters must be online, not logged out, within the configured map distance, and outside their duel cooldown. Members of the same active quest may duel while they are separated, but once they occupy the same map point they cannot manually duel each other. This especially prevents grid-quest companions from repeatedly dueling after their directed paths converge. The default maximum distance is 10 map units and the default cooldown is 1 hour for both duelists.

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
,idlerpg duel Sven
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
- boss events where 3-5 eligible online players fight a room boss together
- critical strikes that add time to the defeated player's clock
- level-up battles, with classic odds below/above level 25
- rare item drops and swaps after battles
- tiered envs.net-flavoured unique artifacts, including protected upgrades at high levels
- item blessings that improve a random item
- item damage events that fairly reduce an existing item a little
- fair item swap/steal events where the old item is left behind
- calamities that add time to a player's timer
- godsends that remove time from a player's timer
- alignment bonuses that remove time for aligned players
- optional periodic top-player announcements and topic updates with configurable custom topic text

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
    "boss_event_weight": 0.06,
    "item_event_weight": 0.15,
    "item_damage_event_weight": 0.08,
    "item_steal_event_weight": 0.04,
    "alignment_event_weight": 0.10,
    "critical_strike_chance": 1 / 35,
    "critical_strike_chance_good": 1 / 50,
    "critical_strike_chance_evil": 1 / 20,
    "item_drop_chance": 0.02,
    "level_battle_chance_below_25": 0.25,
    "level_battle_chance_at_25": 1.0,
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
    "boss_min_players": 3,
    "boss_max_players": 5,
    "boss_min_level": 10,
    "boss_reward_percent": 12,
    "boss_loss_percent": 4,
    "boss_power_min_factor": 0.75,
    "boss_power_max_factor": 1.25,
    "manual_duel_max_distance": 10,
    "manual_duel_cooldown_seconds": 3600,
}
```

`manual_duel_max_distance` limits player-triggered duels to nearby characters on the map. `manual_duel_cooldown_seconds` applies to both duelists after a manual duel so one player cannot be challenged repeatedly.

`battle_win_min_percent` and `battle_loss_min_percent` are minimum values. The
opponent's level can increase the final battle percentage. Critical strikes,
godsends and calamities use a random percentage within their configured range.

Boss events require at least `boss_min_players` online players at or above
`boss_min_level`. Boss power is drawn between `boss_power_min_factor` and
`boss_power_max_factor` times the selected party's power (0.75-1.25 by default).
If the party defeats the boss, each participant receives a TTL reduction and can
unlock the `Boss Slayer` / `Raid Veteran` achievements. If the party fails, each
participant receives a small configured setback.

Unique items use predefined envs.net-themed names and are exported in each
player profile under `unique_items`. Every equipment slot, including gloves and
leggings, can receive a bound unique artifact. Higher tiers unlock at levels 75,
85, 100 and 125. A later drop may upgrade an occupied unique slot only when its
catalog tier is higher and its rolled item level is strictly greater; equal,
weaker or unknown items are never replaced. Unique artifacts remain protected
from damage, theft and ordinary item swaps. They never expose JIDs or private
account data.

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
    "export_full_season_events": False,
    "export_season_event_chunk_size": 1000,
}
```

`event_log_limit` controls the compact recent-event log used by bot commands.
`export_event_limit` controls how many recent events are written to
`events.json` for lightweight consumers. When `export_full_season_events` is
enabled, `season_events.json` becomes a small chunk manifest and the complete
active-season history is stored in append-friendly `season-events/NNNNNN.json`
files. Automatic exports query SQLite only for events appended since the last
successful export and normally rewrite only the final partial chunk or create a
new chunk. A season rollover performs a clean full rebuild; disabling the option
removes both the manifest and generated chunks.

## Quests

When enough online players have reached the configured minimum level and have
been online long enough, the bot can start a room quest. By default the online
time requirement is 10 hours, matching classic IdleRPG. Quest completion removes
25% of the participating players' remaining timer burden.

Physical MUC presence is part of the game state as well. When a registered
character leaves the game room, IdleRPG starts the same logout grace period as
for an explicit `,idlerpg logout`. Returning before the grace expires cancels
that presence-triggered penalty. Remaining offline past the grace adds the
configured logout penalty to the character clock. Nick changes and a second
session of the same real JID do not count as logouts. Accumulated message,
logout and quest penalties are shown by `,idlerpg status` and exported in the
public player profile.

The bot supports both classic quest types:

- **Grid quests**: four questers automatically walk toward a route containing
  `quest_grid_min_points` to `quest_grid_max_points` waypoints (2-3 by default)
  on the world map. If they do not finish before the configured deadline, only the
  assigned questers receive a p15 quest penalty.
- **Time quests**: four questers must remain online and avoid message or logout
  penalties until a random 12-24h timer ends. Such a penalty against any
  quester fails the quest, and only the assigned questers receive the p15 quest
  penalty. Random battles and other game events may still change a quester's
  clock without failing the time quest. Logout grace applies, so short XMPP
  reconnects do not immediately destroy it.

Automatic quest starts are additionally capped by `quest_max_per_day` per UTC
day (default: 2; `0` means unlimited).

Relevant settings:

```python
IDLERPG = {
    "quest_min_level": 40,
    "quest_min_online_seconds": 36000,
    "quest_interval": 21600,
    "quest_max_per_day": 2,
    "quest_grid_enabled": True,
    "quest_grid_weight": 0.5,
    "quest_grid_min_points": 2,
    "quest_grid_max_points": 3,
    "quest_min_duration": 43200,
    "quest_max_duration": 86400,
    "quest_time_enabled": True,
    "quest_time_weight": 0.5,
    "quest_time_min_duration": 43200,
    "quest_time_max_duration": 86400,
}
```

## Admin commands

Room owners/admins can adjust characters:

```text
,idlerpg push <character> <duration>
,idlerpg setlevel <character> <level>
,idlerpg reset <character>
,idlerpg delete <character>
,idlerpg delold <days> [confirm]
```

Examples:

```text
,idlerpg push Sven 10m
,idlerpg setlevel Sven 12
,idlerpg reset Sven
,idlerpg delete Sven
,idlerpg delold 90
,idlerpg delold 90 confirm
```

`delold` only targets characters that are currently offline and whose latest
known activity is at least the requested number of days old. The first form is
a preview; deletion requires the explicit `confirm` argument. Active quest
participants and currently online characters are never selected, and archived
Hall of Fame rankings are left unchanged.

## Diagnostics

IdleRPG exposes runtime state for plugin diagnostics:

```text
,plugins state idlerpg
,plugins state idlerpg <room_jid>
```

The state includes room count, player count, online player count, active quests
and running game-loop tasks. On installations using the current database schema,
it also reports normalized SQLite row counts and the most recent public-export
duration, file size and exported room/player/event counts.

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

`level_reward_min_level` (default: 50) controls the minimum level for
level-gated reward badges. With `season_achievement_gates_enabled = True`,
long-term achievements are also gated by season age so a fresh season cannot
immediately award milestones intended to represent sustained play.

### Login, ranking and room-topic announcements

```python
IDLERPG = {
    "announce_login": True,
    "announce_top_interval": 21600,
    "announce_top_limit": 5,
    "update_room_topic": False,
    "topic_update_interval": 14400,
    "topic_custom_text": "",
}
```

`announce_login` controls player-login announcements. Automatic top-player
announcements use the configured interval and limit; setting
`announce_top_interval` to `0` disables them. Room-topic updates are opt-in;
when enabled, `topic_update_interval` limits their frequency and
`topic_custom_text` can prepend operator-defined text.

## Persistence and live export

IdleRPG state is persisted in normalized SQLite tables for rooms, players,
seasons and events. Existing installations are migrated automatically from the
legacy plugin-global JSON blob on first access after the database migration.
The migration is transactional; after a successful copy the legacy blob is
removed. No manual conversion command is required.

The in-memory game model keeps only the bounded recent event feed used by
commands and normal website views. Full active-season history is append-only in
SQLite and is loaded on demand only when `export_full_season_events` requires
it. Newly created events are kept in a short-lived pending buffer until a
successful database save, so events cannot be lost merely because the recent
feed was pruned before persistence. Room-scoped saves update only the affected
room/player/season rows instead of re-walking every IdleRPG room after each
action.

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
/srv/envsbot/envsbot/data/idlerpg/season_events.json
/srv/envsbot/envsbot/data/idlerpg/achievements.json
/srv/envsbot/envsbot/data/idlerpg/artifacts.json
/srv/envsbot/envsbot/data/idlerpg/generation.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/room.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/leaderboard.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/players.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/map.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/hall_of_fame.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/events.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/season_events.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/achievements.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/artifacts.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/generation.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/season-events/000001.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/season-events/000002.json
/srv/envsbot/envsbot/data/idlerpg/<room-slug>/profiles/<character>.json
```

The top-level files mirror the first exported room for simple websites. The
room-specific directories are useful when IdleRPG is enabled in multiple rooms.

Public exports are intentionally privacy-reduced: they contain character names,
classes, public game state, events and map positions, but no raw JIDs and no
internal admin-only state. Snapshot creation happens before the export is queued;
JSON serialization and filesystem work then run in a worker thread so a large
export cannot block XMPP message processing. Concurrent automatic exports are
coalesced by an export lock.

The exporter performs content-aware delta writes: unchanged JSON files are not
rewritten, while changed files are atomically replaced and stale generated files
are removed. `generation.json` is published only after the generation's files are
in place and contains SHA-256 hashes for the committed snapshot. Readers that
understand the `envsbot-generation-v1` manifest can verify every file and retry
if an export changes mid-read instead of combining old and new generations. The
bundled PHP example does this (up to five attempts, 20 ms apart) and falls back
to a temporary unavailable response rather than rendering a mixed snapshot.
Legacy readers can continue to consume the individual atomically written JSON
files. Existing export trees are bootstrapped with generation manifests on the
first compatible export.
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
    "export_interval_seconds": 300,
    "export_path": "data/idlerpg",
    "export_public_base_url": "",
    "website_public_base_url": "",
    "export_top_limit": 50,
}
```

| Option | Default | Meaning |
| --- | ---: | --- |
| `export_enabled` | `True` | Enables the public JSON website/status export. Disable this when no public export is wanted. |
| `export_interval_seconds` | `300` | Minimum interval between automatic export refreshes, independent of `tick_seconds`. Startup, room `on`/`off` and `,idlerpg export` still refresh immediately. Set to `0` for the legacy behavior of exporting after every state change. |
| `export_path` | `"data/idlerpg"` | Base directory for JSON exports. Relative paths are resolved from the bot checkout/base directory. Room-specific data is written below `<export_path>/<room-slug>/`. |
| `export_public_base_url` | `""` | Optional public URL for the JSON export base. This is used inside exported metadata and for raw data access. |
| `website_public_base_url` | `""` | Optional human-facing IdleRPG website root used in chat output. When empty and `export_public_base_url` ends in `/data`, the parent URL is derived automatically. |
| `export_top_limit` | `50` | Maximum number of players in exported leaderboard files. `players.json` still contains all exported players. |

Chat output now links to website views such as `?view=quest`, `?view=map` and `?view=players&character=...` instead of exposing raw JSON files.

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
    "export_interval_seconds": 300,
    "export_path": "/var/www/envs.net/idlerpg/data",
    "export_public_base_url": "https://envs.net/idlerpg/data",
    "website_public_base_url": "https://envs.net/idlerpg",
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

The generated recommended systemd unit intentionally uses `UMask=0077` for private bot
data. IdleRPG public exports explicitly add read/traverse access to generated
room directories and JSON files, resulting in `0755` directories and `0644`
files when no broader ACL or mode already exists. The pre-existing export base
and all parent directories still need to be traversable by the webserver.
Default ACLs remain useful when a deployment requires access for a specific
webserver group instead of public read access.

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

Each character has a coordinate on the room map. The movement model follows the
classic IdleRPG grid system: online players are simulated once per elapsed
second, with equal chances to step left, right or neither and equal chances to
step up, down or neither. Active grid quests include route coordinates that are
exported in `map.json` and can be rendered by the website. Questers walk toward
the current quest point more slowly than normal random movement.

```text
,idlerpg map
```

The XMPP command renders a compact text map with player markers and a legend.
The website uses the exported `map.json` for a visual map. Online players use
blue circular markers, offline players use red circular markers and active
quest participants use orange circular markers. Grid-quest route points are
shown as orange squares connected by an orange line.

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
    "map_step_per_second": 1,
    "grid_battle_enabled": True,
    "quest_grid_step_seconds": 30,
}
```

| Option | Default | Meaning |
| --- | ---: | --- |
| `map_x` | `500` | Width of the virtual game map. Exported as `width` in `map.json`. |
| `map_y` | `500` | Height of the virtual game map. Exported as `height` in `map.json`. |
| `map_step_per_second` | `1` | Grid step size for original-style per-second random walking. Set to `0` to keep coordinates static. |
| `map_step_per_tick` | `1` | Legacy alias for `map_step_per_second`; kept for old configs. |
| `grid_battle_enabled` | `True` | Allow original-style grid encounters when multiple online players meet on the same coordinate. |
| `quest_grid_step_seconds` | `30` | Seconds per directed quest step. On the default 500x500 map this normally keeps grid quests active for several hours; higher values make them slower. |

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
,idlerpg season discard confirm
,idlerpg season extend [duration|manual]
,idlerpg season clear-end
,idlerpg hof clear confirm
```

`season end` archives the current ranking and starts a new season without
resetting player progress. `season reset` archives the ranking and resets player
levels, items, timers, achievements and game statistics for a fresh season.
Character identity and registration history remain intact. `season discard confirm`
is the emergency recovery command for a faulty active season: it does not add a
Hall of Fame entry, removes events created after that season started, cancels the
active quest and applies the same full player reset before starting a clean new
season. Existing Hall of Fame entries remain untouched. `season extend` extends
the current season by a duration such as `30d`, `12h` or by the
configured season length when no duration is given. `season extend manual` and
`season clear-end` remove the current end timestamp so the season runs until an
admin ends or resets it.
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
| `rp_step` | `1.16` | Exponential level scaling through level 60. From level 61 onward the classic IdleRPG rule uses the level-60 TTL plus one additional day per level. |

### Penalties

| Option | Default | Meaning |
| --- | ---: | --- |
| `penalty_step` | `1.14` | Exponential scaling for message and logout penalties. |
| `message_penalty` | `1` | Base penalty in seconds for normal room messages. Formula: `max(1, len(body) * message_penalty) * (penalty_step ** current_level)`. |
| `logout_penalty` | `20` | Base penalty in seconds when a player explicitly logs out or leaves the game MUC long enough to exceed the logout grace period. |
| `logout_grace_seconds` | `300` | Grace period for short reconnects/logouts. Presence-triggered departures and explicit logouts are penalized only after this period; a presence-triggered reconnect before expiry cancels the pending penalty. |
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
| `critical_strike_chance` | `1 / 35` | Neutral critical-strike chance after a battle. |
| `critical_strike_chance_good` | `1 / 50` | Good players' classic critical-strike chance. |
| `critical_strike_chance_evil` | `1 / 20` | Evil players' classic critical-strike chance. |
| `item_drop_chance` | `0.02` | Chance after a battle that the winner steals/swaps one better item from the loser. |
| `level_battle_chance_below_25` | `0.25` | Chance that a level-up below level 25 triggers a battle. |
| `level_battle_chance_at_25` | `1.0` | Chance that a level-up at level 25 or higher triggers a battle. |
| `unique_items_enabled` | `True` | Enables rare named unique items. |
| `unique_item_min_level` | `25` | Minimum character level before unique items may appear. |
| `unique_item_chance` | `0.025` | Chance that a level-up item roll becomes a unique item or a strictly stronger tier upgrade. Unique artifacts cover all equipment slots and may grant small bonuses such as battle power, godsend rewards, reduced penalties or stronger quest rewards. |
| `boss_power_min_factor` | `0.75` | Minimum multiplier applied to the selected party power when generating a boss. |
| `boss_power_max_factor` | `1.25` | Maximum multiplier applied to the selected party power when generating a boss. |

The event weights are relative. Raising `battle_event_weight`, for example,
makes battle events more likely compared to item and alignment events.
`event_chance` still controls how often any random event starts at all.

### Events, achievements and retention

| Option | Default | Meaning |
| --- | ---: | --- |
| `event_log_limit` | `200` | Maximum number of events kept in the compact recent-event log used by bot commands and `events.json`. |
| `event_retention_days` | `90` | Maximum age for completed-season event rows and the compact recent-event cache. Set to `0` to disable age pruning. Active-season history and currently retained recent events are never removed. |
| `export_event_limit` | `50` | Maximum number of recent public events exported to `events.json`. |
| `export_full_season_events` | `False` | Export the complete active-season history through a small `season_events.json` manifest plus append-friendly `season-events/*.json` chunks. When disabled, only the limited `events.json` feed is published and stale full-season files/chunks are removed. |
| `export_season_event_chunk_size` | `1000` | Maximum events per full-season export chunk. Changing it causes the next automatic export to rebuild the active-season chunk set safely. |
| `level_reward_min_level` | `50` | Minimum level for level-gated reward badges. |
| `season_achievement_gates_enabled` | `True` | Gate long-term achievements by season age so they represent sustained play in the current season. |
| `announce_login` | `True` | Announce player logins in the game room. |
| `announce_top_interval` | `21600` | Interval in seconds between automatic top-player announcements. |
| `announce_top_limit` | `5` | Number of players included in automatic top-player announcements. |
| `update_room_topic` | `False` | Allow IdleRPG to update the MUC subject/topic. |
| `topic_update_interval` | `14400` | Minimum seconds between IdleRPG room-topic updates. |
| `topic_custom_text` | `""` | Optional custom prefix for IdleRPG room topics. |

Achievements are awarded automatically for long idling, level milestones,
battles, quests, unique items, godsends, calamities and item collection.
Players can inspect unlocked achievements with `,idlerpg achievements` and the
full catalog with `,idlerpg achievements list`. Room owners/admins can use
`,idlerpg stats` to inspect basic game statistics for a room.

### Quests

| Option | Default | Meaning |
| --- | ---: | --- |
| `quest_min_level` | `40` | Minimum level for players to be selected for quests. |
| `quest_min_online_seconds` | `36000` | Minimum continuous online time before a player can be selected for a quest. The default is 10 hours, matching classic IdleRPG behaviour. |
| `quest_interval` | `21600` | Minimum time in seconds between quest start attempts. The default is 6 hours. |
| `quest_max_per_day` | `2` | Maximum automatically started quests per UTC day. Set to `0` for no daily cap. |
| `quest_grid_enabled` | `True` | Enable grid-based route quests. |
| `quest_grid_weight` | `0.5` | Relative selection weight for grid quests when both quest types are enabled. |
| `quest_grid_min_points` | `2` | Minimum number of route waypoints for a grid quest. |
| `quest_grid_max_points` | `3` | Maximum number of route waypoints for a grid quest. |
| `quest_min_duration` | `43200` | Minimum grid quest deadline in seconds. The default is 12 hours. |
| `quest_max_duration` | `86400` | Maximum grid quest deadline in seconds. The default is 24 hours. If the route is not completed before the deadline, online players receive a p15 quest penalty. |
| `quest_time_enabled` | `True` | Enable time-based idle endurance quests. |
| `quest_time_weight` | `0.5` | Relative selection weight for time quests when both quest types are enabled. |
| `quest_time_min_duration` | `43200` | Minimum time-based quest duration in seconds. The default is 12 hours. |
| `quest_time_max_duration` | `86400` | Maximum time-based quest duration in seconds. The default is 24 hours. |

### Export, map and seasons

These options are documented in the sections above: `export_enabled`,
`export_interval_seconds`, `export_path`, `export_public_base_url`, `website_public_base_url`, `export_top_limit`, `map_x`, `map_y`,
`map_step_per_second`, `map_step_per_tick`, `grid_battle_enabled`,
`quest_grid_step_seconds`, `quest_min_online_seconds`, `quest_grid_enabled`, `quest_grid_weight`,
`quest_time_enabled`, `quest_time_weight`, `quest_time_min_duration`, `quest_time_max_duration`,
`season_enabled`, `season_duration_days`,
`season_reset_on_rollover`, `season_hof_size`, `event_log_limit`,
`event_retention_days`, `export_event_limit`, `export_full_season_events`,
`export_season_event_chunk_size`, `quest_max_per_day`, `quest_grid_min_points`,
`quest_grid_max_points`, `boss_power_min_factor`, `boss_power_max_factor`,
`announce_login`, `announce_top_interval`, `announce_top_limit`,
`update_room_topic`, `topic_update_interval`, `topic_custom_text`,
`level_reward_min_level`, and `season_achievement_gates_enabled`.

## Room concept

There is no globally forced game room. IdleRPG is room-scoped and only active in
rooms where the plugin is enabled. Since the default is disabled, operators can
choose a dedicated game room or enable the game in selected community rooms.
