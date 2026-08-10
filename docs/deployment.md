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

Recommended layout (all paths are examples and may be replaced by site-specific locations):

```text
/srv/envsbot/              repository + virtualenv
/etc/envsbot/config.py     runtime-editable config
/var/lib/envsbot/          database, backups, exports and runtime state
/var/log/envsbot/          rotating file logs (journald receives console logs too)
```

The two log destinations are intentional: envsbot writes one rotating file and
also emits the same records to stderr, which systemd captures in the journal.
If the host forwards journald to rsyslog/syslog, the console copy can therefore
appear there as well; that is host-side forwarding, not a third envsbot log
handler.

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


## Interactive deployment helper (optional)

`./scripts/deploy.sh` provides an interactive, preservation-first wrapper around
the same manual deployment steps documented below. Running the script **without
a command only prints its help** and never installs or updates anything:

```bash
./scripts/deploy.sh
./scripts/deploy.sh status
./scripts/deploy.sh check
./scripts/deploy.sh install --dry-run
./scripts/deploy.sh update --dry-run
```

Actual installation and update operations require explicit confirmation. If an
active systemd service must be stopped, that stop is confirmed separately. The
script also asks separately before starting the service again. Declining a start
leaves the service stopped. Declining a required stop aborts the update before
application code, dependencies or the database schema are changed.

The helper is deliberately conservative with operator-managed state:

- an existing runtime config is kept and never replaced from `config_sample.py`;
- an existing SQLite database is never replaced by deployment code;
- an existing runtime `vcard.py` is kept;
- an existing operator-managed/custom avatar file is kept (the packaged default asset may update with envsbot);
- an existing systemd service/unit is **never overwritten** by the helper; and
- an update refuses to continue with tracked local Git modifications.

For legacy installations that still keep config, database, vCard or avatar files
inside the application checkout, the update helper protects those files across
the Git checkout and restores them if the target release would remove or replace
them. Files outside the application checkout are never touched by Git in the
first place. Database migrations still use the normal verified `envsbot db backup` workflow.

Installations do not have to use `/srv/envsbot`, `/etc/envsbot` or the default
service name. The helper derives the application root from its own checkout,
uses `ENVSBOT_CONFIG` when set and inspects an existing systemd service account and unit path
where possible. Non-standard layouts can be selected explicitly:

```bash
sudo ./scripts/deploy.sh status \
  --root /opt/bots/envsbot \
  --venv /opt/venvs/envsbot \
  --config /opt/bot-config/envsbot.py \
  --service my-envsbot.service \
  --user botuser \
  --group botgroup \
  --unit /etc/systemd/system/my-envsbot.service
```

Useful environment overrides are `ENVSBOT_CONFIG`, `ENVSBOT_VENV`,
`ENVSBOT_SERVICE`, `ENVSBOT_SERVICE_USER`, `ENVSBOT_SERVICE_GROUP`,
`ENVSBOT_SYSTEMD_UNIT`, `ENVSBOT_DEPLOY_BASE_PYTHON` and
`ENVSBOT_DEPLOY_PYTHON`. Command-line options take precedence.

`install` starts from an existing envsbot source checkout and an existing service
account; it deliberately does not create system users or clone a repository. Those
minimal bootstrap steps remain explicit because account names, ownership and source
locations vary between installations.

A fresh `install` is resumable. If the configured config file is missing, the
helper creates it once from `config_sample.py`, stops there and asks the operator
to edit it. Rerunning `install` keeps that edited config, validates it, creates a
missing vCard only when needed, optionally installs a **new** systemd unit and
then asks whether the service should be started. The helper does not create or
guess XMPP credentials.

For updates, use a release tag:

```bash
sudo ./scripts/deploy.sh update --to v1.8.0
# or let the helper select the newest version-sorted tag after git fetch:
sudo ./scripts/deploy.sh update
```

The automatic update path **never deploys `main`**. After fetching tags it compares
the selected release with the currently checked-out `HEAD` using Git ancestry:

- a release newer than `HEAD` is offered as the normal update;
- if `HEAD` already contains commits newer than the newest release tag, the helper
  reports that no newer release is available and exits without stopping the service;
- if `HEAD` is on a branch but already points at the exact release commit, the helper
  can pin the checkout to that release tag;
- a release on unrelated/diverged history is refused as a non-fast-forward deployment.

An older release is never selected automatically. An intentional code rollback must
name the older tag explicitly and opt in to downgrade handling:

```bash
sudo ./scripts/deploy.sh update --to v1.7.3 --allow-downgrade
```

This produces an additional warning and confirmation. It only permits the older
**code** checkout; it does not downgrade the SQLite schema. If the older release is
incompatible with the current database, validation fails and the service remains
stopped. Restoring a matching verified database backup may therefore be required.

The helper runs the same database status/dry-run/backup/migrate/check and local
preflight steps shown in the manual update procedure below. If an update fails
after the service was stopped, it intentionally leaves the service stopped; it
does not automatically start older code against a database that may already
have been migrated.

`status` keeps read-only discovery probes quiet and prints only the resolved
deployment paths, current Git revision, latest local release tag and service
state. `check` is also intentionally compact on success. In addition to the
normal envsbot preflight and path/permission checks, it compares the **effective
systemd properties currently loaded by systemd** with the unit rendered for the
active installation. This catches drift from both the main unit and drop-ins,
including the service account, working directory, executable, config path,
restart/watchdog policy, core hardening flags and `ReadWritePaths`.

A mismatch makes `./scripts/deploy.sh check` fail and prints the current and
expected value. For the complete underlying diagnostic output or the full
rendered unit, run the existing commands directly:

```bash
envsbot --check
envsbot systemd check
envsbot systemd render
```

The manual installation and update procedures below remain supported and are
recommended when an operator wants full command-by-command control.

## Configuration

Create the runtime configuration outside the application tree:

```bash
if ! sudo test -e /etc/envsbot/config.py; then
  sudo install -o envsbot -g envsbot -m 0600 config_sample.py /etc/envsbot/config.py
else
  echo "KEEP existing /etc/envsbot/config.py"
fi
sudo install -d -o envsbot -g envsbot -m 0700 /var/lib/envsbot
if ! sudo test -e /var/lib/envsbot/vcard.py; then
  sudo install -o envsbot -g envsbot -m 0600 vcard_sample.py /var/lib/envsbot/vcard.py
else
  echo "KEEP existing /var/lib/envsbot/vcard.py"
fi
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
RUNTIME_DATA_DIR = "/var/lib/envsbot"
BACKUP_DIR = "/var/lib/envsbot/backups"
RESTART_NOTIFICATION_FILE = "/var/lib/envsbot/restart_notification.json"
# In the existing IDLERPG dictionary:
# "export_path": "/var/lib/envsbot/idlerpg",
```

`RUNTIME_DATA_DIR` contains mutable support files (`vcard.py`, `chat_slang.csv`,
slang review queues and profile hash markers). When it is unset, envsbot keeps the historical application-root
location; setting it explicitly is required for a read-only hardened
production checkout. The packaged `init_chat_slang.csv` is copied there automatically on
first startup. The default avatar is bundled with the Python package as well, so
production deployments do not need `avatar.jpg` or `init_chat_slang.csv` copies
in the application root. Configure a separate `AVATAR_PATH` only when using a
custom avatar.

Runtime Python data files are executed directly from source instead of being
imported as modules, so current releases do not create `__pycache__` beside
`/etc/envsbot/config.py` or `/var/lib/envsbot/vcard.py`. An old cache left by a
previous release is unused and can be removed safely, for example with
`sudo rm -rf /etc/envsbot/__pycache__`.

Do not grant write access to `/srv/envsbot` merely to accommodate a database,
configuration or runtime support file there. `envsbot systemd check` treats that
as a hardening failure.
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
envsbot systemd render > /tmp/envsbot.service.new
if sudo test -e /etc/systemd/system/envsbot.service; then
  echo "KEEP existing /etc/systemd/system/envsbot.service"
  sudo diff -u /etc/systemd/system/envsbot.service /tmp/envsbot.service.new || true
  echo "Review the diff and replace the unit manually only when intended."
else
  sudo install -m 0644 /tmp/envsbot.service.new /etc/systemd/system/envsbot.service
fi
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

## Manual updates

The interactive helper above is optional. For a fully manual update, stop the service before changing application code, dependencies or the database
schema. Production deployments should move between tagged releases rather than
blindly pulling `main` while the old process is still running:

```bash
sudo systemctl stop envsbot.service

cd /srv/envsbot
sudo -u envsbot git fetch --tags --prune
LATEST_TAG="$(sudo -u envsbot git tag --sort=-v:refname | head -n1)"
sudo -u envsbot git checkout "$LATEST_TAG"
echo "Using EnvsBot release $LATEST_TAG"

sudo -u envsbot .venv/bin/pip install -c constraints/python313.txt -e .
sudo -u envsbot env ENVSBOT_CONFIG=/etc/envsbot/config.py .venv/bin/envsbot db status
sudo -u envsbot env ENVSBOT_CONFIG=/etc/envsbot/config.py .venv/bin/envsbot db migrate --dry-run
sudo -u envsbot env ENVSBOT_CONFIG=/etc/envsbot/config.py .venv/bin/envsbot db backup
sudo -u envsbot env ENVSBOT_CONFIG=/etc/envsbot/config.py .venv/bin/envsbot db migrate
sudo -u envsbot env ENVSBOT_CONFIG=/etc/envsbot/config.py .venv/bin/envsbot db check
sudo -u envsbot env ENVSBOT_CONFIG=/etc/envsbot/config.py .venv/bin/envsbot --check

sudo systemctl start envsbot.service
sudo journalctl -u envsbot.service -n 100 --no-pager
```

If any pre-start step fails, leave the service stopped, correct the problem and
rerun the checks. Do not start the previous code against a database that has
already been migrated by a newer release.

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
sh scripts/quality.sh
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
