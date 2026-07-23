# config_cmd plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `core`
Category: `core`

Safe config inspection, validation and reload commands.

## Commands

### `,config diff`

Show config values that differ from config_sample.py defaults.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config diff [all|page|last]`

Examples:

- `,config diff` — Show config values that differ from config_sample.py defaults.
- `,config diff all` — Show config values that differ from config_sample.py defaults.

### `,config reload`

Reload config.py into the running bot where possible.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config reload`

Examples:

- `,config reload` — Reload config.py into the running bot where possible.

### `,config search`

Search visible config keys and values.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config search/find <query>`

Aliases: `,config find`

Examples:

- `,config search rss` — Search visible config keys and values.
- `,config find timeout` — Search visible config keys and values.

### `,config set`

Persist and apply one runtime-writable config value.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config set <KEY> <value>`

Examples:

- `,config set LOG_LEVEL DEBUG` — Persist and apply one runtime-writable config value.

### `,config show`

Show the effective config grouped like config_sample.py, with secrets redacted.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config show [all|page|last]`

Aliases: `,config`

Examples:

- `,config show` — Show the effective config grouped like config_sample.py, with secrets redacted.
- `,config show all` — Show the effective config grouped like config_sample.py, with secrets redacted.

### `,config unset`

Reset one runtime-writable config value to the config_sample.py default.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config unset <KEY>`

Examples:

- `,config unset LOG_LEVEL` — Reset one runtime-writable config value to the config_sample.py default.

### `,config validate`

Validate the current config.py file.

Role: `admin`<br>
Context: `private chat / MUC PM`<br>
Category: `admin`<br>
Usage: `,config validate`

Examples:

- `,config validate` — Validate the current config.py file.
