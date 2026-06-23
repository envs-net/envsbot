#!/usr/bin/env python3
"""Generate docs/commands.md from plugin command metadata."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.command import Role  # noqa: E402
from utils.config import config  # noqa: E402

PREFIX = config.get("prefix", ",")


def _clean(value: str | None) -> str:
    return inspect.cleandoc(value or "").strip()


def _first_line(doc: str | None) -> str:
    for line in _clean(doc).splitlines():
        line = line.strip()
        if line:
            return line.replace("{prefix}", PREFIX)
    return "No description available."


def _metadata(cmd):
    short = getattr(cmd, "short", "") or _first_line(cmd.handler.__doc__)
    usage = getattr(cmd, "usage", "") or f"{{prefix}}{cmd.name}"
    examples = getattr(cmd, "examples", []) or []
    context = getattr(cmd, "context", "any") or "any"
    category = getattr(cmd, "category", "") or "other"
    return {
        "short": str(short).replace("{prefix}", PREFIX),
        "usage": str(usage).replace("{prefix}", PREFIX),
        "examples": [str(e).replace("{prefix}", PREFIX) for e in examples],
        "context": str(context),
        "role": getattr(cmd, "role", Role.NONE),
        "category": str(category).strip().lower() or "other",
    }


def _plugin_meta(module, name):
    meta = getattr(module, "PLUGIN_META", {}) or {}
    return {
        "name": meta.get("name", name),
        "category": meta.get("category", "other"),
        "description": meta.get("description") or _first_line(module.__doc__),
        "hidden": bool(meta.get("hidden")),
        "version": meta.get("version", ""),
    }


def _discover_plugins():
    sources = [("core_plugins", "core"), ("plugins", "plugins")]
    seen = set()
    for package_name, source in sources:
        try:
            package = importlib.import_module(package_name)
        except Exception as exc:
            print(f"warning: could not import {package_name}: {exc}", file=sys.stderr)
            continue

        for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda item: item.name):
            name = module_info.name
            if name in seen:
                continue
            seen.add(name)
            try:
                yield name, importlib.import_module(f"{package_name}.{name}"), source
            except Exception as exc:
                print(f"warning: could not import {package_name}.{name}: {exc}", file=sys.stderr)


def _commands_from_module(module):
    seen = set()
    commands = []
    for _, obj in inspect.getmembers(module):
        if not callable(obj) or not hasattr(obj, "__commands__"):
            continue
        for registered_name, cmd in getattr(obj, "__commands__", []):
            if id(cmd) in seen or registered_name != cmd.name:
                continue
            seen.add(id(cmd))
            commands.append(cmd)
    return sorted(commands, key=lambda c: c.name)


def _category_title(category: str) -> str:
    return category.replace("_", " ").replace("-", " ").title()


def _collect():
    plugins = []
    commands = []
    for name, module, source in _discover_plugins():
        meta = _plugin_meta(module, name)
        meta["source"] = source
        if meta["hidden"]:
            continue
        plugin_commands = _commands_from_module(module)
        if not plugin_commands:
            continue
        plugins.append((name, meta, plugin_commands))
        for cmd in plugin_commands:
            commands.append((name, meta, cmd, _metadata(cmd)))
    return plugins, commands


def generate() -> str:
    plugins, commands = _collect()
    lines = [
        "# envsbot command reference",
        "",
        "This file is generated from command metadata. Do not edit it by hand.",
        "",
        "```bash",
        "python scripts/generate_commands_md.py",
        "```",
        "",
        "## Usage notes",
        "",
        f"Examples use the default command prefix `{PREFIX}`.",
        "Runtime help is available through:",
        "",
        f"- `{PREFIX}help`",
        f"- `{PREFIX}help commands`",
        f"- `{PREFIX}help categories`",
        f"- `{PREFIX}help category <name>`",
        f"- `{PREFIX}help <plugin>`",
        f"- `{PREFIX}help <command>`",
        "",
        "For paginated commands, `all` disables paging and `last` jumps to the final page.",
        "",
        "## Role legend",
        "",
        "Lower role values have more privileges. A command is visible when your role is strong enough.",
        "",
        "| Role | Meaning |",
        "| --- | --- |",
        "| `owner` | Configured owner JID with full control |",
        "| `superadmin` | High-level administration |",
        "| `admin` | Normal bot administration |",
        "| `moderator` | Room/plugin moderation commands |",
        "| `trusted` | Trusted user commands |",
        "| `user` | Normal user commands |",
        "| `new` / `none` | Limited or unknown users |",
        "| `banned` | No command access |",
        "",
        "## Plugin overview",
        "",
        "| Plugin | Source | Category | Description |",
        "| --- | --- | --- | --- |",
    ]

    for name, meta, _plugin_commands in plugins:
        lines.append(f"| `{name}` | `{meta['source']}` | `{meta['category']}` | {meta['description']} |")

    by_category: dict[str, list[tuple[str, object, dict]]] = {}
    for _plugin_name, _meta, cmd, data in commands:
        by_category.setdefault(data["category"], []).append((_plugin_name, cmd, data))

    lines += ["", "## Commands by category", ""]
    for category in sorted(by_category):
        items = sorted(by_category[category], key=lambda item: item[1].name)
        lines += [f"### {_category_title(category)}", "", "| Command | Role | Context | Description |", "| --- | --- | --- | --- |"]
        for _plugin_name, cmd, data in items:
            lines.append(
                f"| `{PREFIX}{cmd.name}` | `{data['role']}` | `{data['context']}` | {data['short']} |"
            )
        lines.append("")

    lines += ["## Plugin command details", ""]
    for name, meta, plugin_commands in plugins:
        lines += [
            f"### {meta['name']}",
            "",
            f"Source: `{meta.get('source', 'plugins')}`",
            f"Category: `{meta['category']}`",
            "",
            str(meta["description"]),
            "",
        ]
        for cmd in plugin_commands:
            data = _metadata(cmd)
            aliases = sorted(set(a for a in (cmd.aliases or []) if a != cmd.name))
            lines += [
                f"#### `{PREFIX}{cmd.name}`",
                "",
                data["short"],
                "",
                f"Role: `{data['role']}`  ",
                f"Context: `{data['context']}`  ",
                f"Category: `{data['category']}`  ",
                f"Usage: `{data['usage']}`",
                "",
            ]
            if aliases:
                lines += ["Aliases: " + ", ".join(f"`{PREFIX}{alias}`" for alias in aliases), ""]
            if data["examples"]:
                lines.append("Examples:")
                lines.append("")
                for example in data["examples"]:
                    lines.append(f"- `{example}`")
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    output = ROOT / "docs" / "commands.md"
    output.write_text(generate(), encoding="utf-8")
    print(f"wrote {output.relative_to(ROOT)}")
