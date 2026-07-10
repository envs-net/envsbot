#!/usr/bin/env python3
"""Check that generated command docs match the command registry metadata."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_commands_md import (  # noqa: E402
    generate as generate_commands_md,
    generate_plugin_docs,
)
from utils.command_registry import decorated_command_records  # noqa: E402

DOCS_COMMANDS = ROOT / "docs" / "commands.md"
DOCS_PLUGINS = ROOT / "docs" / "plugins"


def validate_command_docs(docs_path: Path = DOCS_COMMANDS) -> tuple[list[str], int]:
    """Return command-doc validation errors and decorated command count.

    This function is intentionally importable so ``envsbot --check`` can reuse
    the same source-of-truth validation as CI without spawning another Python
    process or accidentally using a different interpreter.
    """
    errors: list[str] = []
    commands = decorated_command_records()
    if not commands:
        errors.append("no commands found")

    docs_text = ""
    if docs_path.exists():
        docs_text = docs_path.read_text(encoding="utf-8")
        if "This file is generated from command metadata" not in docs_text:
            errors.append("docs/commands.md is missing generated-file marker")
        else:
            generated = generate_commands_md()
            if docs_text != generated:
                errors.append(
                    "docs/commands.md is out of date; run "
                    "python scripts/generate_commands_md.py"
                )
    else:
        errors.append("docs/commands.md is missing")

    plugin_docs = generate_plugin_docs()
    for rel_name, generated_doc in plugin_docs.items():
        path = DOCS_PLUGINS / rel_name
        if not path.exists():
            errors.append(f"docs/plugins/{rel_name} is missing")
            continue
        if path.read_text(encoding="utf-8") != generated_doc:
            errors.append(
                f"docs/plugins/{rel_name} is out of date; run "
                "python scripts/generate_commands_md.py"
            )

    for plugin, _meta, cmd in commands:
        name = str(getattr(cmd, "name", "")).lower()
        if not name:
            errors.append(f"{plugin}: command with empty name")
            continue
        for field in ("short", "usage", "category", "context"):
            value = str(getattr(cmd, field, "") or "").strip()
            if not value:
                errors.append(f"{plugin}:{name}: missing {field}")
        examples = list(getattr(cmd, "examples", []) or [])
        if not examples:
            errors.append(f"{plugin}:{name}: missing examples")
        if docs_text and f"`,{name}`" not in docs_text:
            errors.append(f"docs/commands.md: missing primary command {name!r}")
        plugin_doc_name = f"{plugin.replace('/', '_')}.md"
        plugin_doc = plugin_docs.get(plugin_doc_name, "")
        if plugin_doc and f"### `,{name}`" not in plugin_doc:
            errors.append(f"docs/plugins/{plugin_doc_name}: missing command {name!r}")

    return errors, len(commands)


def main() -> int:
    errors, command_count = validate_command_docs()
    if errors:
        print("Command docs check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Command docs check passed ({command_count} decorated commands).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
