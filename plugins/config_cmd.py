"""Runtime configuration inspection and validation commands."""

from __future__ import annotations

import json

from utils.command import Role, command
from utils.config import ConfigError, config, load_config, validate_config
from utils.formatting import format_page, parse_page_args
from utils.audit import audit_event

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
        return {k: ("<redacted>" if _is_secret_key(k) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _format_config_lines(cfg: dict) -> list[str]:
    safe = _redact(cfg)
    lines = []
    for key in sorted(safe):
        value = safe[key]
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        lines.append(f"• {key} = {rendered}")
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
            page_size=14,
            command_hint=f"{bot.prefix}config show",
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

    bot.prefix = config.get("prefix", bot.prefix)
    bot.nick = config.get("nick", bot.nick)

    notes = ["config.py reloaded."]
    if bot.prefix != old_prefix:
        notes.append(f"Prefix changed from {old_prefix!r} to {bot.prefix!r}.")
    notes.append("Connection credentials and DB path require a bot restart to fully apply.")
    await audit_event(bot, "config_reloaded", actor=sender, target="config")
    bot.reply_ok(msg, "\n".join(notes))
