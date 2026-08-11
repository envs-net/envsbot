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
- in-process performance timing for DB locks, IdleRPG, outbox, RSS and commands
- backup directory and retention settings
- plugin-provided health checks for RSS, IdleRPG, reminders, pins, weather, translate, URLCheck, birthdays, ducks, tell and karma

Useful sections include `config`, `database`, `rooms`, `plugins`, `tasks`,
`performance`, `backups`, `network`, `plugin-health` and selected plugin names
such as `rss`, `idlerpg`, `weather`, `translate` or `urlcheck`.

Examples:

```text
,doctor
,doctor all
,doctor warnings
,doctor failed
,doctor tasks
,doctor performance
,doctor rss
,doctor idlerpg
,doctor translate
```


## In-process performance diagnostics

`,doctor performance` exposes lightweight counters kept only in the running
process. It reports event-loop lag plus average/maximum timings for SQLite lock
waits, IdleRPG ticks/saves/exports, outbox delivery and RSS fetches. It also
shows the slowest command names and RSS hosts. RSS measurements retain only the
host name, not complete feed URLs.

```text
,doctor performance
,doctor performance full
,doctor full
```

The counters reset on process restart and intentionally do not require an
external metrics service. They are diagnostics rather than long-term monitoring.

## Room diagnostics

Use `,rooms diagnose <room_jid>` when a room behaves differently than expected.

The output shows whether the room is known in the database, whether it is joined,
tracked occupant count, pending invites, enabled/disabled room plugins and
plugin-provided room state where available. The command reports a warning only
when the detailed core MUC state and the smaller presence/routing room mirror
disagree; a normal joined room does not need a separate presence line.

```text
,rooms diagnose lounge@conference.example.org
```

## Room invite onboarding

When the bot receives a direct or mediated MUC invite, it stores the invite as a pending item and notifies the configured admin target. After accepting an invite, the reply includes a small onboarding checklist:

```text
,rooms diagnose room@conference.example.org
,rooms plugins room@conference.example.org all
,doctor rooms
```

This keeps the invite flow safe: the room is joined and stored with autojoin enabled, room plugin defaults are applied, and the operator gets the next checks for affiliation, room plugin toggles and general room health.

## Plugin diagnostics and state

Use `,plugins` for the loaded/available plugin list. Loaded plugins include a compact health marker and the first line shows an aggregate health summary. Use `,plugin diagnose <plugin>` for metadata, command, hook and task information. Use `,plugin state <plugin> [room_jid]` for plugin-provided runtime counters.

Examples:

```text
,plugins
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

`tasks stale` is read-only and reports supervised tasks with an expired progress heartbeat (`TASK_STALE_AFTER_SECONDS`, default: one hour). Services that have not emitted their first heartbeat yet use creation time as the initial progress marker, so an early startup hang is still visible; ordinary one-shot tasks without a heartbeat remain exempt. Heartbeat-aware sleeps refresh at no more than half of this threshold and never wait more than 30 seconds between heartbeats; values below 60 seconds are rejected. Restart support is intentionally opt-in per plugin.

Plugins with long-running loops should use `utils.task_supervisor.create_resilient_plugin_task()`
instead of `asyncio.create_task()` so tasks appear as services in `,tasks`, are
cancelled on plugin unload and recover from unexpected worker failures with the
shared restart/circuit-breaker policy.

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
,audit errors
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
[DB] event=migration status=ok version=0004_message_cache
```

Sensitive values and URLs with embedded credentials are passed through the
central redaction helper before they are written to logs or audit details.

## Persistent outbound queue

RSS posts, reminders, tell deliveries and selected administrative messages can
be transferred to the SQLite-backed outbox when immediate XMPP delivery is not
possible. The queue resumes after reconnects and process restarts.

```text
,outbox status
,outbox dead
,outbox retry 42
,outbox retry rss
,outbox retry all
,outbox delete 42
,outbox delete dead
```

`dead` deliberately omits message bodies. `status` also reports configured count
and byte limits plus the largest destination/category backlog. `doctor database`
reports pending and dead counts, the oldest pending age and whether the worker is
running. Durable stanzas also keep one stable XEP-0359 `origin-id` across every
retry. This does not turn XMPP into a strict exactly-once transport, but it lets
servers/clients recognize a replay if the bot dies after transport acceptance
and before the outbox row can be marked sent. Dead letters are retained for
`OUTBOX_DEAD_RETENTION_DAYS` and pruned automatically; setting the retention to
`0` disables age-based dead-letter cleanup.

## Task circuits and systemd watchdog

Restartable workers use exponential backoff. After the configured number of
consecutive failures, the worker opens its circuit and sends one administrative
notification. Inspect and reset it with:

```text
,tasks failed
,tasks all
,tasks restart rss
,doctor tasks
```

The runtime watchdog reports current and maximum event-loop lag in `doctor
tasks`. With the generated recommended systemd unit it also feeds `WatchdogSec`; a process
that is alive but no longer scheduling the event loop is restarted by systemd.

## Command usage statistics

Aggregate command counters help identify commands that are heavily used, rare
or never used without retaining caller identities or command arguments:

```text
,commandstats top 30
,commandstats rare 90
,commandstats unused
```

Counters are retained for `COMMAND_USAGE_RETENTION_DAYS` and pruned by automatic
database maintenance.

## Immediate admin alerts and optional daily report

Immediate alerts are enabled by default and delivered only over XMPP to the same
administrative destination used by runtime notifications. They cover state
changes such as an opened task circuit, outbox pressure/dead letters, a prolonged
missing room, stale or invalid backups, repeated database/IdleRPG export failures
and excessive event-loop lag. Alerts are stateful and deduplicated: the first
problem is marked red, optional cooldown reminders yellow and recovery green.

The daily report is disabled by default. It summarizes uptime, required
autojoin-room health (with separately counted manual rooms), plugin/task failures,
open circuits, anonymized active-alert categories, outbox and persistent
message-cache state, event-loop lag, database maintenance, latest backup age and
verification, and aggregate 24-hour command counts. Its final overall state is
warning whenever an active alert or another current operational failure is
present, so it cannot report a green overall state alongside an active incident.

```python
ADMIN_REPORT_ENABLED = True
ADMIN_REPORT_JID = "admin@example.org"
ADMIN_REPORT_TIME = "08:00"
ADMIN_REPORT_TIMEZONE = "Europe/Berlin"
ADMIN_REPORT_MODE = "daily"  # or "problems_only"

ADMIN_ALERTS_ENABLED = True
ADMIN_ALERT_INTERVAL_SECONDS = 60
ADMIN_ALERT_COOLDOWN_SECONDS = 3600
```

`ADMIN_REPORT_MODE = "problems_only"` suppresses the scheduled report when no
active immediate alert exists. Use `,report status` to inspect the schedule and `,report now` for a manual
report. `ADMIN_REPORT_BACKUP_SMOKE_TEST = True` additionally extracts and opens
the latest backup in a temporary directory; it does not modify production
files. No external metrics service or network listener is created.
