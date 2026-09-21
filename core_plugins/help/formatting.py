"""Pure help metadata and presentation helpers.

This module intentionally does not own the live command registry or command
dispatch.  Keeping those concerns in :mod:`core_plugins.help` preserves the
runtime/permission boundary while making formatting independently testable.
"""

from __future__ import annotations

import inspect
import re

from utils.command import (
    CommandExample,
    CommandSubcommand,
    Role,
    command_examples,
    command_subcommands,
)


def _clean_doc(doc: str | None, prefix: str) -> str:
    """Return a readable docstring with prefix placeholders resolved."""
    if not doc:
        return ""
    return inspect.cleandoc(doc).replace("{prefix}", prefix).strip()


def _first_line(doc: str | None) -> str:
    """Return the first non-empty line from a docstring."""
    doc = _clean_doc(doc, "")
    if not doc:
        return ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _section_lines(doc: str, title: str) -> list[str]:
    """
    Extract simple NumPy-style docstring sections such as Usage or Examples.
    """
    if not doc:
        return []

    lines = doc.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == title.lower():
            start = i + 1
            # Skip underline made of dashes if present.
            if start < len(lines) and set(lines[start].strip()) <= {"-"}:
                start += 1
            break
    if start is None:
        return []

    out = []
    for line in lines[start:]:
        stripped = line.strip()
        if (
            stripped
            and re.fullmatch(r"[A-Za-z][A-Za-z /_-]+", stripped)
            and len(stripped.split()) <= 4
        ):
            break
        out.append(line.rstrip())

    return [line for line in out if line.strip()]


def _command_short(cmd_obj, prefix: str) -> str:
    """Return the command summary from decorator metadata only."""
    short = str(getattr(cmd_obj, "short", "") or "")
    return short.format(prefix=prefix) if short else "No description available."


def _command_usage(cmd_obj, prefix: str) -> list[str]:
    """Return usage lines from decorator metadata only."""
    usage = str(getattr(cmd_obj, "usage", "") or "")
    return [usage.format(prefix=prefix)] if usage else []


def _command_example_entries(cmd_obj, prefix: str) -> list[CommandExample]:
    """Return normalized, prefix-resolved command examples."""
    return [
        CommandExample(
            example.command.format(prefix=prefix),
            example.description.format(prefix=prefix),
        )
        for example in command_examples(cmd_obj)
    ]


def _command_examples(cmd_obj, prefix: str) -> list[str]:
    """Return example commands for compatibility with older callers."""
    return [example.command for example in _command_example_entries(cmd_obj, prefix)]


def _command_subcommand_entries(
    cmd_obj,
    prefix: str,
) -> list[CommandSubcommand]:
    """Return normalized, prefix-resolved structured subcommands."""
    result = []
    for subcommand in command_subcommands(cmd_obj):
        result.append(
            CommandSubcommand(
                name=subcommand.name,
                usage=subcommand.usage.format(prefix=prefix),
                short=subcommand.short.format(prefix=prefix),
                aliases=tuple(subcommand.aliases),
                examples=tuple(
                    CommandExample(
                        example.command.format(prefix=prefix),
                        example.description.format(prefix=prefix),
                    )
                    for example in subcommand.examples
                ),
                role=subcommand.role,
                context=subcommand.context,
                section=subcommand.section,
            )
        )
    return result


def _role_label(role: Role) -> str:
    return str(role)


def _context_label(cmd_obj) -> str:
    context = getattr(cmd_obj, "context", "any") or "any"
    if context != "any":
        return context

    # envsbot blocks privileged commands in normal room messages.
    if getattr(cmd_obj, "role", Role.NONE) <= Role.MODERATOR:
        return "private chat / MUC PM"
    return "room, MUC PM or private chat"


def _plugin_meta(bot, name: str) -> dict:
    meta = getattr(bot.bot_plugins, "meta", {}).get(name, {}) or {}
    if meta:
        return meta

    module = bot.bot_plugins.plugins.get(name)
    if module is None:
        return {}
    return getattr(module, "PLUGIN_META", {}) or {}


def _plugin_description(bot, name: str, module) -> str:
    meta = _plugin_meta(bot, name)
    desc = meta.get("description") or _first_line(module.__doc__)
    return desc or "No description available."


def _format_command_line(cmd_obj, prefix: str) -> str:
    aliases = sorted(set(a for a in (cmd_obj.aliases or []) if a != cmd_obj.name))
    alias_text = ""
    if aliases:
        alias_text = f" / aliases: {', '.join(prefix + a for a in aliases)}"
    return (
        f"• {prefix}{cmd_obj.name} [{_role_label(cmd_obj.role)}] — "
        f"{_command_short(cmd_obj, prefix)}{alias_text}"
    )


def _effective_subcommand_role(cmd_obj, subcommand: CommandSubcommand) -> Role:
    return subcommand.role if subcommand.role is not None else cmd_obj.role


def _effective_subcommand_context(cmd_obj, subcommand: CommandSubcommand) -> str:
    return subcommand.context or _context_label(cmd_obj)


def _visible_subcommands(cmd_obj, role: Role, prefix: str) -> list[CommandSubcommand]:
    """Return structured subcommands visible to one user role."""
    return [
        subcommand
        for subcommand in _command_subcommand_entries(cmd_obj, prefix)
        if role <= _effective_subcommand_role(cmd_obj, subcommand)
    ]


def _subcommand_aliases(cmd_obj, subcommand: CommandSubcommand, prefix: str) -> list[str]:
    """Return full command aliases for one structured subcommand."""
    root = str(cmd_obj.name)
    return [f"{prefix}{root} {alias}" for alias in subcommand.aliases]


def _access_summary(role: Role, context: str) -> str:
    """Return one compact role/context line for focused help output."""
    return f"Role: {_role_label(role)} · Context: {context}"


def _access_label(role: Role, context: str) -> str:
    """Return a short access label suitable for one command line."""
    return f"{_role_label(role)} · {context}"


def _command_access_profiles(
    cmd_obj,
    prefix: str,
    role: Role,
) -> list[tuple[Role, str]]:
    """Return visible role/context pairs represented by one command family."""
    subcommands = _visible_subcommands(cmd_obj, role, prefix)
    if subcommands:
        return [
            (
                _effective_subcommand_role(cmd_obj, subcommand),
                _effective_subcommand_context(cmd_obj, subcommand),
            )
            for subcommand in subcommands
        ]
    return [(cmd_obj.role, _context_label(cmd_obj))]


def _common_plugin_access(
    commands: list,
    prefix: str,
    role: Role,
) -> tuple[Role, str] | None:
    """Return a shared access profile when every visible command uses it."""
    profiles = {
        profile
        for cmd_obj in commands
        for profile in _command_access_profiles(cmd_obj, prefix, role)
    }
    return next(iter(profiles)) if len(profiles) == 1 else None


def _format_one_subcommand_lines(
    cmd_obj,
    subcommand: CommandSubcommand,
    prefix: str,
    *,
    common_access: tuple[Role, str] | None = None,
) -> list[str]:
    """Return compact lines for one structured subcommand."""
    effective_role = _effective_subcommand_role(cmd_obj, subcommand)
    context = _effective_subcommand_context(cmd_obj, subcommand)
    access = (effective_role, context)
    access_suffix = (
        ""
        if common_access == access
        else f" [{_access_label(effective_role, context)}]"
    )
    lines = [f"• {subcommand.usage} — {subcommand.short}{access_suffix}"]
    aliases = _subcommand_aliases(cmd_obj, subcommand, prefix)
    if aliases:
        lines.append("  Aliases: " + ", ".join(aliases))
    return lines


def _sectioned_subcommands(
    subcommands: list[CommandSubcommand],
) -> list[tuple[str, list[CommandSubcommand]]]:
    """Group subcommands by their optional help section, preserving order."""
    sections: list[tuple[str, list[CommandSubcommand]]] = []
    indexes: dict[str, int] = {}
    for subcommand in subcommands:
        section = subcommand.section.strip()
        if section not in indexes:
            indexes[section] = len(sections)
            sections.append((section, []))
        sections[indexes[section]][1].append(subcommand)
    return sections


def _format_plugin_command_lines(
    cmd_obj,
    prefix: str,
    role: Role,
    *,
    common_access: tuple[Role, str] | None = None,
) -> list[str]:
    """Return compact, consistently spaced plugin-help command lines."""
    subcommands = _visible_subcommands(cmd_obj, role, prefix)
    if subcommands:
        sections = _sectioned_subcommands(subcommands)
        has_named_sections = any(section for section, _entries in sections)
        lines: list[str] = []
        for section, entries in sections:
            if has_named_sections:
                if lines:
                    lines.append("")
                lines.append(f"{section or 'Other commands'}:")
            for subcommand in entries:
                lines.extend(
                    _format_one_subcommand_lines(
                        cmd_obj,
                        subcommand,
                        prefix,
                        common_access=common_access,
                    )
                )
        return lines

    aliases = sorted(set(a for a in (cmd_obj.aliases or []) if a != cmd_obj.name))
    access = (cmd_obj.role, _context_label(cmd_obj))
    access_suffix = (
        ""
        if common_access == access
        else f" [{_access_label(*access)}]"
    )
    lines = [
        f"• {_command_usage(cmd_obj, prefix)[0]} — "
        f"{_command_short(cmd_obj, prefix)}{access_suffix}",
    ]
    if aliases:
        lines.append("  Aliases: " + ", ".join(prefix + alias for alias in aliases))
    return lines


def _example_description_for_command(
    cmd_obj,
    example: CommandExample,
    prefix: str,
) -> str:
    """Return an explicit or subcommand-derived example description."""
    if example.description:
        return example.description

    example_tokens = _command_query_tokens(example.command, prefix)
    for subcommand in _command_subcommand_entries(cmd_obj, prefix):
        names = [subcommand.name, *subcommand.aliases]
        for name in names:
            if not name or name.startswith("<"):
                continue
            name_tokens = tuple(name.lower().split())
            primary_tokens = tuple(str(cmd_obj.name).lower().split())
            if example_tokens[: len(primary_tokens)] != primary_tokens:
                continue
            remaining = example_tokens[len(primary_tokens):]
            if remaining[: len(name_tokens)] == name_tokens:
                return subcommand.short
    return _command_short(cmd_obj, prefix)


def _format_example_lines(
    cmd_obj,
    examples: list[CommandExample] | tuple[CommandExample, ...],
    prefix: str,
) -> list[str]:
    """Render every example and its description on one compact line."""
    lines = []
    for example in examples:
        description = _example_description_for_command(cmd_obj, example, prefix)
        suffix = f" — {description}" if description else ""
        lines.append(f"• {example.command}{suffix}")
    return lines


def _examples_for_plugin_command(
    cmd_obj,
    prefix: str,
    role: Role,
) -> list[CommandExample]:
    """Prefer concise structured examples for aggregate commands."""
    subcommands = _visible_subcommands(cmd_obj, role, prefix)
    if subcommands:
        return [example for subcommand in subcommands for example in subcommand.examples]
    return _command_example_entries(cmd_obj, prefix)


def _format_command_detail(cmd_obj, prefix: str, role: Role | None = None) -> list[str]:
    lines = [
        f"📖 Command: {prefix}{cmd_obj.name}",
        _access_summary(cmd_obj.role, _context_label(cmd_obj)),
    ]

    aliases = sorted(set(a for a in (cmd_obj.aliases or []) if a != cmd_obj.name))
    if aliases:
        lines.append("Aliases: " + ", ".join(prefix + a for a in aliases))

    lines += ["", _command_short(cmd_obj, prefix), "", "Usage:"]
    for usage in _command_usage(cmd_obj, prefix):
        lines.append(f"  {usage}")

    visible_role = role if role is not None else Role.OWNER
    subcommands = _visible_subcommands(cmd_obj, visible_role, prefix)
    if subcommands:
        lines += ["", "Subcommands:"]
        lines.extend(_format_plugin_command_lines(cmd_obj, prefix, visible_role))

    examples = _examples_for_plugin_command(cmd_obj, prefix, visible_role)
    if examples:
        lines += ["", "Examples:"]
        lines.extend(_format_example_lines(cmd_obj, examples, prefix))

    return lines


def _command_context_plugin(bot, cmd_obj) -> str | None:
    """Return the plugin name matching a focused command, if any."""
    first_token = str(cmd_obj.name).split(maxsplit=1)[0].lower()
    if first_token in getattr(bot.bot_plugins, "plugins", {}):
        return first_token
    return None


def _command_query_tokens(query: str, prefix: str) -> tuple[str, ...]:
    """Return normalized command tokens for a help query."""
    query = query.strip().lower()
    if prefix and query.startswith(prefix):
        query = query[len(prefix):].strip()
    return tuple(part for part in query.split() if part)
