# EnvsBot - Modular XMPP Bot Framework - [![Build Status](https://drone.envs.net/api/badges/envs/envsbot/status.svg)](https://drone.envs.net/envs/envsbot)

EnvsBot is a modular XMPP bot for rooms and direct chats, built with Python and slixmpp.
It provides a plugin-based command framework, room-specific feature toggles, user/role management, SQLite persistence, generated command documentation, vCard/avatar publishing, and a growing set of utility, community and fun plugins.

This repository is the **envs.net maintained fork** of the original EnvsBot project at [`redterminal-org/envsbot`](https://github.com/redterminal-org/envsbot).
It is developed independently from Dan's original bot and tailored for the envs.net XMPP/pubnix setup, while remaining useful for other small XMPP communities.

The bot was originally developed for the **envs pubnix/tilde** community and follows the spirit of classic tilde bots: useful, extensible, friendly in shared rooms, and easy to run on a small server.

---

## Features

* Modular plugin architecture with dynamic load, unload and reload support
* Decorator-based command registry with roles, aliases, usage metadata and generated help
* Generated command reference in [`docs/commands.md`](docs/commands.md) and runtime help guide in [`docs/help.md`](docs/help.md)
* XMPP MUC and direct-message command handling
* Room management with persistent autojoin rooms and per-room plugin toggles
* User registration, hardened role management, last-seen tracking and nickname lookup
* Safe runtime config inspection, validation and reload commands
* SQLite-backed persistence with online status checks, audit log and documented offline maintenance
* vCard and avatar support via XEP-0054, XEP-0084 and XEP-0153
* RSS/Atom feed watcher for room announcements
* URL metadata checks for links, files and YouTube videos
* Weather, vCard lookup, XMPP diagnostics, reminders, polls, pins, tell messages and utility commands
* Community/fun plugins such as ducks, dice, karma, sed corrections and XKCD
* Pytest-based test suite and Drone CI support

---

## Mirrors

* `https://git.envs.net/envs/envsbot`
* `https://github.com/envs-net/envsbot`

---

## Installation / Quickstart

Requires **Python 3.12+**.

```bash
sudo useradd -m -s /bin/bash envsbot -d /srv/envsbot
sudo su - envsbot

cd /srv/envsbot
git clone https://git.envs.net/envs/envsbot.git
cd envsbot

python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

cp config_sample.json config.json
$EDITOR config.json

cp vcard_sample.py vcard.py
$EDITOR vcard.py

python envsbot.py
```

---

## Minimal Configuration

Copy `config_sample.json` to `config.json` and set at least:

```json
{
  "jid": "envsbot@example.org",
  "password": "secret",
  "nick": "EnvsBot",
  "timezone": "Europe/Berlin",
  "owner": "admin@example.org",
  "prefix": ",",
  "db": "bot.db",
  "stop_cmd": ["/usr/bin/systemctl", "--user", "stop", "envsbot.service"],
  "avatar": "avatar.jpg",
  "avatar_type": "image/jpeg"
}
```

Optional `host` and `port` values can be used when the XMPP server address differs from the JID domain or default client port.

Runtime-safe configuration checks are available through:

```text
,config show
,config validate
,config reload
```

Secrets such as passwords and API keys are redacted in bot output.

---

## vCard and Avatar

Copy `vcard_sample.py` to `vcard.py` and adjust the bot profile. EnvsBot can publish profile data and an avatar through XMPP vCard/PEP mechanisms.

Avatar-related config keys:

```json
{
  "avatar": "avatar.jpg",
  "avatar_type": "image/jpeg"
}
```

Supported avatar MIME types are usually `image/jpeg` and `image/png`. The bot publishes the avatar hash in presence so MUC occupants can discover the avatar even if they do not have the bot in their roster.

---

## Important Commands

Examples assume the default command prefix `,`.

| Command | Description |
| --- | --- |
| `,help` | Show available help topics and commands |
| `,help all` | Show the full visible help output |
| `,help <plugin>` | Show focused help for one plugin |
| `,help <command>` | Show focused help for one command |
| `,bot status [full]` / `,status [full]` | Show compact or detailed bot, runtime, XMPP, plugin and database status |
| `,config show [all/page/last]` | Show redacted runtime configuration |
| `,config validate` | Validate `config.json` |
| `,config reload` | Reload runtime-safe configuration |
| `,audit last [limit]` | Show recent administrative audit events |
| `,audit user <jid>` | Show audit events for one actor |
| `,db status` | Show SQLite path, size and integrity status |
| `,plugins list [all/page/last]` | List loaded plugins |
| `,plugins load <name>` | Load a plugin at runtime |
| `,plugins unload <name>` | Unload a plugin at runtime |
| `,plugins reload <name>` | Reload a plugin at runtime |
| `,rooms list [all/page/last]` | List known rooms |
| `,rooms add <room_jid> <nick> [autojoin]` | Add a room to the database |
| `,rooms join <room_jid> [nick]` | Join a room immediately |
| `,rooms leave <room_jid>` | Leave a room |
| `,rooms plugins [all/page/last]` | Show plugin states for the current room |
| `,rooms enable <plugin>` | Enable a room-toggleable plugin for this room |
| `,rooms disable <plugin>` | Disable a room-toggleable plugin for this room |
| `,users roles` | Show available user roles |
| `,users admins [all/page/last]` | List privileged users |
| `,users role <jid> <role>` | Change a user's role |

For paginated commands, `all` disables paging and prints the full result set. Full reference: [`docs/commands.md`](docs/commands.md).

---

## Plugins

Core and administration:

* `_admin` - restart, shutdown and runtime status/statistics
* `_core` - shared helpers for plugins
* `_reg_profile` - startup profile, vCard and avatar publishing
* `help` - dynamic command and plugin help
* `plugins` - runtime plugin management
* `rooms` - room persistence, joining and per-room feature toggles
* `users` - user registration, roles, admin listings and last-seen tracking
* `config_cmd` - safe config inspection, validation and reload
* `audit` - admin audit log viewer
* `db` - SQLite online status checks
* `presence` - bot presence/status controls

Room, utility and community plugins:

* `birthday_notify` - birthday announcements for opted-in rooms
* `dice` - dice rolling with common notation
* `ducks` - duck game with persistent stats
* `info` - Wikipedia, Fediverse, Urban Dictionary and acronym helpers
* `karma` - room-local karma tracking
* `pin` - save and manage pinned messages
* `poll` - room polls with voting and history
* `reminder` - timed reminders
* `rss` - RSS/Atom feed watcher
* `sed` - sed-style message corrections
* `tell` - offline messages delivered when users rejoin
* `tools` - ping, echo, time/date, seen and timestamp helpers
* `urlcheck` - URL title, metadata, file and YouTube lookup
* `vcard` - public vCard lookup helpers
* `weather` - weather lookup from configured location data
* `xkcd` - latest, random, specific and searched XKCD comics
* `xmpp` - XMPP diagnostics, discovery, uptime, version and SRV checks

---

## Systemd Service

Example service unit:

```ini
[Unit]
Description=EnvsBot XMPP Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=envsbot
Group=envsbot
WorkingDirectory=/srv/envsbot/envsbot
ExecStart=/srv/envsbot/envsbot/venv/bin/python /srv/envsbot/envsbot/envsbot.py

Restart=always
RestartSec=5s
StartLimitIntervalSec=300
StartLimitBurst=10

# Give the process time to close the SQLite database before a restart.
ExecStopPost=/usr/bin/sleep 5

Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal

KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Install and start:

```bash
sudo install -m 0644 envsbot.service /etc/systemd/system/envsbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now envsbot.service
journalctl -u envsbot.service -f
```

Adjust paths, user and group for your installation.

---

## SQLite Maintenance

Use `,db status` for safe online status and integrity checks.

Do **not** run `VACUUM` from inside the live bot process. Stop the bot first and perform maintenance manually:

```bash
systemctl stop envsbot.service

sqlite3 bot.db "PRAGMA integrity_check;"
sqlite3 bot.db "PRAGMA optimize;"
sqlite3 bot.db "VACUUM;"

systemctl start envsbot.service
```

See [`docs/maintenance.md`](docs/maintenance.md).

---

## Tests and CI

Install development dependencies and run the test suite:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
pytest
```

Run without coverage when you only want a quick local check:

```bash
pytest --no-cov -q
```

Drone CI is configured in `.drone.yml`.

---

## Documentation

* [`docs/README.md`](docs/README.md) - documentation index
* [`docs/commands.md`](docs/commands.md) - generated command reference
* [`docs/help.md`](docs/help.md) - runtime help guide
* [`docs/maintenance.md`](docs/maintenance.md) - offline SQLite maintenance

Regenerate the command reference after changing command metadata:

```bash
python scripts/generate_commands_md.py
```

---

## Security Notes

* Keep `config.json` private; it contains the bot password and optional API keys.
* Use a dedicated XMPP account for the bot.
* Give Owner/Superadmin roles only to trusted administrators.
* Runtime config output redacts known secret values, but logs and local files should still be protected.
* `VACUUM` and other SQLite rewrite operations should be run only while the bot is stopped.
* Review loaded plugins before enabling them in public rooms.

---

## License

This project is licensed under the **GPL-3.0-only** license. See [`LICENSE`](LICENSE) for details. Future versions of the GPL license are explicitly excluded.
