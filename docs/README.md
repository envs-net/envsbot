# EnvsBot documentation

This directory contains the operator and command documentation for EnvsBot.

## Index

- [`commands.md`](commands.md) - generated command reference from the live command metadata
- [`help.md`](help.md) - runtime help behavior and usage examples
- [`maintenance.md`](maintenance.md) - offline SQLite maintenance workflow

Operational notes:

- `,status full` includes supervised background-task state.
- `,version` shows the running EnvsBot version and the latest checked release.
- `,checkupdate` / `,updatecheck` performs a manual GitHub release check.
- `,audit last` shows recent administrative changes such as role updates, room changes, plugin reloads and config reloads.
- Role changes are guarded so the configured owner and superadmins cannot be modified by lower roles.

## Regenerate command reference

Run this after changing command decorators or `utils/command_help.py`:

```bash
python scripts/generate_commands_md.py
```
