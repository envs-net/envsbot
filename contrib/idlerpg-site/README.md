# IdleRPG website example

This directory contains a complete, generic PHP website for the public JSON
export produced by EnvsBot's IdleRPG plugin.

It is intentionally independent from envs.net's website layout. The page has no
framework, database, build step, JavaScript dependency or external image asset.
Copy it into a PHP-capable webroot and point it at the JSON files written by the
bot.

## Requirements

- PHP 8.0 or newer
- read access to the IdleRPG export directory
- the IdleRPG plugin configured with `export_enabled: True`

## Recommended layout

```text
public/idlerpg/index.php
public/idlerpg/data/index.json
public/idlerpg/data/<room-slug>/room.json
public/idlerpg/data/<room-slug>/leaderboard.json
public/idlerpg/data/<room-slug>/players.json
public/idlerpg/data/<room-slug>/map.json
public/idlerpg/data/<room-slug>/events.json
public/idlerpg/data/<room-slug>/hall_of_fame.json
public/idlerpg/data/<room-slug>/achievements.json
public/idlerpg/data/<room-slug>/profiles/*.json
```

The website primarily uses the room-specific exports. `room.json` provides the
season, public rules, achievement catalog and complete fallback state; the
specialized JSON files keep individual views usable if one optional file is
missing.

Example plugin config:

```python
IDLERPG = {
    "export_enabled": True,
    "export_path": "/path/to/public/idlerpg/data",
    "export_public_base_url": "https://example.org/idlerpg/data",
    "website_public_base_url": "https://example.org/idlerpg",
}
```

## Included views

The standalone site includes:

- overview dashboard, leaderboard and recent events
- searchable and paginated player directory
- complete player profiles with online state, play time, last seen, map region,
  equipment, bound unique items, bonuses, all exported statistics,
  achievements and player-specific events
- achievement catalog with unlock counts, percentages and linked earners
- current time-based or grid-based quest details and participants
- complete SVG world map with every exported player and grid-quest route
- searchable, filterable and paginated event history
- current season details and full historic season rankings
- Hall of Fame champion history
- public rules and the effective exported game configuration
- complete user and room-administration command overview
- automatic room selector when multiple IdleRPG rooms are exported
- debug view for checking which JSON paths PHP can read

## World map

The self-contained SVG map uses:

- blue circles for online players
- red circles for offline players
- orange circles for active quest participants
- numbered orange waypoints and a dashed route for grid quests
- collision-aware player labels
- clickable markers linked to public player profiles
- hover text with position, level and current state

Time-based quests intentionally have no route because they are completed by
remaining penalty-free until their deadline.

## Multiple rooms

When `index.json` contains more than one exported room, the header displays a
room selector. Room slugs may also be selected explicitly:

```text
https://example.org/idlerpg/?view=map&room=room_at_conference.example.org
```

Only room slugs already found in the export are accepted. Values containing
path separators or other unsafe characters are ignored.

## Environment variables

The page works without environment variables when the JSON files are below the
local `data/` directory. Optional overrides:

```text
IDLERPG_DATA_DIR   Export base directory or a room-specific export directory.
IDLERPG_ROOM_SLUG  Preferred room slug when no room is selected in the URL.
```

Open `?debug=1` in the browser to inspect the selected data directory and all
candidate paths.

## Deployment notes

- Point `IDLERPG_DATA_DIR` at the export base when several rooms should be
  selectable.
- Keep PHP's process user limited to read-only access where practical.
- Serve the site and exported JSON over HTTPS.
- The page escapes all values before rendering and accepts only known safe room
  slugs, but the web server should still use normal restrictive permissions.
- The export is replaced atomically by EnvsBot, so no separate synchronization
  process is required when the webroot is the configured export path.

## Privacy

The IdleRPG export intentionally contains public game state only: character
names, levels, items, achievements, events and map positions. The website does
not need raw JIDs, role assignments, bot configuration secrets or admin-only
state.
