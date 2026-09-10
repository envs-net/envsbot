# Production observation after a release

Use this checklist for the first 72 hours after a significant envsbot release. It is intentionally observational: do not change state merely to make a metric look clean. Capture anomalies first, then diagnose them.

## Baseline: immediately after deployment

Verify the installed versions without connecting a second bot instance:

```bash
envsbot --version
./scripts/deploy.sh status
systemctl status envsbot --no-pager
```

In XMPP, capture:

```text
,bot status full
,doctor full
,tasks failed
,tasks stale
,outbox status
```

Expected baseline:

- the bot version and `envs-xmpp` version are the intended release pair;
- all configured MUCs join;
- no failed/stale supervised tasks;
- outbox dead-letter count is zero;
- no repeating reconnect/startup loop;
- backup/database/message-cache health is not degraded.

## Journal review

Check the current boot and the period since deployment:

```bash
journalctl -u envsbot -b --no-pager
journalctl -u envsbot --since "24 hours ago" --no-pager \
  | grep -Ei 'warning|error|exception|traceback|restart|stale|locked|timeout'
```

One transient network warning can be legitimate. Repeated worker restarts, repeated database locks, reconnect loops, unhandled tracebacks or continuously growing dead-letter state need investigation.

## 24-hour checkpoint

Repeat `,bot status full`, `,tasks failed`, `,tasks stale` and `,outbox status`. Compare:

- process RSS/CPU and system load;
- task restart counters;
- watchdog/event-loop warnings;
- outbox pending/dead counts;
- room join/routing issues;
- message-cache write/retry/degraded state;
- backup freshness.

A short-lived pending outbox is normal. A queue that only grows is not.

## 48-hour checkpoint

Repeat the 24-hour checks and inspect release-sensitive background features that are expected to have run by now, especially periodic backups, RSS/feed delivery, reminders and update checks where enabled.

Confirm that no worker shows a steadily increasing restart count and that the process is not showing unexplained monotonic memory growth.

## 72-hour acceptance checkpoint

Treat the release as production-stable when all of the following are true:

- no unhandled exceptions or crash loops;
- no persistent failed/stale/restarting tasks;
- no unexplained database-lock errors;
- no dead outbox entries and no sustained queue growth;
- MUC joins/rejoins and direct-message routing behave normally;
- watchdog lag is bounded and not continuously suppressing heartbeats;
- backups remain fresh and verifiable;
- CPU/RSS are broadly stable for the workload;
- no user-visible regression has been reported.

If a problem appears, preserve the relevant `journalctl` range plus `,bot status full`, `,doctor full` and `,tasks full all` output before restarting whenever operationally safe.
