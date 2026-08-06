# Bot architecture

This document describes the runtime structure of EnvsBot after the core split.
It is intended for maintainers who need to debug startup, command dispatch,
permissions, plugin loading, diagnostics or shutdown behaviour.

## High-level flow

```text
XMPP stanza
   │
   ▼
bot.routing
   │  public MUC messages and private/MUC-PM messages
   ├──► bot.message_cache (RAM + SQLite persistence)
   ▼
bot.dispatch
   │  prefix parsing, command lookup, CommandContext, permissions, rate limit
   ▼
utils.command_execution
   │  timeout, slow-command logging, audit wrapper, exception handling
   ▼
command handler
   │  core_plugins/* or plugins/*
   ▼
bot.messages
      reply formatting, no-store hints and safe async send
```

The public runtime class is still `envsbot.Bot`. The class is intentionally kept
as the stable entrypoint, while most behaviour is delegated to small mixins and
utility modules in `bot/` and `utils/`.

## Runtime modules

### `envsbot.py`

`envsbot.py` remains the console entrypoint and compatibility layer. It wires
configuration, database access, the plugin manager, presence tracking, rate
limits and the mixins from `bot/` into the final `Bot` class.

Keep this file focused on application wiring. New runtime logic should normally
live in one of the smaller modules below.

### `bot.connection`

Connection helpers build the login JID, optional resource and Slixmpp connect
keyword arguments. They intentionally inspect the installed Slixmpp `connect()`
signature so the bot can support different Slixmpp versions and both STARTTLS
and direct TLS deployments.

Main responsibilities:

- normalize configured JID/resource values
- derive a fallback domain from the configured or bound JID
- build supported `connect()` keyword arguments
- log the connection target in a stable key/value format

### `bot.routing`

Routing receives raw XMPP message events and decides whether they should be sent
to command dispatch.

Main responsibilities:

- ignore the bot's own MUC messages
- store each accepted incoming message once in the shared message cache
- route public groupchat messages
- route direct private messages
- route MUC private messages through the same private-message handler

### `bot.dispatch`

Dispatch is the command gatekeeper. It converts a message into a normalized
command execution request.

Main responsibilities:

- resolve the command prefix
- find the registered command object
- resolve real sender JID and room context
- build `CommandContext`
- check shutdown/accepting-command state
- apply room/private restrictions and role checks
- apply command rate limiting
- call `CommandExecutor`

### `bot.context` / `utils.command_context`

`CommandContext` is the central command runtime structure. It contains the bot,
message, command name, parsed args, sender JID, room JID, nick, role and context
flags.

New core code should prefer passing `CommandContext` where practical instead of
re-computing sender, room and role information.

### `bot.permissions` and `utils.permissions`

`bot.permissions` resolves user roles from config, the database and live room
presence. `utils.permissions` contains pure decision helpers such as whether a
command is executable in the current context.

Main responsibilities:

- configured owner recognition
- stored role lookup
- room-admin/owner elevation to moderator
- rate-limit bypass role checks
- centralized command permission decisions

### `bot.messages`

Message helpers keep reply behaviour consistent across plugins.

Main responsibilities:

- groupchat mention prefixing
- private vs groupchat reply target selection
- no-store hint handling
- thread propagation
- safe sync/async `send()` handling
- test reply capture

### `bot.lifecycle`

Lifecycle code handles startup, restart notifications, startup backups and
shutdown cleanup.

Main responsibilities:

- ready/startup sequence
- optional startup backup
- plugin ready hooks
- restart notification delivery
- accepting-command shutdown gate
- supervised task cancellation
- plugin unload timeout
- shared message-cache flush before database close
- idempotent database flush and close

### `bot.audit`

Audit writes are best-effort. The helper checks whether the database audit log is
available, redacts actor/target/details and never lets audit failures break the
user-facing command path.

## Command registry

The command registry is the source of truth for command metadata.

```text
@command(... metadata ...)
        │
        ▼
utils.command.COMMANDS
        │
        ├── runtime dispatch
        ├── ,help output
        ├── docs/commands.md generation
        ├── scripts/check_command_docs.py
        └── envsbot --check preflight
```

Every command decorator must include `short`, `usage`, `examples`, `category`
and `context`. `utils.command_help` is only a compatibility facade for older
imports and generates its data from the live registry.

Useful commands while developing command metadata:

```bash
python scripts/generate_commands_md.py
python scripts/check_command_docs.py
```

## Plugin manager structure

`utils.plugin_manager.PluginManager` remains the public manager class, with
helper modules for the split responsibilities:

- `utils.plugin_manager_discovery` discovers plugin modules
- `utils.plugin_manager_dependencies` validates optional dependencies
- `utils.plugin_manager_lifecycle` calls load/ready/unload hooks
- `utils.plugin_manager_diagnostics` collects metadata, runtime state and doctor hooks

Plugins can expose optional hooks:

```python
async def on_load(bot): ...
async def on_ready(bot): ...
async def on_unload(bot): ...
async def cleanup_room_state(bot, room_jid: str) -> dict[str, int]: ...
async def get_runtime_state(bot, room_jid: str | None = None) -> dict: ...
async def doctor(bot, room_jid: str | None = None) -> list[str]: ...
```

## State and persistence

The database layer lives in `database/`. Runtime plugin state should normally go
through `bot.db.users.plugin(<plugin>)` instead of ad-hoc files.

Important state paths:

- `database.manager.DatabaseManager` owns the SQLite connection and migrations
- `database.users.UserManager` stores user and per-plugin JSON state
- `database.rooms.RoomManager` stores known rooms and room feature state
- `database.audit.AuditLog` stores operational audit events
- `database.message_cache.MessageCacheStore` persists recent message bodies
- `database.idlerpg.IdleRPGStateStore` normalizes IdleRPG rooms, players, seasons and events
- `utils.message_cache.MessageCache` serves shared recent history from RAM
- `utils.task_supervisor.TaskSupervisor` tracks long-running async tasks


## IdleRPG normalized persistence

`database.idlerpg.IdleRPGStateStore` keeps the active game model split across
`idlerpg_rooms`, `idlerpg_players`, `idlerpg_seasons` and `idlerpg_events`.
The plugin still works with one in-memory room dictionary, but persistence uses
incremental row updates instead of rewriting one global JSON blob. The first
load after migration imports legacy `users_runtime` state transactionally and
then removes the old plugin-global value.

Public JSON export is deliberately separate from database persistence. The
async state layer takes an immutable snapshot, serializes and writes it through
`asyncio.to_thread()`, and uses one export lock to coalesce overlapping
automatic refreshes.

## Shared recent-message cache

`envsbot.Bot` owns one `bot.message_cache` instance for every plugin. Incoming
public MUC, direct-chat and MUC-PM messages are inserted once by `bot.routing`.
Plugins should only query the shared cache instead of registering their own
message-history stores.

`MESSAGE_CACHE_SIZE` is the maximum number of retained entries **per
conversation**. The same limit applies to every plugin. Reads are served from
RAM, while writes are batched into the SQLite `message_cache` table. The cache
is loaded before plugins start and flushed before the database closes, so reply
lookups keep working after a normal restart. Reducing the configured size also
prunes older persisted rows on the next start.

Conversation keys deliberately keep scopes separate:

- public MUC history is keyed by bare room JID
- direct chats are keyed by the sender's bare JID
- MUC private messages are keyed by room and occupant nick

Useful read methods are:

```python
entries = bot.message_cache.get_messages(conversation, limit=20)
entry = bot.message_cache.get_by_id(conversation, stanza_id)
entry = bot.message_cache.get_last(conversation, predicate=filter_entry)
```

Message bodies are persisted as plain text in the bot database and are included
in normal database backups. Operators should choose `MESSAGE_CACHE_SIZE` with
that retention and privacy implication in mind.

## Diagnostics and preflight

Runtime diagnostics are available through:

```text
,doctor
,doctor all
,doctor <section-or-plugin>
,tasks
,plugin diagnose <plugin>
,plugin state <plugin> [room_jid]
,rooms diagnose <room_jid>
```

Local deployment diagnostics are available without connecting to XMPP:

```bash
python -m envsbot --check
envsbot --check
```

Preflight checks config loading, sample/default compatibility, plugin imports,
plugin metadata, command metadata, generated command docs, migrations, backup
writability, runtime files and SQLite integrity/read-write behaviour.

## Logging and redaction

Core logs prefer stable key/value messages:

```text
[COMMAND] event=done command=doctor actor=user@example.org room=room@example.org status=ok duration_ms=42
[LIFECYCLE] event=shutdown phase=tasks status=ok cancelled=21
[DB] event=migration status=ok version=0004_message_cache
```

Use `utils.redaction` for log and audit values that may contain secrets, tokens,
URLs with credentials or long user-controlled strings.

## Where to add new code

- XMPP connection details: `bot.connection`
- message routing: `bot.routing`
- command permission or dispatch decisions: `bot.dispatch` / `utils.permissions`
- reply formatting: `bot.messages`
- startup or shutdown behaviour: `bot.lifecycle`
- audit writes: `bot.audit`
- command metadata and docs: `utils.command` / `utils.command_registry`
- shared room feature toggles: `utils.room_toggles`
- MUC identity helpers: `utils.xmpp_identity`
- local deployment checks: `utils.preflight`

Avoid adding new cross-cutting helpers to individual plugins when a core module
already owns the responsibility.

## Durable delivery, runtime supervision and operational state

Failed or temporarily deferred XMPP deliveries are owned by the central
`PersistentOutbox`. The queue is stored in `outbox_messages`, uses atomic
claiming, exponential retry backoff and a dead-letter state, and resumes after
a process restart. Plugins should use `utils.outbox.durable_send()` or
`bot.reply(..., persist=True, category=...)` for messages whose delivery must
survive a disconnect. Message bodies remain private in the SQLite database and
are included in managed backups.

Long-running workers use `TaskSupervisor.create_resilient()` through
`create_resilient_plugin_task()`. Repeated failures move a worker through
closed, half-open and open circuit states. A successful `,tasks restart
<plugin>` clears the old circuit diagnostics and starts a fresh worker.

`RuntimeWatchdog` measures event-loop lag and sends native systemd `sd_notify`
heartbeats without adding an external dependency. The application exposes this
state only through local/XMPP diagnostics; no HTTP or external metrics endpoint
is opened.

Aggregate command usage is kept in `command_usage_daily`. It stores command
names, daily counters and success/failure totals, but no sender JIDs, message
bodies or command arguments. Operational settings shared by defaults, runtime
reload and validation are declared in `utils.config.spec` to reduce duplicated
configuration plumbing.
