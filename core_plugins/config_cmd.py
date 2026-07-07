"""Runtime configuration inspection and validation commands."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from utils.command import Role, command
from utils.config import (
    ConfigError,
    STARTUP_ONLY_KEYS,
    apply_runtime_config,
    config,
    config_change_lines,
    get_config_display_sections,
    get_config_diff_sections,
    load_config,
    restart_reloadable_plugin_tasks,
    startup_change_lines,
    validate_config,
)
from utils.formatting import format_page, paginate_lines, parse_page_args
from utils.audit import audit_event
from utils.room_features import clear_room_feature_caches

PLUGIN_META = {
    "name": "config_cmd",
    "version": "0.1.0",
    "description": "Safe config inspection, validation and reload commands.",
    "category": "core",
}

_SECRET_KEYS = {"password", "token", "secret", "api_key", "apikey", "key"}


def _is_secret_key(key: str) -> bool:
    key_lc = key.lower()
    return any(part in key_lc for part in _SECRET_KEYS)


def _redact(value):
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if _is_secret_key(k) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _redact_named(name: str, value):
    if _is_secret_key(name):
        return "<redacted>"
    return _redact(value)


def _render_value(value) -> str:
    return repr(value)


def _format_dict_lines(value: dict, *, indent: str = "  ") -> list[str]:
    lines = []
    for key in sorted(value):
        item = value[key]
        if isinstance(item, dict):
            lines.append(f"{indent}• {key}:")
            lines.extend(_format_dict_lines(item, indent=indent + "  "))
        else:
            lines.append(f"{indent}• {key} = {_render_value(item)}")
    return lines


def _section_lines(
    title: str,
    items: Iterable[tuple[str, object]],
) -> list[str]:
    section = [f"{title}:"]
    for name, value in items:
        if isinstance(value, dict):
            section.append(f"• {name}:")
            section.extend(_format_dict_lines(value))
        else:
            section.append(f"• {name} = {_render_value(value)}")
    return section


def _format_config_lines(cfg: dict) -> list[str]:
    safe = _redact(cfg)
    lines = []
    for section_title, entries in get_config_display_sections(safe):
        if lines:
            lines.append("")
        lines.extend(_section_lines(section_title, entries))
    return lines


def _config_diff_entries(cfg: dict) -> list[str]:
    sections = get_config_diff_sections(cfg)
    lines: list[str] = []

    for _section_title, entries in sections:
        for name, current_value, default_value in entries:
            if _is_secret_key(name):
                continue
            lines.extend([
                f"• {name}",
                f"  current: {_render_value(_redact_named(name, current_value))}",
                f"  default: {_render_value(_redact_named(name, default_value))}",
                "",
            ])

    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _config_diff_arg_requests_page(args: Sequence[str]) -> bool:
    return any(
        str(arg).lower().strip() == "last" or str(arg).isdigit()
        for arg in args
    )



def _format_diff_body(cfg: dict, args: Sequence[str], *, prefix: str = ",") -> str:
    entries = _config_diff_entries(cfg)
    diff_count = sum(1 for line in entries if line.startswith("• "))

    if not entries:
        return "🧩 Config Diff: no differences from config_sample.py defaults."

    page_request = parse_page_args(args)
    should_paginate = (not page_request.all) and _config_diff_arg_requests_page(args)
    if should_paginate:
        page_size = 24
        page = page_request.page
        page_lines, current_page, total_pages = paginate_lines(
            entries,
            page=page,
            page_size=page_size,
        )
        return "\n".join([
            f"🧩 Config Diff ({diff_count} change(s)) - Page {current_page}/{total_pages}:",
            "",
            *page_lines,
            "",
            f"Use {prefix}config diff all for the full output.",
        ])

    return "\n".join([
        f"🧩 Config Diff ({diff_count} change(s)):",
        "",
        *entries,
    ])


def _format_diff_lines(cfg: dict) -> list[str]:
    entries = _config_diff_entries(cfg)
    if not entries:
        return ["No config differences from config_sample.py defaults."]
    return entries


@command("config show", role=Role.ADMIN, aliases=["config"])
async def config_show(bot, sender, nick, args, msg, is_room):
    """Show the effective config with secrets redacted."""
    page = parse_page_args(args)
    bot.reply(
        msg,
        format_page(
            "⚙️ Effective config",
            _format_config_lines(config),
            page_request=page,
            page_size=24,
            command_hint=f"{bot.prefix}config show",
        ),
    )


@command("config diff", role=Role.ADMIN)
async def config_diff(bot, sender, nick, args, msg, is_room):
    """Show config values that differ from config_sample.py defaults."""
    bot.reply(
        msg,
        _format_diff_body(config, args, prefix=getattr(bot, "prefix", ",")),
    )


@command("config validate", role=Role.ADMIN)
async def config_validate(bot, sender, nick, args, msg, is_room):
    """Validate config.py."""
    try:
        validate_config(
            load_config(require_required_keys=True),
            require_required_keys=True,
        )
    except ConfigError as exc:
        bot.reply_error(msg, f"Invalid config.py:\n{exc}")
        return
    bot.reply_ok(msg, "config.py is valid.")


@command("config reload", role=Role.ADMIN)
async def config_reload(bot, sender, nick, args, msg, is_room):
    """Reload config.py into the running process where possible."""
    before = dict(config)
    try:
        new_config = load_config(require_required_keys=True)
    except ConfigError as exc:
        bot.reply_error(msg, f"Config reload failed:\n{exc}")
        return

    startup_changes = startup_change_lines(before, new_config)
    effective_config = dict(new_config)
    for key in STARTUP_ONLY_KEYS:
        if before.get(key) != new_config.get(key):
            if key in before:
                effective_config[key] = before[key]
            else:
                effective_config.pop(key, None)

    config.clear()
    config.update(effective_config)
    clear_room_feature_caches()

    runtime_notes = apply_runtime_config(bot, before, config)
    restarted = await restart_reloadable_plugin_tasks(bot, before, config)

    changed_lines = config_change_lines(before, config)

    notes = ["config.py reloaded."]
    if changed_lines:
        notes.append("\nChanged:")
        notes.extend(changed_lines)
    else:
        notes.append("\nNo config changes detected.")

    if runtime_notes:
        notes.append("\nApplied at runtime:")
        notes.extend(f"- {line}" for line in runtime_notes)

    if restarted:
        notes.append("\nRestarted plugin tasks:")
        notes.extend(f"- {line}" for line in restarted)

    if startup_changes:
        notes.append("\nStartup-only changes detected and NOT fully applied. Restart the bot to activate:")
        notes.extend(startup_changes)

    await audit_event(bot, "config_reloaded", actor=sender, target="config")
    bot.reply_ok(msg, "\n".join(notes))
