# IdleRPG website example

This directory contains a generic, standalone PHP example page for the IdleRPG
public JSON export.

It is intentionally not tied to envs.net's website layout. Copy it into any
PHP-capable webroot and point it at the export files written by the EnvsBot
IdleRPG plugin.

## Recommended layout

```text
public/idlerpg/index.php
public/idlerpg/data/<room-slug>/room.json
public/idlerpg/data/<room-slug>/leaderboard.json
public/idlerpg/data/<room-slug>/players.json
public/idlerpg/data/<room-slug>/map.json
public/idlerpg/data/<room-slug>/events.json
public/idlerpg/data/<room-slug>/hall_of_fame.json
```

Example plugin config:

```python
IDLERPG = {
    "export_enabled": True,
    "export_path": "/path/to/public/idlerpg/data",
    "export_public_base_url": "https://example.org/idlerpg/data",
}
```

## Environment variables

The page works without environment variables when the JSON files are below the
local `data/` directory. Optional overrides:

```text
IDLERPG_DATA_DIR   Either the export base directory or a room-specific directory.
IDLERPG_ROOM_SLUG  Room slug, for example room_at_conference.example.org.
```

Open `?debug=1` in the browser to see which data paths are readable by PHP.

## Privacy

The IdleRPG export intentionally contains public game state only: character
names, levels, items, events and map positions. It must not include raw JIDs or
admin-only data.
