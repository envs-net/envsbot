"""Generate command docs from plugin command metadata."""

from __future__ import annotations

from pathlib import Path


def _checkout_root(path: Path) -> Path:
    """Return the real checkout when imported from mutmut's copy.

    mutmut copies production modules below ``<repo>/mutants`` but does not
    copy the generated Markdown documentation.  Documentation validation must
    therefore compare against the files in the original checkout.
    """
    if path.name == "mutants":
        checkout = path.parent
        if (checkout / "pyproject.toml").exists():
            return checkout
    return path


ROOT = _checkout_root(Path(__file__).resolve().parents[1])

from utils.command import Role, command_examples, command_subcommands
from utils.config import config
from utils.command_registry import (
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
    context = str(getattr(cmd, "context", "any") or "any")
    role = getattr(cmd, "role", Role.NONE)
    if context == "any":
        context = (
            "private chat / MUC PM"
            if role <= Role.MODERATOR
            else "room, MUC PM or private chat"
        )
    category = str(getattr(cmd, "category", "") or "other")
    examples = [
        {
            "command": example.command.replace("{prefix}", PREFIX),
            "description": example.description.replace("{prefix}", PREFIX),
        }
        for example in command_examples(cmd)
    ]
    subcommands = []
    for subcommand in command_subcommands(cmd):
        subcommands.append(
            {
                "name": subcommand.name,
                "usage": subcommand.usage.replace("{prefix}", PREFIX),
                "short": subcommand.short.replace("{prefix}", PREFIX),
                "aliases": list(subcommand.aliases),
                "examples": [
                    {
                        "command": example.command.replace("{prefix}", PREFIX),
                        "description": example.description.replace("{prefix}", PREFIX),
                    }
                    for example in subcommand.examples
                ],
                "role": subcommand.role,
                "context": subcommand.context,
            }
        )
    return {
        "short": short.replace("{prefix}", PREFIX),
        "usage": usage.replace("{prefix}", PREFIX),
        "examples": examples,
        "subcommands": subcommands,
        "context": context,
        "role": role,
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
        f"- `{PREFIX}rooms enable ducks` — Enable ducks in the current room or MUC PM.",
        f"- `{PREFIX}rooms disable ducks` — Disable ducks in the current room or MUC PM.",
        f"- `{PREFIX}rooms enable room@conference.example.org ducks` — Enable ducks for an explicit room from a normal private chat.",
        f"- `{PREFIX}rooms plugins room@conference.example.org all` — Show every room feature setting without pagination.",
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
        "RSS posts can use a global default, a destination-wide template or a feed-specific template. A destination may be a room or a direct subscriber. The priority is: feed-specific template, destination template, global default, built-in default.",
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
        "### Global default template",
        "",
        "Global moderators can set one persistent default for every room or direct subscriber that has no destination- or feed-specific override:",
        "",
        "```text",
        f"{PREFIX}rss template show default",
        f"{PREFIX}rss template set default 🌐 $feed_link\\n📰 $title\\n📝 $summary\\n🔗 $link\\n\\n",
        f"{PREFIX}rss template test default",
        f"{PREFIX}rss template unset default",
        "```",
        "",
        "`unset default` restores the built-in RSS template. The alias `global` can be used instead of `default`.",
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
        "### Personal direct-chat templates",
        "",
        "Trusted users and higher can set a persistent template for their own 1:1 RSS subscriptions. In a normal direct chat, omit the room JID. The bot recognizes the 1:1 destination automatically:",
        "",
        "```text",
        f"{PREFIX}rss template",
        f"{PREFIX}rss template set 📰 $feed_title: $title\\n$link\\n\\n",
        f"{PREFIX}rss template test",
        f"{PREFIX}rss template unset",
        "```",
        "",
        "This personal template is independent of room templates and applies only to feeds delivered directly to that user's bare JID. An optional `direct` marker is accepted for clarity, but is not required.",
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
        "From a normal private chat, pass both the room JID and feed URL to manage a room feed:",
        "",
        "```text",
        f"{PREFIX}rss template set room@conference.example.org https://example.org/feed.xml 📰 $title\\n$link\\n\\n",
        "```",
        "",
        "For a personal direct subscription, omit the room JID and place the subscribed feed URL before the template:",
        "",
        "```text",
        f"{PREFIX}rss template set https://example.org/feed.xml 📰 $title\\n$link\\n\\n",
        f"{PREFIX}rss template show https://example.org/feed.xml",
        f"{PREFIX}rss template test https://example.org/feed.xml",
        f"{PREFIX}rss template unset https://example.org/feed.xml",
        "```",
        "",
        "The equivalent explicit forms `template set direct ...` and `template set <feed-url> direct ...` are also accepted. The `direct` marker selects the personal scope and is never stored as part of the template.",
        "",
        "## Direct subscriptions",
        "",
        "Trusted users and higher may subscribe to feeds in a direct chat. Trusted users are limited by `RSS_TRUSTED_MAX_FEEDS` (default: 10); moderators and higher are unlimited.",
        "",
        f"Use `{PREFIX}rss template set ...` in the same direct chat to customize all personal deliveries, or include a subscribed feed URL for a feed-specific personal template.",
        "",
        "Trusted users may remove only their own subscriptions. Owner, superadmin, and admin users may remove a trusted user's subscription explicitly:",
        "",
        "```text",
        f"{PREFIX}rss remove <feed-url> <user-jid>",
        "```",
        "",
        f"In direct chat, global moderators see compact sections for room, moderator, and trusted-user feeds while retaining title, status, interval, destination, and URL.",
        f"Global moderators may select a single section with `{PREFIX}rss list rooms`, `{PREFIX}rss list mods`, or `{PREFIX}rss list trusted`. For trusted users, `{PREFIX}rss list` shows only their own direct subscriptions without empty room or moderator sections.",
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
        "## Configured language defaults",
        "",
        "The global Python configuration supports:",
        "",
        "```python",
        'TRANSLATE_FROM = "auto"',
        "TRANSLATE_TO = None",
        "```",
        "",
        "These values preserve the original behavior: the source is detected automatically and every command still requires a target language. Set `TRANSLATE_TO` to a supported language code to enable shorter commands:",
        "",
        "```python",
        'TRANSLATE_FROM = "auto"',
        'TRANSLATE_TO = "de"',
        "```",
        "",
        "With that example configuration, direct text and replies can be translated without language arguments:",
        "",
        "```text",
        f"{PREFIX}tr Hello, world!",
        f"Reply to a message with {PREFIX}tr",
        "```",
        "",
        "A target argument such as `,tr pl Text` overrides `TRANSLATE_TO`; an explicit pair such as `,tr en uk Text` overrides both defaults. The settings are applied by `,config reload` without restarting the bot.",
        "",
        f"Automatic detection can be ambiguous for very short text, especially single words written in the Latin alphabet. If the provider detects the target language and returns the input unchanged, the bot now explains the ambiguity and suggests an explicit source/target pair such as `{PREFIX}tr de en Blume`. Longer phrases usually give the provider enough context for reliable detection.",
        "",
        f"If a shorthand target equals the configured source, the bot automatically uses `auto` as the source instead of sending a no-op translation such as `en` to `en`. An explicitly supplied pair such as `{PREFIX}tr en en text` is still respected unchanged.",
        "",
        f"With `TRANSLATE_TO` configured, `{PREFIX}tr auto` translates the literal word `auto`. To explicitly select automatic source detection for a reply, include the target too, for example `{PREFIX}tr auto de`.",
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


def _example_description(data: dict, example: dict) -> str:
    """Return explicit or command-level fallback text for one example."""
    return str(example.get("description") or data.get("short") or "Example usage.")


def _append_examples(lines: list[str], data: dict, examples: list[dict]) -> None:
    """Append Markdown examples with one explanation per command."""
    if not examples:
        return
    lines += ["Examples:", ""]
    for example in examples:
        description = _example_description(data, example)
        lines.append(
            f"- `{_inline_code(example['command'])}` — {description}"
        )
    lines.append("")


def _append_subcommands(lines: list[str], cmd, data: dict) -> None:
    """Append structured subcommand documentation."""
    if not data["subcommands"]:
        return
    lines += ["#### Subcommands", ""]
    for subcommand in data["subcommands"]:
        lines.append(f"- `{_inline_code(subcommand['usage'])}`")
        lines.append(f"  - Description: {subcommand['short']}")
        aliases = subcommand["aliases"]
        if aliases:
            root = str(cmd.name)
            rendered = ", ".join(
                f"`{PREFIX}{root} {alias}`" for alias in aliases
            )
            lines.append(f"  - Aliases: {rendered}")
        effective_role = subcommand["role"] or data["role"]
        if effective_role != data["role"]:
            lines.append(f"  - Role: `{effective_role}`")
        effective_context = subcommand["context"] or data["context"]
        if effective_context != data["context"]:
            lines.append(f"  - Context: `{effective_context}`")
        examples = subcommand["examples"]
        if examples:
            lines.append("  - Examples:")
            for example in examples:
                description = _example_description(data, example)
                lines.append(
                    "    - "
                    f"`{_inline_code(example['command'])}` — {description}"
                )
        lines.append("")

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
        _append_subcommands(lines, cmd, data)
        if data["subcommands"]:
            structured_examples = [
                example
                for subcommand in data["subcommands"]
                for example in subcommand["examples"]
            ]
            if not structured_examples:
                _append_examples(lines, data, data["examples"])
        else:
            _append_examples(lines, data, data["examples"])
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
        "Calling a registered command family without a subcommand (for example `,rooms`, `,users` or `,bot`) opens the matching help overview automatically.",
        "Unknown command names still produce no automatic response.",
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

def validate_command_docs(
    docs_path: Path | None = None,
) -> tuple[list[str], int]:
    """Return generated-command-documentation errors and command count."""
    from utils.command_registry import decorated_command_records

    docs_path = docs_path or (ROOT / "docs" / "commands.md")
    errors: list[str] = []
    commands = decorated_command_records()
    if not commands:
        errors.append("no commands found")

    docs_text = ""
    if docs_path.exists():
        docs_text = docs_path.read_text(encoding="utf-8")
        if "This file is generated from command metadata" not in docs_text:
            errors.append("docs/commands.md is missing generated-file marker")
        elif docs_text != generate():
            errors.append(
                "docs/commands.md is out of date; run "
                "python scripts/generate_commands_md.py"
            )
    else:
        errors.append("docs/commands.md is missing")

    plugin_docs = generate_plugin_docs()
    for rel_name, generated_doc in plugin_docs.items():
        path = PLUGIN_DOCS_DIR / rel_name
        if not path.exists():
            errors.append(f"docs/plugins/{rel_name} is missing")
        elif path.read_text(encoding="utf-8") != generated_doc:
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
            if not str(getattr(cmd, field, "") or "").strip():
                errors.append(f"{plugin}:{name}: missing {field}")
        if not list(getattr(cmd, "examples", []) or []):
            errors.append(f"{plugin}:{name}: missing examples")
        for subcommand in command_subcommands(cmd):
            label = f"{plugin}:{name}:{subcommand.name}"
            if not subcommand.name.strip():
                errors.append(f"{label}: missing name")
            if not subcommand.usage.strip():
                errors.append(f"{label}: missing usage")
            if not subcommand.short.strip():
                errors.append(f"{label}: missing short")
            if not subcommand.examples:
                errors.append(f"{label}: missing examples")
            for example in subcommand.examples:
                if not example.command.strip():
                    errors.append(f"{label}: empty example command")
                if not example.description.strip():
                    errors.append(f"{label}: missing example description")
        if docs_text and f"`,{name}`" not in docs_text:
            errors.append(f"docs/commands.md: missing primary command {name!r}")
        plugin_doc_name = f"{plugin.replace('/', '_')}.md"
        plugin_doc = plugin_docs.get(plugin_doc_name, "")
        if plugin_doc and f"### `,{name}`" not in plugin_doc:
            errors.append(
                f"docs/plugins/{plugin_doc_name}: missing command {name!r}"
            )

    return errors, len(commands)
