# Deployment

This page describes a simple production-style deployment for envsbot on a
systemd-based Linux host.

## Layout

A small dedicated user and one application directory keeps runtime files,
configuration and logs easy to reason about:

```bash
sudo useradd --system --home /srv/envsbot --shell /usr/sbin/nologin envsbot
sudo mkdir -p /srv/envsbot
sudo chown envsbot:envsbot /srv/envsbot
```

Clone or copy the repository to `/srv/envsbot`, then create a virtualenv:

```bash
cd /srv/envsbot
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
```

The package installs a console entrypoint named `envsbot`, so the bot can be
started with:

```bash
/srv/envsbot/.venv/bin/envsbot
```

## Configuration

Create production config files from the samples:

```bash
cp config_sample.py config.py
cp vcard_sample.py vcard.py
```

Then edit at least:

```python
JID = "bot@example.org"
PASSWORD = "..."
OWNER = "admin@example.org"
ROOMS = []
```

Keep local runtime files such as a custom avatar, `bot.db`, backups and logs in
`/srv/envsbot` or a directory that is writable by the `envsbot` user.

## systemd

An example service file is provided at:

```text
contrib/envsbot.service
```

Install it with:

```bash
sudo cp contrib/envsbot.service /etc/systemd/system/envsbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now envsbot.service
```

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
pip install -e .
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
sqlite3 bot.db "PRAGMA integrity_check;"
sqlite3 bot.db "PRAGMA optimize;"
sqlite3 bot.db "VACUUM;"
sudo systemctl start envsbot.service
```

The bot runs schema migrations automatically on startup. Applied migrations can
be inspected with the `bot status full` database section or directly from the
`schema_migrations` table.
