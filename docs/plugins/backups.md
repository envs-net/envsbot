# backups plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

Managed ZIP backups and restore helpers.

## Commands

### `,backup create`

Create a managed ZIP backup archive.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,backup create [reason]`

Aliases: `,backup`

Examples:

- `,backup create` — Create a managed ZIP backup archive.
- `,backup create before config change` — Create a managed ZIP backup archive.
- `,backup` — Create a managed ZIP backup archive.

### `,backup list`

List managed backup archives.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,backup list [all|page|last]`

Aliases: `,backup ls`, `,backups`

Examples:

- `,backup list` — List managed backup archives.
- `,backup list all` — List managed backup archives.

### `,backup prune`

Prune managed backup archives, with optional dry-run.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,backup prune [dry-run] [keep <n>] [days <n>]`

Examples:

- `,backup prune dry-run` — Prune managed backup archives, with optional dry-run.
- `,backup prune keep 20 days 30` — Prune managed backup archives, with optional dry-run.

### `,backup restore-plan`

Show what a restore would overwrite without writing files.

Role: `owner`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,backup restore-plan <archive|last>`

Aliases: `,backup restore dry-run`, `,restore dry-run`

Examples:

- `,backup restore-plan last` — Show what a restore would overwrite without writing files.

### `,backup show`

Show manifest details for one managed backup archive.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,backup show <archive|last>`

Examples:

- `,backup show last` — Show manifest details for one managed backup archive.

### `,backup verify`

Verify one managed backup archive.

Role: `admin`<br>
Context: `private recommended`<br>
Category: `admin`<br>
Usage: `,backup verify <archive|last>`

Examples:

- `,backup verify last` — Verify one managed backup archive.

### `,restore`

Restore a managed backup after explicit confirmation.

Role: `owner`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,restore <archive|last> confirm`

Aliases: `,backup restore`

Examples:

- `,restore last confirm` — Restore a managed backup after explicit confirmation.
