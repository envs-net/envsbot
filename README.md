# EnvsBot - Modular XMPP Bot Framework - [![Build Status](https://drone.envs.net/api/badges/envs/envsbot/status.svg)](https://drone.envs.net/envs/envsbot)

EnvsBot is a modular XMPP bot for rooms and direct chats, built with Python and slixmpp.
It provides a plugin-based command framework, room-specific feature toggles, user/role management, SQLite persistence, generated command documentation, vCard/avatar publishing, and a growing set of utility, community and fun plugins.

This repository is the **envs.net maintained fork** of the XMPPBot project at [`redterminal-org/XMPPBot`](https://github.com/redterminal-org/XMPPBot).
It is developed independently from Dan's original bot and tailored for the envs.net XMPP/pubnix setup, while remaining useful for other small XMPP communities.

The bot was originally developed for the **envs pubnix/tilde** community and follows the spirit of classic tilde bots: useful, extensible, friendly in shared rooms, and easy to run on a small server.

---

## Features

* Modular plugin architecture with dynamic load, unload and reload support
* Decorator-based command registry with roles, aliases, usage metadata and generated help
* Practical tutorial in [`docs/tutorial.md`](docs/tutorial.md), generated command overview in [`docs/commands.md`](docs/commands.md), plugin guides in [`docs/plugins/`](docs/plugins/), runtime help guide in [`docs/help.md`](docs/help.md), diagnostics guide in [`docs/diagnostics.md`](docs/diagnostics.md), and architecture overview in [`docs/architecture.md`](docs/architecture.md)
* XMPP MUC and direct-message command handling
* Room management with persistent autojoin rooms and per-room plugin toggles
* User registration, hardened role management, last-seen tracking and nickname lookup
* Safe runtime config inspection, validation and reload commands
* Built-in version command and optional GitHub release update checks
* SQLite-backed persistence with doctor checks, audit log, managed ZIP backups and documented offline maintenance
* vCard and avatar support via XEP-0054, XEP-0084 and XEP-0153
* RSS/Atom feed watcher for room announcements
* URL metadata checks for links, files and YouTube videos
* Shared persistent recent-message cache for reply-aware plugins
* Weather, translation, vCard lookup, XMPP diagnostics, reminders, polls, pins, tell messages and utility commands
* Community/fun plugins such as IdleRPG, ducks, dice, karma, sed corrections and XKCD
* Pytest-based test suite and Drone CI support

---

## Mirrors

* `https://git.envs.net/envs/envsbot`
* `https://github.com/envs-net/envsbot`

---

## Installation / Quickstart

Requires **Python 3.12+**.

For production installations, use the **latest tagged release** instead of the
`main` branch. The `main` branch is the active development branch and may contain
changes that are not part of a stable release yet.

The quickstart below automatically checks out the newest local version-sorted tag.
You can also replace `LATEST_TAG` with an explicit release such as `vX.Y.Z`.

```bash
sudo useradd -m -s /bin/bash envsbot -d /srv/envsbot
sudo su - envsbot

cd /srv/envsbot
git clone https://git.envs.net/envs/envsbot.git .
git fetch --tags
LATEST_TAG="$(git tag --sort=-v:refname | head -n1)"
git checkout "$LATEST_TAG"
echo "Using EnvsBot release $LATEST_TAG"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .

cp config_sample.py config.py
$EDITOR config.py

cp vcard_sample.py vcard.py
$EDITOR vcard.py

envsbot --check
envsbot
```

---

## Updating

Use tagged releases for updates as well. Do not update a production bot by
blindly pulling `main`.

Example update flow for a systemd installation:

```bash
sudo systemctl stop envsbot.service

sudo su - envsbot
cd /srv/envsbot
git fetch --tags
LATEST_TAG="$(git tag --sort=-v:refname | head -n1)"
git checkout "$LATEST_TAG"
echo "Using EnvsBot release $LATEST_TAG"

source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
envsbot --check
exit

sudo systemctl start envsbot.service
sudo journalctl -u envsbot.service -f
```

Before updating, keep a copy of `config.py`, `vcard.py` and `bot.db`, or create
a managed bot backup with `,backup`. After updating, check `config_sample.py` for
new options and compare your live config with `,config diff`.

---

## Minimal Configuration

Copy `config_sample.py` to `config.py` and set at least:

```python
JID = "envsbot@example.org"
PASSWORD = "secret"
NICK = "EnvsBot"
RESOURCE = "service"  # optional; set None to let server choose
OWNER = "admin@example.org"

COMMAND_PREFIX = ","
TIMEZONE = "Europe/Berlin"
DB_FILE = "bot.db"
STOP_CMD = ["/usr/bin/systemctl", "--user", "stop", "envsbot.service"]

AVATAR_PATH = "data/avatar.jpg"
AVATAR_TYPE = "image/jpeg"
```

Optional `CONNECT_HOST`, `CONNECT_PORT` and `CONNECT_DIRECT_TLS` values can be
used when the XMPP server address differs from the JID domain, default client
port or STARTTLS mode. For direct TLS, set:

```python
CONNECT_DIRECT_TLS = True
CONNECT_PORT = 5223
```

`config_sample.py` also contains operator tuning sections for network timeouts, default pagination, URL checks, RSS backoff and per-poll burst limits, birthday scans, sed/poll/pin limits, anti-spam delays and XKCD indexing. These values are safe to adjust without editing plugin code.

`DEFAULT_PAGINATION = "all"` makes paginated commands show all entries by default. Set it to a positive integer, for example `20`, to show page 1 with that many entries unless the user explicitly passes `all`, `last` or a page number.

Runtime-safe configuration checks are available through:

```text
,config show
,config diff
,config search rss
,config set LOG_LEVEL DEBUG
,config unset LOG_LEVEL
,config validate
,config reload
```

Secrets such as passwords and API keys are redacted in bot output. `,config set` rejects startup-only, secret and protected options.

Optional release update checks can be enabled with:

```python
VERSION_CHECK_ENABLED = True
VERSION_CHECK_INTERVAL = 3600
VERSION_CHECK_URL = "https://github.com/envs-net/envsbot/releases/latest"
VERSION_CHECK_NOTIFY_JID = "admin@example.org"
```

When `VERSION_CHECK_NOTIFY_JID` is empty, automatic update notifications are sent to the configured `owner` JID.
If `VERSION_CHECK_NOTIFY_JID` is a MUC room JID, EnvsBot joins that room before sending the notification and uses a groupchat message.
The notification room is joined at send time and is not automatically added to the stored room list unless you also add it with `,rooms add` or `,rooms join`.
Manual checks through `,checkupdate` work even when the periodic worker is disabled.

Incoming MUC invites can be reviewed before the bot joins the invited room:

```python
ROOM_INVITES_ENABLED = True
ROOM_INVITE_NOTIFY_JID = ""  # empty = VERSION_CHECK_NOTIFY_JID, then OWNER
ROOM_INVITE_MAX_AGE_DAYS = 30
```

When invited to a room, EnvsBot stores a pending invite and notifies `ROOM_INVITE_NOTIFY_JID`, `VERSION_CHECK_NOTIFY_JID`, or the configured `owner`.
If the notification target is a MUC room, the bot joins it before sending the approval message.
The bot does not join the invited room until an admin accepts the invite with `,rooms invite accept <id>`.
Declined invites are removed with `,rooms invite decline <id>`.

For migration, legacy `config.json` is still accepted when no `config.py` exists, but new installations should use the Python config file. The JSON sample is no longer maintained.

---

## vCard and Avatar

Copy `vcard_sample.py` to `vcard.py` and adjust the bot profile. EnvsBot can publish profile data and an avatar through XMPP vCard/PEP mechanisms.

Avatar-related config keys:

```python
AVATAR_PATH = "data/avatar.jpg"
AVATAR_TYPE = "image/jpeg"
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
| `,help ,<command>` | Show focused help for one command |
| `,bot status [full]` / `,status [full]` | Show compact or detailed bot, runtime, XMPP, plugin and database status |
| `,tasks [full] [plugin <name>] [status]` | Show supervised background task status |
| `,bot version` / `,version` | Show the running bot version and latest checked release |
| `,bot checkupdate` / `,checkupdate` / `,updatecheck` | Check GitHub releases for a newer version |
| `,config show [all/page/last]` | Show redacted runtime configuration |
| `,config diff [all/page/last]` | Show values that differ from `config_sample.py` defaults |
| `,config search/find <query>` | Search visible config keys and values |
| `,config set <KEY> <value>` | Persist and apply one runtime-writable config value |
| `,config unset <KEY>` | Reset one runtime-writable config value to the sample default |
| `,config validate` | Validate `config.py` |
| `,config reload` | Reload runtime-safe configuration |
| `,backup` / `,backup create [reason]` | Create a managed ZIP backup |
| `,backup list [all/page/last]` | List managed backup archives |
| `,backup show <archive|last>` | Show backup manifest details |
| `,restore <archive|last> confirm` | Restore a managed backup after explicit confirmation |
| `,audit last [limit]` | Show recent administrative audit events |
| `,audit user <jid>` | Show audit events for one actor |
| `,plugins list [all/page/last]` | List core and optional plugins |
| `,plugins load <name>` | Load a plugin at runtime |
| `,plugins unload <name>` | Unload an optional plugin at runtime |
| `,plugins reload <name>` | Reload a plugin at runtime |
| `,rooms list [all/page/last]` | List known rooms |
| `,rooms add <room_jid> <nick> [autojoin]` | Add a room to the database |
| `,rooms join <room_jid> [nick]` | Join a room immediately |
| `,rooms invite list [all/page/last]` | List pending room invites |
| `,rooms invite accept/decline <id>` | Accept or decline a pending room invite |
| `,rooms leave <room_jid>` | Leave a room |
| `,rooms plugins [<room_jid>] [all/page/last]` | Show plugin states for a room |
| `,rooms enable [<room_jid>] <plugin>` | Enable a room-toggleable plugin for a room |
| `,rooms disable [<room_jid>] <plugin>` | Disable a room-toggleable plugin for a room |
| `,users roles` | Show available user roles |
| `,users admins [all/page/last]` | List privileged users |
| `,users role <jid> <role>` | Change a user's role |
| `,users grant <jid> <plugin> [plugin ...]` | Grant room-scoped plugin permissions, for example `rss pin poll` |
| `,users revoke <jid> <plugin> [plugin ...]` | Revoke room-scoped plugin permissions |
| `,users grants <jid>` | Show room-scoped plugin permissions |

Room plugin settings can be changed in multiple contexts. In a MUC PM or directly in the room, the bot infers the room automatically. In a normal private chat or operational notification room, pass the target room explicitly, for example `,rooms disable room@conference.example.org xkcd`. The sender must be a room admin/owner in the target room or have a bot moderator/admin role. Selected plugins can also be delegated per user with `,users grant <jid> rss pin poll`; these grants are room-scoped and still require the user to be owner/admin in the target room. The global defaults used for new rooms and `,rooms set_plugin_defaults` are configured with `ROOM_PLUGIN_DEFAULTS` in `config.py`; per-room changes remain stored in the database.

EnvsBot has no separate fixed `ADMIN_ROOM` setting. Global bot privileges are controlled by `OWNER`, `ADMINS` and stored bot roles. Update and invite notification targets are configured separately with `VERSION_CHECK_NOTIFY_JID` and `ROOM_INVITE_NOTIFY_JID`.

For paginated commands, `all` disables paging and prints the full result set. New operators should start with [`docs/tutorial.md`](docs/tutorial.md); full reference: [`docs/commands.md`](docs/commands.md). `,help <command>` without the command prefix remains accepted as a convenience shortcut when it is not ambiguous with a plugin name.

---

## Plugins

EnvsBot now separates built-in bot functionality from optional room/community
features:

* `core_plugins/` contains bot/admin building blocks. These plugins keep their
  public names such as `help`, `rooms`, `users` and `backups`, but they are
  protected from runtime unloads. Reloading them is still supported.
* `plugins/` contains optional room, utility and community features that can be
  loaded, unloaded and reloaded at runtime.

Core plugins:

* `_admin` - restart, shutdown and runtime status/statistics
* `_core` - shared helpers for plugins
* `_reg_profile` - startup profile, vCard and avatar publishing
* `help` - dynamic command and plugin help
* `plugins` - runtime plugin management
* `tasks` - background task inspection
* `rooms` - room persistence, joining and per-room feature toggles
* `users` - user registration, roles, admin listings and last-seen tracking
* `config_cmd` - safe config inspection, validation and reload
* `backups` - managed ZIP backups and restore commands
* `audit` - admin audit log viewer
* `presence` - bot presence/status controls

Optional plugins:

* `birthday_notify` - birthday announcements for opted-in rooms
* `dice` - dice rolling with common notation
* `ducks` - duck game with persistent stats
* `info` - Wikipedia, Fediverse, Urban Dictionary and acronym helpers
* `karma` - room-local karma tracking
* `pin` - save and manage pinned messages
* `poll` - room polls with voting and history
* `reminder` - timed reminders with relative, absolute and timezone-aware scheduling
* `rss` - RSS/Atom feed watcher with optional per-room and per-feed output templates
* `sed` - sed-style message corrections
* `tell` - offline messages delivered when users rejoin
* `tools` - ping, echo, time/date, seen and timestamp helpers
* `translate` - translate text or replied-to room messages with auto-detection
* `urlcheck` - URL title, metadata, file and YouTube lookup
* `vcard` - public vCard lookup helpers
* `weather` - weather lookup from configured location data or city/ZIP input
* `xkcd` - latest, random, specific and searched XKCD comics
* `xmpp` - XMPP diagnostics, discovery, uptime, version and SRV checks

Reminder timezone notes: absolute reminders accept optional timezone tokens such as `CEST`, `CET`, `UTC`, `Europe/Berlin` or `+02:00`. Without an explicit token, the bot uses the user profile timezone from `,timezone set <IANA timezone>`, then `REMINDER_DEFAULT_TIMEZONE` from `config.py`, then UTC.

---

## Systemd Service

Example service unit:

```ini
[Unit]
Description=EnvsBot XMPP bot
Documentation=https://github.com/envs-net/envsbot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=envsbot
Group=envsbot
WorkingDirectory=/srv/envsbot
Environment=PYTHONUNBUFFERED=1
ExecStart=/srv/envsbot/.venv/bin/envsbot
Restart=always
RestartSec=5

# Basic hardening. Adjust ReadWritePaths when using a different data/log path.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/srv/envsbot

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

## Backups and Restore

Managed backups are ZIP archives stored below `data/backups` by default. When `BACKUP_ON_START = True`, the bot creates one startup backup per process start; this also covers service restarts. Archives include:

* `bot.db`
* `config.py`
* `vcard.py`
* `chat_slang.csv`
* `manifest.json`

Commands:

```text
,backup
,backup list
,backup show last
,restore last confirm
```

Restore is owner-only and creates a safety backup before overwriting files. Restart the bot after restoring `config.py` or `vcard.py` changes. Backup archives contain secrets and should be protected like `config.py`.

## SQLite Maintenance

Use `,bot status` for a compact safe online database status check. Use `,bot status full` for additional SQLite page details.

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

Run mutation tests with mutmut:

```bash
mutmut run
mutmut results
mutmut browse
```

The mutmut configuration in `pyproject.toml` explicitly lists the flat-layout source paths and disables coverage during mutant test runs.

Drone CI is configured in `.drone.yml`.

---

## Documentation

* [`docs/README.md`](docs/README.md) - documentation index
* [`docs/tutorial.md`](docs/tutorial.md) - practical setup and operations walkthrough
* [`docs/commands.md`](docs/commands.md) - generated command reference
* [`docs/help.md`](docs/help.md) - runtime help guide
* [`docs/diagnostics.md`](docs/diagnostics.md) - doctor checks, plugin state and operational diagnostics
* [`docs/architecture.md`](docs/architecture.md) - runtime module layout and command flow
* [`docs/plugin-development.md`](docs/plugin-development.md) - plugin structure, hooks, stores, grants and diagnostics
* [`docs/maintenance.md`](docs/maintenance.md) - offline SQLite maintenance
* [`docs/release-checklist.md`](docs/release-checklist.md) - release preparation checklist

Regenerate the command reference after changing command metadata:

```bash
python scripts/generate_commands_md.py
```

---

## Security Notes

* Keep `config.py` private; it contains the bot password and optional API keys.
* Use a dedicated XMPP account for the bot.
* Give Owner/Superadmin roles only to trusted administrators.
* Runtime config output redacts known secret values, but logs and local files should still be protected.
* `VACUUM` and other SQLite rewrite operations should be run only while the bot is stopped.
* Review loaded plugins before enabling them in public rooms.

---

## License

This project is licensed under the **GPL-3.0-only** license. See [`LICENSE`](LICENSE) for details. Future versions of the GPL license are explicitly excluded.

See `docs/README.md` for the full documentation index, including deployment notes in `docs/deployment.md`.
