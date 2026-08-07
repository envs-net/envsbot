# Deployment

This page describes a simple production-style deployment for envsbot on a
systemd-based Linux host.

## Layout

Use a dedicated service account and separate immutable application code from
runtime-writable configuration/state:

```bash
sudo useradd --system --home /srv/envsbot --shell /usr/sbin/nologin envsbot
sudo mkdir -p /srv/envsbot
sudo install -d -o envsbot -g envsbot -m 0750 /etc/envsbot /var/lib/envsbot /var/log/envsbot
```

Recommended layout:

```text
/srv/envsbot/              repository + virtualenv
/etc/envsbot/config.py     runtime-editable config
/var/lib/envsbot/          database, backups, exports and runtime state
/var/log/envsbot/          rotating file logs (journald receives console logs too)
```

Clone or copy the repository to `/srv/envsbot`, then create a virtualenv:

```bash
cd /srv/envsbot
python3 -m venv .venv
. .venv/bin/activate
pip install -c constraints/python313.txt -e .
```

Use `constraints/python312.txt` instead when the production interpreter is
Python 3.12.

The package installs a console entrypoint named `envsbot`, so the bot can be
started with:

```bash
/srv/envsbot/.venv/bin/envsbot
```

## Configuration

Create the runtime configuration outside the application tree:

```bash
sudo cp config_sample.py /etc/envsbot/config.py
sudo chown envsbot:envsbot /etc/envsbot/config.py
sudo chmod 0600 /etc/envsbot/config.py
cp vcard_sample.py vcard.py
```

The supplied systemd unit sets `ENVSBOT_CONFIG=/etc/envsbot/config.py`. For a
manual shell start, export the same variable first.

Then edit at least:

```python
JID = "bot@example.org"
PASSWORD = "..."
OWNER = "admin@example.org"
ROOMS = []
```

For the hardened unit, place mutable state below `/var/lib/envsbot`, for
example:

```python
LOG_DIR = "/var/log/envsbot"
DB_FILE = "/var/lib/envsbot/bot.db"
BACKUP_DIR = "/var/lib/envsbot/backups"
RESTART_NOTIFICATION_FILE = "/var/lib/envsbot/restart_notification.json"
# In the existing IDLERPG dictionary:
# "export_path": "/var/lib/envsbot/idlerpg",
```

Do not grant write access to `/srv/envsbot` merely to accommodate a database or
config file there. `envsbot systemd check` treats that as a hardening failure.
Existing installations can keep their current data while planning the move, but
should move these paths before installing the strict rendered unit.

## systemd

An example service file is provided at:

```text
contrib/envsbot.service
```

The checked-in unit is an `/srv/envsbot` example. On the target host, prefer
rendering a unit from the active installation so `ExecStart`, `WorkingDirectory`
and writable paths cannot silently drift:

```bash
. /srv/envsbot/.venv/bin/activate
export ENVSBOT_CONFIG=/etc/envsbot/config.py
envsbot systemd check
envsbot systemd render | sudo tee /etc/systemd/system/envsbot.service >/dev/null
sudo systemd-analyze verify /etc/systemd/system/envsbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now envsbot.service
```

`envsbot systemd check` also validates the configured log, database, backup, IdleRPG
export and restart-notification paths. The generated unit accepts optional local
overrides from `/etc/default/envsbot` via `EnvironmentFile=`.

Useful commands:

```bash
sudo systemctl status envsbot.service
sudo journalctl -u envsbot.service -f
sudo systemctl restart envsbot.service
```

Optional hardening: after verifying `envsbot --check` works reliably on the
host, add it as an `ExecStartPre=` command in the systemd unit so invalid
configuration or a broken local checkout prevents a restart.

## Updates

For a normal update:

```bash
cd /srv/envsbot
git pull
. .venv/bin/activate
pip install -c constraints/python313.txt -e .
envsbot db status
envsbot db migrate --dry-run
envsbot db backup
envsbot db migrate
envsbot db check
envsbot --check
sudo systemctl restart envsbot.service
sudo journalctl -u envsbot.service -n 100 --no-pager
```

`envsbot --check` is a local preflight check. It does not connect to XMPP,
but it validates configuration loading, plugin imports, command metadata,
generated command docs, migrations, backup paths, runtime files and SQLite
read/write access. Treat a non-zero exit code as a deployment blocker.

Run the test suite before deploying when changing code locally:

```bash
PYTHONPATH="$PWD" pytest --no-cov -q
```

## Database maintenance

Stop the bot before manual SQLite maintenance:

```bash
sudo systemctl stop envsbot.service
DB_PATH="/var/lib/envsbot/bot.db"  # use the DB_FILE path from your config
sqlite3 "$DB_PATH" "PRAGMA integrity_check;"
sqlite3 "$DB_PATH" "PRAGMA optimize;"
sqlite3 "$DB_PATH" "VACUUM;"
sudo systemctl start envsbot.service
```

The bot still runs pending schema migrations automatically on startup, but
upgrades can now be inspected and executed explicitly before restart:

```bash
envsbot db status
envsbot db migrate --dry-run
envsbot db backup
envsbot db migrate
envsbot db check
```

Each migration runs in a SQLite savepoint and is recorded with duration and
status. By default a consistent SQLite snapshot is created before pending
migrations are applied. Startup is refused when the database contains migration
versions unknown to the running build, preventing an accidental downgrade from
using a newer schema.

## Watchdog-enabled systemd unit

The supplied unit uses `Type=notify`, `NotifyAccess=main` and `WatchdogSec=60`.
EnvsBot sends `READY=1` after startup and watchdog heartbeats while the event
loop remains responsive. This detects a hung process that `Restart=on-failure`
alone cannot recover.

After replacing an older unit, reload systemd before restarting:

```bash
sudo systemctl daemon-reload
sudo systemctl restart envsbot.service
sudo systemctl show envsbot.service -p Type -p WatchdogUSec
```

To disable watchdog handling completely, remove or override `WatchdogSec` in
systemd as well as setting `WATCHDOG_ENABLED = False`; when systemd explicitly
requests heartbeats, the bot keeps sending them to avoid an endless restart
loop.

The example unit also enables strict filesystem and kernel hardening. The
application checkout itself is intentionally absent from `ReadWritePaths=`.
`envsbot systemd render` derives only the runtime-writable config, log, database,
backup, IdleRPG export and restart-notification directories from the active
configuration. `envsbot systemd check` fails if those settings would force the
whole application tree (or one of its parents) to become writable.

## Deployment quality gate

Development dependencies provide the local quality runner:

```bash
pip install -c constraints/python313.txt -r requirements.txt -r requirements-dev.txt
scripts/quality.sh
```

Use the constraints file matching the interpreter (`python312.txt` or
`python313.txt`). The snapshots include the complete transitive dependency
closure. `scripts/update-constraints.sh <version>` reproduces the reviewed lock;
use `--refresh` only for an intentional dependency-update commit. CI also runs
`scripts/check_constraints.py` to reject an unpinned transitive dependency.

It checks Python compilation, generated command documentation, focused Ruff and
mypy rules, the test suite with runtime and deprecation warnings treated as
errors, and dependency advisories through `pip-audit`. CI runs the same
categories before packaging.
