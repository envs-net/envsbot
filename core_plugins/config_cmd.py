"""Runtime configuration inspection and validation commands."""

from __future__ import annotations

from collections.abc import Iterable

from utils.command import Role, command
from utils.config import (
    ConfigError,
    config,
    load_config,
    validate_config,
    get_config_display_sections,
    get_config_diff_sections,
)
from utils.formatting import format_page, parse_page_args
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


def _section_lines(title: str, items: Iterable[tuple[str, object]]) -> list[str]:
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


def _format_diff_lines(cfg: dict) -> list[str]:
    sections = get_config_diff_sections(cfg)
    if not sections:
        return ["No config differences from config_sample.py defaults."]

    lines = []
    for section_title, entries in sections:
        if lines:
            lines.append("")
        lines.append(f"{section_title}:")
        for name, current_value, default_value in entries:
            current_display = _render_value(_redact_named(name, current_value))
            default_display = _render_value(_redact_named(name, default_value))
            lines.append(
                f"• {name} = {current_display} "
                f"(default: {default_display})"
            )
    return lines


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
    page = parse_page_args(args)
    bot.reply(
        msg,
        format_page(
            "⚙️ Config differences",
            _format_diff_lines(config),
            page_request=page,
            page_size=24,
            command_hint=f"{bot.prefix}config diff",
        ),
    )


@command("config validate", role=Role.ADMIN)
async def config_validate(bot, sender, nick, args, msg, is_room):
    """Validate config.py."""
    try:
        validate_config(load_config(require_required_keys=True), require_required_keys=True)
    except ConfigError as exc:
        bot.reply_error(msg, f"Invalid config.py:\n{exc}")
        return
    bot.reply_ok(msg, "config.py is valid.")


@command("config reload", role=Role.ADMIN)
async def config_reload(bot, sender, nick, args, msg, is_room):
    """Reload config.py into the running process where possible."""
    try:
        new_config = load_config(require_required_keys=True)
    except ConfigError as exc:
        bot.reply_error(msg, f"Config reload failed:\n{exc}")
        return

    old_prefix = config.get("prefix", ",")
    config.clear()
    config.update(new_config)
    clear_room_feature_caches()

    bot.prefix = config.get("prefix", bot.prefix)
    bot.nick = config.get("nick", bot.nick)

    notes = ["config.py reloaded."]
    if bot.prefix != old_prefix:
        notes.append(f"Prefix changed from {old_prefix!r} to {bot.prefix!r}.")
    notes.append("Connection credentials and DB path require a bot restart to fully apply.")
    await audit_event(bot, "config_reloaded", actor=sender, target="config")
    bot.reply_ok(msg, "\n".join(notes))
