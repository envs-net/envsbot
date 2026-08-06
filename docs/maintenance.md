# Maintenance

This document covers maintenance tasks that should be run by the server administrator outside the running bot process.

## SQLite database maintenance

Do not run `VACUUM` from a live bot command. `VACUUM` rewrites the SQLite database file and should be performed during a planned maintenance window while envsbot is stopped.

Recommended manual procedure:

```bash
systemctl stop envsbot.service

sqlite3 envsbot.db "PRAGMA integrity_check;"
sqlite3 envsbot.db "PRAGMA optimize;"
sqlite3 envsbot.db "VACUUM;"

systemctl start envsbot.service
```

Adjust the service name and database path if your installation uses different names.

For a quick online status check from the bot, use:

```text
,bot status
```

Use `,bot status full` for additional SQLite page details.


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
start; this also covers service restarts. Each archive contains `bot.db`,
`config.py`, `vcard.py`, `chat_slang.csv` and a `manifest.json` when those
files exist. Restore is owner-only and creates a
safety backup before overwriting files. Restart envsbot after restoring
`config.py` or `vcard.py` changes.

Backup archives contain secrets such as the bot password and optional API keys.
Keep them private and include them in your normal server backup policy.

## Automatic online maintenance

The running bot performs lightweight online maintenance at
`DB_MAINTENANCE_INTERVAL_SECONDS`:

- `PRAGMA optimize`
- a passive WAL checkpoint
- pruning old aggregate command-usage rows

The task never runs `VACUUM`; planned offline `VACUUM` remains the administrator
procedure described above. Results and the last error are visible through
`,doctor database` and the optional daily admin report.

The optional report normally verifies the latest backup manifest and files.
With `ADMIN_REPORT_BACKUP_SMOKE_TEST = True`, it also restores the archive into
a temporary directory and opens the restored SQLite database. This provides a
stronger recurring check without overwriting live files.
