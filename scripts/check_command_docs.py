#!/usr/bin/env python3
"""Check that generated command docs match the command registry metadata."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_commands_md import generate as generate_commands_md  # noqa: E402
from utils.command_registry import decorated_command_records  # noqa: E402

DOCS_COMMANDS = ROOT / "docs" / "commands.md"


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
