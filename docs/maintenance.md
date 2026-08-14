# Maintenance

This document covers maintenance tasks that should be run by the server administrator outside the running bot process.

## SQLite database maintenance

Do not run `VACUUM` from a live bot command. `VACUUM` rewrites the SQLite database file and should be performed during a planned maintenance window while envsbot is stopped.

Recommended manual procedure. Set `DB_PATH` to the effective `DB_FILE` from
your runtime configuration before running maintenance. Fresh source-tree
installations default to `data/bot.db`; hardened deployments commonly use
`/var/lib/envsbot/bot.db`.

```bash
DB_PATH=/var/lib/envsbot/bot.db
systemctl stop envsbot.service

sqlite3 "$DB_PATH" "PRAGMA integrity_check;"
sqlite3 "$DB_PATH" "PRAGMA optimize;"
sqlite3 "$DB_PATH" "VACUUM;"

systemctl start envsbot.service
```

Adjust the service name and `DB_PATH` for the active installation. Do not assume
that the database lives in the current working directory.

For a quick online status check from the bot, use:

```text
,bot status
```

Use `,bot status full` for additional SQLite page details, detected room problems, plugin details and bounded-cache diagnostics. Its final section mirrors the compact inventory from `,tasks all`, so the usually longest list stays at the bottom; use `,tasks full all` for per-task timestamps, restart counters and circuit details. Healthy rooms are not enumerated there; use `,rooms list all` for the complete MUC inventory.


## Managed ZIP backups

Use the built-in backup commands for normal operational snapshots:

```text
,backup
,backup list
,backup show last
,restore last confirm
```

Managed archives are written to `BACKUP_DIR`, which defaults to `data/backups`.
When `BACKUP_ON_START = True`, envsbot creates one startup backup per process
start; this also covers service restarts. `BACKUP_INTERVAL_HOURS` defaults to
24 and runs a supervised scheduler that creates another managed backup whenever
the newest archive reaches that age. Set it to `0` only when periodic backups
are intentionally provided elsewhere. The default cadence stays below the
36-hour stale-backup admin alert threshold. Keep `BACKUP_INTERVAL_HOURS` lower
than `ADMIN_ALERT_BACKUP_MAX_AGE_HOURS` so a scheduled backup is normally
created before that alert threshold. Each archive contains `bot.db`, `config.py`,
`vcard.py`, `chat_slang.csv`, `slang_additions.csv`, `slang_removals.csv` and a
`manifest.json` when those files exist. Restore is owner-only. Before changing
runtime files, envsbot fully
verifies the selected archive, stages the runtime files and creates a
checksum-verified safety backup. It then stops command handling, plugins,
supervised workers, the persistent outbox, message cache and database before
replacing `bot.db`, the active config and writable support files below
`RUNTIME_DATA_DIR`. Legacy support files inside the read-only source tree remain
available in the archive for offline/manual restore. The old Python process is
never resumed against restored state: envsbot exits with restart code `75` and
the generated recommended `Restart=on-failure` systemd service starts a fresh
process. After shutdown, envsbot snapshots the exact closed runtime files before
publishing restored state. If a file replacement fails, it rolls back from that
quiesced snapshot; the verified safety backup remains available as an additional
recovery point. A fresh restart is still required.

Backup archives contain secrets such as the bot password and optional API keys.
Keep them private and include them in your normal server backup policy.

New managed ZIP backups are restore-smoke-tested by default
(`BACKUP_SMOKE_TEST_ON_CREATE = True`) before they are accepted. Pre-migration
SQLite snapshots are also verified with `integrity_check` and
`foreign_key_check`, then retained independently using
`DATABASE_MIGRATION_BACKUP_KEEP` and
`DATABASE_MIGRATION_BACKUP_RETENTION_DAYS`. This prevents migration safety
snapshots from accumulating forever while preserving recent rollback points.

## Automatic online maintenance

The running bot performs lightweight online maintenance at
`DATABASE_MAINTENANCE_INTERVAL_SECONDS` (default: 21600 seconds / 6 hours):

- `PRAGMA optimize`
- a passive WAL checkpoint when WAL mode is enabled
- pruning old aggregate command-usage rows

Important SQLite runtime settings are:

```python
DATABASE_BUSY_TIMEOUT_MS = 5000
DATABASE_WAL_ENABLED = False
DATABASE_SHUTDOWN_TIMEOUT_SECONDS = 15.0
DATABASE_MAINTENANCE_INTERVAL_SECONDS = 21600
DATABASE_BACKUP_BEFORE_MIGRATE = True
```

`DATABASE_BUSY_TIMEOUT_MS` is applied when the SQLite connection opens. WAL mode
is optional and disabled by default. `DATABASE_SHUTDOWN_TIMEOUT_SECONDS` gives
shutdown/restart cleanup enough time to flush and close the shared connection.
When `DATABASE_BACKUP_BEFORE_MIGRATE` is enabled, pending schema migrations are
preceded by a consistent SQLite safety snapshot.

The task never runs `VACUUM`; planned offline `VACUUM` remains the administrator
procedure described above. Results and the last error are visible through
`,doctor database` and the optional daily admin report.

The optional report normally verifies the latest backup manifest and files.
With `ADMIN_REPORT_BACKUP_SMOKE_TEST = True`, it also restores the archive into
a temporary directory and opens the restored SQLite database. This provides a
stronger recurring check without overwriting live files.

## Database migrations and schema fingerprints

Before a production upgrade, use the local database commands while the service
is stopped to preview and verify schema changes:

```bash
envsbot db status
envsbot db migrate --dry-run
envsbot db backup
envsbot db migrate
envsbot db schema
envsbot db check
```

`envsbot db status` reports pending/unknown migrations plus the migration
catalog and live-schema fingerprints. `envsbot db schema` additionally compares
the live database with the schema produced by the current release and should
report `Schema match: yes` after a successful migration.

Applied migrations store a SHA-256 checksum. EnvsBot refuses normal startup when
an already-applied migration has been changed in the running source tree or when
the database contains a migration version unknown to that build. Existing
pre-v1.8 development databases with empty checksum fields are bootstrapped once
from the known migration catalog; a non-empty mismatch is never overwritten.

The schema fingerprint covers envsbot-managed tables, columns, foreign keys,
indexes, views and triggers, but not row contents. An unexpected fingerprint
mismatch should therefore be investigated before starting the service rather
than repaired by manually editing the migration metadata.
