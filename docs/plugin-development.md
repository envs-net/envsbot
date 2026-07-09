# Plugin development

EnvsBot plugins are small Python modules that register commands, optional event
handlers and optional runtime hooks. Core/admin plugins live in `core_plugins/`;
normal feature plugins live in `plugins/` and can be loaded, unloaded and
reloaded at runtime.

## Minimal plugin

A minimal plugin needs metadata and at least one command:

```python
from utils.command import Role, command

PLUGIN_META = {
    "name": "example",
    "version": "0.1.0",
    "description": "Small example plugin.",
    "category": "utility",
}

HELP = {
    "commands": {
        "example": {
            "usage": ",example",
            "description": "Reply with a small example message.",
        },
    },
}

@command("example", role=Role.USER)
async def example_command(bot, sender_jid, nick, args, msg, is_room):
    bot.reply(msg, "example ok")
```

Command functions are async and receive the normalized sender JID, nick,
remaining arguments, the original stanza and a boolean telling whether the
command came from a room context.

## Command metadata

Use `@command(...)` for every command entry. The decorator controls the public
command name, required role, aliases and context limits:

```python
@command(
    "example admin",
    role=Role.ADMIN,
    aliases=["example debug"],
    room_only=False,
    private_only=False,
)
async def example_admin_command(bot, sender_jid, nick, args, msg, is_room):
    ...
```

Keep command names stable because they are used by generated docs, runtime help
and permission checks. Run the docs generator after changing command metadata:

```bash
python scripts/generate_commands_md.py
```

## Help metadata

Plugins should expose a `HELP` dictionary. This powers `,help <plugin>`, the
generated command reference and focused command help. Keep usage strings short
and include room-context hints when commands behave differently in MUCs, MUC PMs
or normal private chats.

Useful fields are:

```python
HELP = {
    "summary": "Short plugin summary.",
    "commands": {
        "example": {
            "usage": ",example [arg]",
            "description": "What the command does.",
            "examples": [",example test"],
        },
    },
}
```

## Room feature toggles

Room-toggleable plugins should define a stable plugin name in `PLUGIN_META` and
check the room feature state before doing room work. Command handlers can use the
shared helper from `_core` when they expose enable/disable style controls.
Operators manage room toggles with:

```text
,rooms plugins <room_jid>
,rooms enable <room_jid> <plugin>
,rooms disable <room_jid> <plugin>
,rooms set_plugin_defaults <room_jid>
```

Defaults for new rooms come from `ROOM_PLUGIN_DEFAULTS` in `config.py`.

## Runtime store

Plugin state should go through the per-plugin runtime store instead of module
specific files where possible:

```python
store = bot.db.users.plugin("example")
state = await store.get_global("EXAMPLE", default={})
await store.set_global("EXAMPLE", state)
```

Use stable top-level keys and JSON-serializable values. When a plugin stores
room-specific data, normalize room JIDs by stripping resources and lowercasing
before comparing rooms.

## Permissions and grants

Global bot roles use `utils.command.Role`. Lower numeric values mean stronger
permissions: owner, superadmin, admin, moderator, trusted, user, new, none and
banned.

Room-scoped delegation is handled through plugin grants:

```text
,users grant <jid> rss pin poll
,users revoke <jid> rss
,users grants <jid>
```

A grant should not be treated as a global admin role. For room-mutating actions,
combine the grant with room admin/owner checks or use existing helpers from the
core plugins.

## Lifecycle hooks

The plugin manager calls optional hooks when a plugin is loaded, made ready,
unloaded or when room state is deleted.

```python
async def on_load(bot):
    # Register event handlers or initialize lightweight module state.
    ...

async def on_ready(bot):
    # Start background tasks after the bot is connected and rooms are known.
    ...

async def on_unload(bot):
    # Cancel tasks and release external resources.
    ...

async def cleanup_room_state(bot, room_jid: str) -> dict[str, int]:
    # Remove plugin data for a deleted room.
    return {"rooms": 1, "tasks": 0}

async def on_room_delete(bot, room_jid: str):
    # Optional notification-style hook; prefer cleanup_room_state for cleanup.
    ...
```

`cleanup_room_state()` should be idempotent. It should return small counters so
`,rooms delete` and diagnostics can summarize what changed.

## Background tasks

Use the shared task supervisor instead of unmanaged `asyncio.create_task()` when
possible. Supervised tasks show up in `,tasks`, can be restarted and are easier
to inspect during `,doctor` runs.

```python
from utils.task_supervisor import create_plugin_task

task = create_plugin_task(
    bot,
    "example",
    example_loop(bot),
    name="example-loop",
)
```

Long-running loops should handle cancellation cleanly:

```python
try:
    while True:
        await do_work()
        await asyncio.sleep(60)
except asyncio.CancelledError:
    raise
```

## Runtime diagnostics

A plugin can expose small state counters for `,plugin state`, room diagnostics and `,doctor plugin-health`:

```python
async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int]:
    if room_jid:
        return {"items": 3, "tasks": 1}
    return {"items": 12, "tasks": 4}
```

Return compact numeric or string values. Do not return large raw state objects, secrets, full feed contents or user-private data.

For richer operator output, expose a doctor hook:

```python
async def doctor(bot, room_jid: str | None = None) -> list[str]:
    state = await get_runtime_state(bot, room_jid=room_jid)
    return [f"✅ example: items={state.get('items', 0)}"]
```

Doctor hooks should be fast, side-effect free and safe to run in normal operations.

## Audit logging

Administrative changes should write audit events through the shared audit helper
when available. Good candidates are persistent room changes, plugin reloads,
role changes, config reloads, backup/restore operations and destructive plugin
commands.

Include a stable event type, actor, target and small JSON-serializable details.
Avoid storing secrets or full message bodies.

## Common pitfalls

- Do not create unsupervised background tasks unless there is no practical
  alternative.
- Do not assume a command always runs in a room; private chat and MUC PM paths
  differ.
- Do not store room JIDs with resources unless the resource is intentionally
  part of the key.
- Do not expose config secrets, passwords, tokens or private JIDs in diagnostics.
- Do not mutate dictionaries while iterating over them; iterate over snapshots
  such as `list(mapping.items())` when cleanup can change the mapping.
- Keep cleanup hooks idempotent so repeated room deletion or plugin reloads are
  safe.
- Keep help metadata and generated docs in sync with command decorators.


## Shared HTTP fetch utility

Plugins that fetch external HTTP resources should use `utils.http_fetch` instead
of creating their own sessions and redirect logic. The shared helpers provide
consistent timeouts, user-agent handling, byte limits and SSRF-safe redirect
handling for user-supplied URLs. Fixed, bot-controlled API endpoints can use
`passthrough_validator`; user-supplied URLs should keep URL safety validation
enabled.

```python
from utils.http_fetch import fetch_json, fetch_text, passthrough_validator

result = await fetch_json(
    "https://api.example.org/status",
    validator=passthrough_validator,
    max_bytes=262144,
)
```

## Command/docs CI checks

After changing commands or command metadata, run:

```bash
python scripts/generate_commands_md.py
python scripts/check_command_docs.py
python -m compileall -q .
pytest
```

The CI pipeline runs these checks so generated docs and runtime help do not drift.
