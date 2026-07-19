#!/usr/bin/env python3
"""Generate command docs from plugin command metadata."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.command import Role  # noqa: E402
from utils.config import config  # noqa: E402
from utils.command_registry import (  # noqa: E402
    decorated_commands_from_module,
    discover_command_modules,
    plugin_metadata,
)

PREFIX = config.get("prefix", ",")
PLUGIN_DOCS_DIR = ROOT / "docs" / "plugins"


def _metadata(cmd):
    """Return docs metadata from the command decorator only."""
    short = str(getattr(cmd, "short", ""))
    usage = str(getattr(cmd, "usage", ""))
    examples = list(getattr(cmd, "examples", []) or [])
    context = str(getattr(cmd, "context", "any") or "any")
    category = str(getattr(cmd, "category", "") or "other")
    return {
        "short": short.replace("{prefix}", PREFIX),
        "usage": usage.replace("{prefix}", PREFIX),
        "examples": [str(e).replace("{prefix}", PREFIX) for e in examples],
        "context": context,
        "role": getattr(cmd, "role", Role.NONE),
        "category": category.strip().lower() or "other",
    }


def _plugin_meta(module, name, source="plugins"):
    """Return plugin metadata through the shared registry helper."""
    return plugin_metadata(module, name, source)


def _discover_plugins():
    """Discover plugin modules through the shared command registry helpers."""
    for name, module, source in discover_command_modules():
        yield name, module, source


def _commands_from_module(module):
    """Return commands from the shared command registry discovery helper."""
    return decorated_commands_from_module(module)


def _category_title(category: str) -> str:
    return category.replace("_", " ").replace("-", " ").title()


def _table_cell(value: object) -> str:
    """Return markdown table-safe text."""
    return str(value).replace("\n", " ").replace("|", "\\|")


def _inline_code(value: object) -> str:
    """Return text that is safe to show inside inline backticks."""
    return str(value).replace("\n", "\\n")


def _plugin_doc_filename(name: str) -> str:
    return f"{name.replace('/', '_')}.md"


def _plugin_doc_relpath(name: str) -> str:
    return f"plugins/{_plugin_doc_filename(name)}"


def _room_feature_names() -> list[str]:
    try:
        from utils.room_features import available_features

        return available_features()
    except Exception:
        return []


def _room_feature_section() -> list[str]:
    features = _room_feature_names()
    lines = [
        "## Room plugin settings",
        "",
        "Room-scoped plugin toggles are managed through the `rooms` commands:",
        "",
        f"- `{PREFIX}rooms plugins [<room_jid>] [all|page|last]`",
        f"- `{PREFIX}rooms enable [<room_jid>] <plugin>`",
        f"- `{PREFIX}rooms disable [<room_jid>] <plugin>`",
        f"- `{PREFIX}rooms set_plugin_defaults [<room_jid>]`",
        "",
        "Examples:",
        "",
        f"- `{PREFIX}rooms enable ducks`",
        f"- `{PREFIX}rooms disable ducks`",
        f"- `{PREFIX}rooms enable room@conference.example.org ducks`",
        f"- `{PREFIX}rooms plugins room@conference.example.org all`",
        "",
        "In a room or MUC PM the target room can usually be inferred. In a normal private chat, pass `<room_jid>` explicitly. The sender must be room owner/admin or have a bot moderator/admin role.",
        f"Defaults shown by these commands come from `ROOM_PLUGIN_DEFAULTS` in `config.py` merged with internal fallbacks. Existing per-room overrides stay in the database until `{PREFIX}rooms set_plugin_defaults` is used for that room.",
    ]
    if features:
        lines += [
            "",
            "Known room feature names:",
            "",
            "`" + "`, `".join(features) + "`",
            "",
            "`information` can also be addressed as `info`.",
        ]
    return lines


def _collect():
    plugins = []
    commands = []
    for name, module, source in _discover_plugins():
        meta = _plugin_meta(module, name, source)
        if meta["hidden"]:
            continue
        plugin_commands = _commands_from_module(module)
        if not plugin_commands:
            continue
        plugins.append((name, meta, plugin_commands))
        for cmd in plugin_commands:
            commands.append((name, meta, cmd, _metadata(cmd)))
    return plugins, commands


def _reminder_notes() -> list[str]:
    return [
        "## Reminders from replies",
        "",
        "Reply to an existing message and provide only the reminder time. The replied-to message becomes the reminder text:",
        "",
        "```text",
        f"{PREFIX}remind 1h",
        f"{PREFIX}remind 2026-07-10 13:23",
        f"{PREFIX}remind 2026-07-10 13:23 Europe/Berlin",
        "```",
        "",
        "The shared persistent message cache is used to resolve the XMPP reply target. A client-provided XEP-0461 plain-text fallback quote is used when the original message is no longer available in the cache.",
        "",
        "## Timezone-aware reminders",
        "",
        "Relative reminders do not need a timezone:",
        "",
        "```text",
        f"{PREFIX}remind 10m check the logs",
        f"{PREFIX}remind 1h30m restart the service",
        f"{PREFIX}remind 2d review the backup plan",
        "```",
        "",
        "Absolute reminders use the user's configured timezone, the bot fallback, or an explicit timezone token:",
        "",
        "```text",
        f"{PREFIX}remind 2026-07-10 13:23 deploy window",
        f"{PREFIX}remind 2026-07-10 13:23 CEST deploy window",
        f"{PREFIX}remind 2026-07-10 13:23 Europe/Berlin deploy window",
        f"{PREFIX}remind 2026-07-10 13:23 +02:00 deploy window",
        "```",
        "",
        "For absolute dates without an explicit timezone, the plugin resolves the timezone in this order:",
        "",
        "1. explicit timezone in the command, for example `CEST`, `Europe/Berlin` or `+02:00`",
        f"2. the user's stored `TIMEZONE`, set with `{PREFIX}timezone set Europe/Berlin`",
        "3. `REMINDER_DEFAULT_TIMEZONE` from `config.py`",
        "4. UTC as final fallback",
        "",
        "Supported command timezone forms:",
        "",
        "- `UTC`, `GMT`, `Z`",
        "- `CET` / `MEZ`",
        "- `CEST` / `MESZ`",
        "- IANA timezone names such as `Europe/Berlin`",
        "- fixed offsets such as `+02:00`, `+0200` or `-05:00`",
        "",
        "Prefer IANA timezone names such as `Europe/Berlin` for user profiles and bot defaults because they handle daylight saving time automatically. `CET` and `CEST` are fixed offsets and mean exactly UTC+1 and UTC+2.",
        "",
        "Configuration fallback:",
        "",
        "```python",
        'REMINDER_DEFAULT_TIMEZONE = "UTC"',
        "```",
        "",
    ]


def _rss_notes() -> list[str]:
    return [
        "## RSS templates",
        "",
        "RSS posts can use a room-wide template or a feed-specific template. Feed-specific templates take precedence over the room template, and the room template takes precedence over the built-in default.",
        "",
        "### Template variables",
        "",
        "- `$feed_title` - title of the subscribed feed",
        "- `$title` - title of the current entry",
        "- `$summary` - entry summary when it is meaningfully different from the title",
        "- `$summary_line` - the summary prefixed with ` - `, or an empty string",
        "- `$link` - normalized link to the current entry",
        "- `$feed_url` - subscribed RSS/Atom URL",
        "- `$feed_link` - website URL advertised by the feed",
        "- `$id` - entry identifier",
        "- `$date` - published/updated date provided by the feed",
        "",
        "Use `$$` when a literal dollar sign is needed.",
        "",
        "### Newlines and readable spacing",
        "",
        "The command is normally entered on one line. Write `\\n` in the command to store a real line break. Two trailing `\\n` sequences leave one blank separator line after an RSS post. More than two trailing line breaks are capped at two to avoid excessive gaps.",
        "",
        "A compact multiline template:",
        "",
        "```text",
        f"{PREFIX}rss template set 🌐 $feed_link\\n📰 $title\\n📝 $summary\\n🔗 $id – 📅 $date\\n\\n",
        "```",
        "",
        "The stored and rendered message is equivalent to:",
        "",
        "```text",
        "🌐 https://example.org/",
        "📰 Example entry",
        "📝 Short example summary",
        "🔗 https://example.org/article – 📅 2026-07-07 12:00",
        "",
        "```",
        "",
        "Do not add an accidental space after `\\n` unless the following line should be indented. For example, use `📝\\n$summary`, not `📝\\n $summary`.",
        "",
        "### Room-wide templates",
        "",
        "Inside a room or MUC PM, the room is inferred:",
        "",
        "```text",
        f"{PREFIX}rss template",
        f"{PREFIX}rss template set 📰 $feed_title: $title\\n📝 $summary\\n🔗 $link\\n\\n",
        f"{PREFIX}rss template test",
        f"{PREFIX}rss template unset",
        "```",
        "",
        "From a normal private chat, pass the room JID explicitly:",
        "",
        "```text",
        f"{PREFIX}rss template set room@conference.example.org 📰 $title\\n$link\\n\\n",
        "```",
        "",
        "### Feed-specific templates",
        "",
        "Inside a subscribed room, place the feed URL before the template:",
        "",
        "```text",
        f"{PREFIX}rss template set https://example.org/feed.xml 📰 $title\\n$link\\n\\n",
        f"{PREFIX}rss template show https://example.org/feed.xml",
        f"{PREFIX}rss template test https://example.org/feed.xml",
        f"{PREFIX}rss template unset https://example.org/feed.xml",
        "```",
        "",
        "From a normal private chat, pass both the room JID and feed URL:",
        "",
        "```text",
        f"{PREFIX}rss template set room@conference.example.org https://example.org/feed.xml 📰 $title\\n$link\\n\\n",
        "```",
        "",
    ]


def _translate_notes() -> list[str]:
    return [
        "## Translation forms and message contexts",
        "",
        "Translate text with an explicit source language, automatic source-language detection, or the short target-only form:",
        "",
        "```text",
        f"{PREFIX}tr en uk Hello, world!",
        f"{PREFIX}tr auto pl Guten Morgen",
        f"{PREFIX}tr de Hello, world!",
        "```",
        "",
        "Language arguments use supported ISO or BCP-47 codes such as `de`, `en`, `pl`, `uk`, `pt-BR` or `zh-CN`. `auto` is valid only as the source language.",
        "",
        "The command works in public rooms, MUC private messages and normal direct chats. Reply to an existing message and omit the text to translate the replied-to message:",
        "",
        "```text",
        f"{PREFIX}tr de",
        f"{PREFIX}tr en uk",
        "```",
        "",
        "Reply targets are resolved through the shared persistent message cache. Native XEP-0461 replies and client-provided visible fallback quotes are supported in all three message contexts.",
        "",
        "## Room setting",
        "",
        "Public-room and MUC-PM use is controlled per room. Inside the room or a MUC PM, use:",
        "",
        "```text",
        f"{PREFIX}translate status",
        f"{PREFIX}translate on",
        f"{PREFIX}translate off",
        f"{PREFIX}rooms enable translate",
        f"{PREFIX}rooms disable translate",
        "```",
        "",
        "From a normal direct chat, pass the target room JID to the `rooms` command:",
        "",
        "```text",
        f"{PREFIX}rooms enable room@conference.example.org translate",
        f"{PREFIX}rooms disable room@conference.example.org translate",
        "```",
        "",
        "Direct translation in a normal private chat does not depend on a room toggle.",
        "",
    ]


def _plugin_extra_notes(name: str) -> list[str]:
    if name == "reminder":
        return _reminder_notes()
    if name == "rss":
        return _rss_notes()
    if name == "translate":
        return _translate_notes()
    return []


def generate_plugin_doc(name: str, meta: dict, plugin_commands: list[object]) -> str:
    """Generate one detailed plugin documentation page."""
    title = str(meta.get("name") or name)
    lines = [
        f"# {title} plugin",
        "",
        "This file is generated from command metadata. Do not edit command sections by hand.",
        "",
        "```bash",
        "python scripts/generate_commands_md.py",
        "```",
        "",
        f"Source: `{meta.get('source', 'plugins')}`",
        f"Category: `{meta['category']}`",
        "",
        str(meta["description"]),
        "",
    ]
    lines.extend(_plugin_extra_notes(name))
    lines += ["## Commands", ""]

    for cmd in sorted(plugin_commands, key=lambda item: item.name):
        data = _metadata(cmd)
        aliases = sorted(set(a for a in (cmd.aliases or []) if a != cmd.name))
        lines += [
            f"### `{PREFIX}{cmd.name}`",
            "",
            data["short"],
            "",
            f"Role: `{data['role']}`<br>",
            f"Context: `{data['context']}`<br>",
            f"Category: `{data['category']}`<br>",
            f"Usage: `{data['usage']}`",
            "",
        ]
        if aliases:
            lines += ["Aliases: " + ", ".join(f"`{PREFIX}{alias}`" for alias in aliases), ""]
        if data["examples"]:
            lines.append("Examples:")
            lines.append("")
            for example in data["examples"]:
                lines.append(f"- `{_inline_code(example)}`")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_plugin_index(plugins: list[tuple[str, dict, list[object]]]) -> str:
    """Generate docs/plugins/README.md."""
    lines = [
        "# Plugin documentation",
        "",
        "This file is generated from command metadata. Do not edit it by hand.",
        "",
        "```bash",
        "python scripts/generate_commands_md.py",
        "```",
        "",
        "`docs/commands.md` is the compact command overview. These plugin pages contain the detailed command usage, aliases and examples for each plugin.",
        "",
        "| Plugin | Source | Category | Description |",
        "| --- | --- | --- | --- |",
    ]
    for name, meta, _plugin_commands in plugins:
        filename = _plugin_doc_filename(name)
        lines.append(
            f"| [`{name}`]({filename}) | `{_table_cell(meta.get('source', 'plugins'))}` | `{_table_cell(meta['category'])}` | {_table_cell(meta['description'])} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def generate_plugin_docs() -> dict[str, str]:
    """Generate all plugin docs under docs/plugins/.

    Returned keys are filenames relative to docs/plugins/.
    """
    plugins, _commands = _collect()
    docs = {"README.md": generate_plugin_index(plugins)}
    for name, meta, plugin_commands in plugins:
        docs[_plugin_doc_filename(name)] = generate_plugin_doc(name, meta, plugin_commands)
    return docs


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
        f"- `{PREFIX}help {PREFIX}<command>`",
        "",
        "For paginated commands, `all` disables paging and `last` jumps to the final page.",
        "",
        "## Context notes",
        "",
        "- `private chat / MUC PM` means a normal 1:1 chat with the bot or a MUC private message through a room occupant JID.",
        "- Room-scoped feature commands can infer the target room from a room message or MUC PM.",
        "- When using a normal private chat, pass `<room_jid>` explicitly for room-scoped feature commands.",
        "- EnvsBot has no separate fixed `ADMIN_ROOM` setting; global bot privileges come from `OWNER`, `ADMINS` and stored bot roles.",
        "",
        *_room_feature_section(),
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
        "| Plugin | Source | Category | Description | Detailed docs |",
        "| --- | --- | --- | --- | --- |",
    ]

    for name, meta, _plugin_commands in plugins:
        lines.append(
            f"| `{name}` | `{_table_cell(meta['source'])}` | `{_table_cell(meta['category'])}` | {_table_cell(meta['description'])} | [`docs/plugins/{_plugin_doc_filename(name)}`]({_plugin_doc_relpath(name)}) |"
        )

    by_category: dict[str, list[tuple[str, object, dict]]] = {}
    for _plugin_name, _meta, cmd, data in commands:
        by_category.setdefault(data["category"], []).append((_plugin_name, cmd, data))

    lines += ["", "## Commands by category", ""]
    for category in sorted(by_category):
        items = sorted(by_category[category], key=lambda item: item[1].name)
        lines += [f"### {_category_title(category)}", "", "| Command | Plugin | Role | Context | Description |", "| --- | --- | --- | --- | --- |"]
        for plugin_name, cmd, data in items:
            lines.append(
                f"| `{PREFIX}{cmd.name}` | [`{plugin_name}`]({_plugin_doc_relpath(plugin_name)}) | `{data['role']}` | `{_table_cell(data['context'])}` | {_table_cell(data['short'])} |"
            )
        lines.append("")

    lines += [
        "## Detailed plugin docs",
        "",
        "This generated file is intentionally an overview. Detailed usage, aliases and examples are generated into dedicated plugin documents:",
        "",
        "- [`docs/plugins/`](plugins/) - plugin command guides",
        "",
    ]

    return "\n".join(lines).rstrip() + "\n"


def write_generated_docs() -> list[Path]:
    """Write docs/commands.md and docs/plugins/*.md."""
    written: list[Path] = []
    commands_path = ROOT / "docs" / "commands.md"
    commands_path.write_text(generate(), encoding="utf-8")
    written.append(commands_path)

    PLUGIN_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, text in generate_plugin_docs().items():
        path = PLUGIN_DOCS_DIR / filename
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in write_generated_docs():
        print(f"wrote {path.relative_to(ROOT)}")
