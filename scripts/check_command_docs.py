#!/usr/bin/env python3
"""Check that command decorators and command help metadata stay in sync."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Ensure repo imports win when the script is run from any directory.
sys.path.insert(0, str(ROOT))

from utils.command_help import COMMAND_HELP  # noqa: E402
from scripts.generate_commands_md import generate as generate_commands_md  # noqa: E402

DOCS_COMMANDS = ROOT / "docs" / "commands.md"


def _is_command_decorator(decorator: ast.AST) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    return (
        isinstance(func, ast.Name) and func.id == "command"
    ) or (
        isinstance(func, ast.Attribute) and func.attr == "command"
    )


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _iter_commands():
    for rel in ("plugins", "core_plugins"):
        for path in sorted((ROOT / rel).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if not _is_command_decorator(decorator):
                        continue
                    if not decorator.args:
                        continue
                    name = _constant_string(decorator.args[0])
                    if name:
                        keywords = {kw.arg for kw in decorator.keywords if kw.arg}
                        yield path.relative_to(ROOT), node.name, name.lower(), keywords


def main() -> int:
    errors: list[str] = []
    commands = list(_iter_commands())
    if not commands:
        errors.append("no commands found")

    docs_text = ""
    if DOCS_COMMANDS.exists():
        docs_text = DOCS_COMMANDS.read_text()
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

    for rel, func, name, keywords in commands:
        metadata = COMMAND_HELP.get(name, {})
        if not metadata and not {"short", "usage"} & keywords:
            errors.append(f"{rel}:{func}: {name}: missing COMMAND_HELP entry")
            continue
        for field in ("short", "usage"):
            if field not in keywords and not metadata.get(field):
                errors.append(f"{rel}:{func}: {name}: missing {field}")
        if "examples" not in keywords and not metadata.get("examples"):
            errors.append(f"{rel}:{func}: {name}: missing examples")
        if docs_text and f"`,{name}`" not in docs_text:
            errors.append(f"docs/commands.md: missing primary command {name!r}")

    for key, metadata in sorted(COMMAND_HELP.items()):
        if not metadata.get("short"):
            errors.append(f"COMMAND_HELP[{key!r}]: missing short")
        if not metadata.get("usage"):
            errors.append(f"COMMAND_HELP[{key!r}]: missing usage")
        if not metadata.get("examples"):
            errors.append(f"COMMAND_HELP[{key!r}]: missing examples")

    if errors:
        print("Command docs check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Command docs check passed ({len(commands)} decorated commands).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
