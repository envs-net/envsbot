# Diagnostics and operational controls

EnvsBot includes a small set of operator commands for runtime diagnostics,
state inspection and safe maintenance.

## Health checks

Use `,doctor` for a compact health check, `,doctor all` for the full operator view and `,doctor <section>` for focused diagnostics.

The doctor command checks:

- runtime config path and command prefix
- command rate-limit status
- database connectivity and applied migrations
- known rooms vs joined rooms
- loaded/available plugins and registered commands
- supervised background task summary
- backup directory and retention settings
- plugin-provided health checks for RSS, IdleRPG, reminders, pins, weather, URLCheck, birthdays, ducks, tell and karma

Useful sections include `config`, `database`, `rooms`, `plugins`, `tasks`, `backups`, `network`, `plugin-health` and selected plugin names such as `rss`, `idlerpg`, `weather` or `urlcheck`.

Examples:

```text
,doctor
,doctor all
,doctor tasks
,doctor rss
,doctor idlerpg
```

## Room diagnostics

Use `,rooms diagnose <room_jid>` when a room behaves differently than expected.

The output shows whether the room is known in the database, whether it is joined,
tracked occupant count, pending invites, enabled/disabled room plugins and
plugin-provided room state where available.

```text
,rooms diagnose lounge@conference.example.org
```

## Plugin diagnostics and state

Use `,plugin diagnose <plugin>` for metadata, command, hook and task information.
Use `,plugin state <plugin> [room_jid]` for plugin-provided runtime counters.

Examples:

```text
,plugin diagnose rss
,plugin state rss
,plugin state poll lounge@conference.example.org
```

Plugins can expose a small diagnostic state hook:

```python
async def get_runtime_state(bot, room_jid=None) -> dict:
    return {"items": 3}
```

The hook should return counters and status values, not raw private user data.

## Background task control

The `,tasks` command lists supervised background tasks. Use `,tasks restart
<plugin>` to cancel a plugin's supervised tasks and ask the plugin to restore
its tasks through `restart_tasks(bot)` or `on_ready(bot)`.

```text
,tasks
,tasks list
,tasks failed
,tasks stale
,tasks plugin rss
,tasks plugin rss running
,tasks restart rss
```

`tasks stale` is read-only and reports supervised tasks whose heartbeat is older than `TASK_STALE_AFTER_SECONDS` (default: one hour). Restart support is intentionally opt-in per plugin.

Plugins with long-running loops should use `utils.task_supervisor.create_plugin_task()`
instead of `asyncio.create_task()` so tasks appear in `,tasks`, are cancelled on
plugin unload and can be restarted consistently.

## Backup retention

Backups are kept by count with `BACKUP_KEEP` and optionally by age with
`BACKUP_RETENTION_DAYS`. Set `BACKUP_RETENTION_DAYS = 0` to disable age-based
retention.

Manual inspection and restore planning should be used before destructive restores:

```text
,backup show last
,backup verify last
,backup restore last dry-run
,backup restore last confirm
```

Manual pruning supports a dry-run mode:

```text
,backup prune dry-run
,backup prune keep 20 days 30
```

## Audit filters

The audit log can be filtered by actor, target or event type:

```text
,audit last
,audit user admin@example.org
,audit target lounge@conference.example.org
,audit action room_feature_changed
,audit target lounge@conference.example.org all
,audit export 100 action backup_created
,audit prune 90 dry-run
```

Room changes, plugin changes, config reloads, backups and selected plugin state
changes are written to the audit log where available.

## Command rate limits

Command rate limits are configured in `config.py` through the
`COMMAND_RATE_LIMIT_*` options. The limiter is in-memory and resets on restart.
By default, room moderators and higher bot roles bypass the limiter.

Important options:

```python
COMMAND_RATE_LIMIT_ENABLED = True
COMMAND_RATE_LIMIT_CAPACITY = 4
COMMAND_RATE_LIMIT_REFILL_AMOUNT = 1
COMMAND_RATE_LIMIT_REFILL_INTERVAL_SECONDS = 0.5
COMMAND_RATE_LIMIT_BYPASS_ROLE = "moderator"
```

## Local preflight check

For deployments and upgrades, envsbot now has a local preflight mode that does
not connect to XMPP:

```bash
python -m envsbot --check
# or, when installed from the package:
envsbot --check
```

The preflight checks that the config can be loaded, `config_sample.py` stays
compatible, plugin modules import, plugin metadata is valid, command metadata is
complete, command documentation is generated from current metadata, known
migrations are ordered, the backup directory is writable, runtime files are
available, and the SQLite database can be opened, checked and written inside a
rolled-back transaction.

A non-zero exit code means the deployment should not be restarted yet. The
preflight intentionally does not connect to XMPP and is safe to run from CI or
from a systemd `ExecStartPre=` style check.

## Core runtime modules

The top-level `envsbot.py` entrypoint now delegates most runtime behaviour to
small `bot/` modules:

- `bot.connection` for JID/resource/connect option handling
- `bot.routing` for incoming MUC/private message routing
- `bot.dispatch` for command resolution, rate limiting and permissions
- `bot.messages` for reply formatting and safe sending
- `bot.permissions` for role lookup and room-affiliation elevation
- `bot.lifecycle` for startup, restart notifications and shutdown cleanup
- `bot.audit` for best-effort audit writes

These modules are intended to keep the runtime core easier to test while the
public `envsbot.Bot` API remains compatible. See [`architecture.md`](architecture.md)
for the full module map and command flow.


## Structured core logs

Core paths now prefer stable key/value log messages so `journalctl` output is
easier to filter. Common examples are:

```text
[COMMAND] event=slow command=doctor actor=user@example.org room=room@conference.example.org duration_ms=45 status=ok
[LIFECYCLE] event=shutdown phase=tasks status=ok cancelled=21
[DB] event=migration status=ok version=0003_room_invites
```

Sensitive values and URLs with embedded credentials are passed through the
central redaction helper before they are written to logs or audit details.
