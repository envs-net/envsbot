"""Runtime configuration inspection and validation commands."""

from __future__ import annotations

import ast
import os
import pprint
from collections.abc import Iterable, Sequence
from contextlib import suppress

from utils.command import Role, command
from utils.config import (
    ConfigError,
    NORMALIZED_CONFIG_KEYS,
    PYTHON_CONFIG_KEY_MAP,
    _LOWER_TO_PYTHON_CONFIG_KEY,
    STARTUP_ONLY_KEYS,
    apply_runtime_config,
    config,
    config_change_lines,
    get_config_display_sections,
    get_config_diff_sections,
    get_runtime_config_path,
    load_config,
    load_default_config_for_diff,
    restart_reloadable_plugin_tasks,
    startup_change_lines,
    validate_config,
)
from utils.formatting import format_page, paginate_lines, parse_page_args
from utils.audit import audit_event
from utils.backups import create_backup
from utils.room_features import clear_room_feature_caches
from utils.redaction import is_secret_key as _central_is_secret_key, redact_named as _central_redact_named, redact_value as _central_redact

PLUGIN_META = {
    "name": "config_cmd",
    "version": "0.1.0",
    "description": "Safe config inspection, validation and reload commands.",
    "category": "core",
}

_CONFIG_EDIT_BACKUP_REASON = "before-config-edit"
_CONFIG_EDIT_SECTION = "# Runtime config edits"
_PROTECTED_CONFIG_KEYS = {
    "owner",
    "admins",
    "stop_cmd",
}


def _display_key_to_normalized(key: str) -> str | None:
    """Return the normalized internal config key for an operator-facing name."""
    candidate = str(key or "").strip()
    if not candidate:
        return None
    if candidate in PYTHON_CONFIG_KEY_MAP:
        return PYTHON_CONFIG_KEY_MAP[candidate]
    upper_candidate = candidate.upper()
    if upper_candidate in PYTHON_CONFIG_KEY_MAP:
        return PYTHON_CONFIG_KEY_MAP[upper_candidate]
    lower_candidate = candidate.lower()
    if lower_candidate in NORMALIZED_CONFIG_KEYS:
        return lower_candidate
    return None


def _normalized_to_display_key(key: str) -> str:
    """Return the config.py-style display key for an internal config key."""
    return _LOWER_TO_PYTHON_CONFIG_KEY.get(key, str(key).upper())


def _is_runtime_writable_config_key(normalized_key: str) -> bool:
    """Return True when a key may be safely changed via chat command."""
    return (
        normalized_key in NORMALIZED_CONFIG_KEYS
        and normalized_key not in STARTUP_ONLY_KEYS
        and normalized_key not in _PROTECTED_CONFIG_KEYS
        and not _is_secret_key(normalized_key)
    )


def _format_config_display_value(name: str, value: object) -> str:
    """Render one config value for admin-facing output."""
    redacted = _redact_named(name, value)
    if isinstance(redacted, (list, tuple)) and len(redacted) > 6:
        preview = ", ".join(repr(item) for item in redacted[:4])
        return f"[{preview}, ...] ({len(redacted)} items)"
    return _render_value(redacted)


def _config_line_marker(name: str) -> str:
    normalized = _display_key_to_normalized(name) or str(name).lower()
    return "✏️" if _is_runtime_writable_config_key(normalized) else "🔒"


def _format_config_search_line(name: str, value: object) -> str:
    return f"{_config_line_marker(name)} {name} = {_format_config_display_value(name, value)}"


def _parse_config_value(raw: str) -> object:
    """Parse a chat-provided config literal with convenient bool/None handling."""
    text = str(raw).strip()
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "none":
        return None
    try:
        return ast.literal_eval(text)
    except Exception:
        return text


def _format_config_assignment(display_key: str, value: object) -> str:
    rendered = pprint.pformat(value, width=88, sort_dicts=False)
    return f"{display_key} = {rendered}"


def _config_assignment_ranges(source: str) -> dict[str, tuple[int, int, str]]:
    """Return top-level uppercase assignment line ranges in a Python config file."""
    tree = ast.parse(source)
    ranges: dict[str, tuple[int, int, str]] = {}
    lines = source.splitlines()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        for target in targets:
            if not target.isupper():
                continue
            start = max(0, int(getattr(node, "lineno", 1)) - 1)
            end = int(getattr(node, "end_lineno", start + 1))
            line = lines[start] if start < len(lines) else ""
            indent = line[: len(line) - len(line.lstrip())]
            ranges[target] = (start, end, indent)
    return ranges


def _replace_config_assignment(source: str, display_key: str, value: object) -> str:
    """Replace or append a top-level assignment in config.py."""
    lines = source.splitlines()
    had_trailing_newline = source.endswith("\n")
    ranges = _config_assignment_ranges(source)
    start_end_indent = ranges.get(display_key)
    assignment_lines = _format_config_assignment(display_key, value).splitlines()
    if start_end_indent is not None:
        start, end, indent = start_end_indent
        replacement = [indent + assignment_lines[0]]
        replacement.extend(indent + line for line in assignment_lines[1:])
        lines[start:end] = replacement
    else:
        while lines and lines[-1].strip() == "":
            lines.pop()
        if lines:
            lines.append("")
        lines.append(_CONFIG_EDIT_SECTION)
        lines.extend(assignment_lines)
    result = "\n".join(lines)
    return result + "\n" if had_trailing_newline or not result.endswith("\n") else result


def _write_config_text_atomic(path, text: str) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    # Directory fsync is best-effort: some platforms/filesystems do not
    # support opening directories, but the atomic replace above is complete.
    with suppress(OSError):
        dir_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _update_config_file_assignment(display_key: str, value: object) -> None:
    path = get_runtime_config_path()
    if path.suffix.lower() == ".json":
        raise ConfigError("config set/unset only supports config.py, not legacy config.json")
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    source = path.read_text(encoding="utf-8")
    updated = _replace_config_assignment(source, display_key, value)
    # Ensure we never persist syntactically invalid Python.
    ast.parse(updated, filename=str(path))
    _write_config_text_atomic(path, updated)


def _write_config_text_with_rollback(path, new_text: str, *, rollback_text: str | None = None) -> None:
    """Atomically write config text and restore the previous text on failure."""
    if rollback_text is None and path.exists():
        rollback_text = path.read_text(encoding="utf-8")
    try:
        _write_config_text_atomic(path, new_text)
    except Exception:
        if rollback_text is not None:
            with suppress(Exception):
                _write_config_text_atomic(path, rollback_text)
        raise


def _candidate_config_text(display_key: str, value: object) -> tuple[object, str, str]:
    """Return path, original text and validated candidate config text."""
    path = get_runtime_config_path()
    if path.suffix.lower() == ".json":
        raise ConfigError("config set/unset only supports config.py, not legacy config.json")
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    source = path.read_text(encoding="utf-8")
    updated = _replace_config_assignment(source, display_key, value)
    ast.parse(updated, filename=str(path))
    return path, source, updated


async def _maybe_create_config_backup(bot) -> str | None:
    """Create a safety backup before mutating config.py when possible."""
    try:
        backup = await create_backup(bot, reason=_CONFIG_EDIT_BACKUP_REASON)
    except Exception:
        return None
    return getattr(backup, "name", str(backup))


async def _apply_config_reload(bot, sender: str, before: dict, new_config: dict) -> str:
    """Apply a freshly loaded config atomically and return reply text."""
    startup_changes = startup_change_lines(before, new_config)
    effective_config = dict(new_config)
    for key in STARTUP_ONLY_KEYS:
        if before.get(key) != new_config.get(key):
            if key in before:
                effective_config[key] = before[key]
            else:
                effective_config.pop(key, None)

    old_config = dict(config)
    try:
        config.clear()
        config.update(effective_config)
        clear_room_feature_caches()

        runtime_notes = apply_runtime_config(bot, before, config)
        restarted = await restart_reloadable_plugin_tasks(bot, before, config)
        changed_lines = config_change_lines(before, config)
    except Exception:
        config.clear()
        config.update(old_config)
        clear_room_feature_caches()
        with suppress(Exception):
            apply_runtime_config(bot, effective_config, config)
        raise

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
    return "\n".join(notes)


def _is_secret_key(key: str) -> bool:
    return _central_is_secret_key(key)


def _redact(value):
    return _central_redact(value)


def _redact_named(name: str, value):
    return _central_redact_named(name, value)


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



@command("config search", role=Role.ADMIN, aliases=["config find"])
async def config_search(bot, sender, nick, args, msg, is_room):
    """Search visible config keys and values by substring."""
    query = " ".join(str(arg).strip() for arg in args).strip()
    if not query:
        bot.reply_usage(msg, f"{bot.prefix}config search/find <query>")
        return

    query_lower = query.lower()
    matches: list[str] = []
    for _section_title, entries in get_config_display_sections(config):
        for name, value in entries:
            display_value = _format_config_display_value(name, value)
            if query_lower in name.lower() or query_lower in display_value.lower():
                matches.append(_format_config_search_line(name, value))

    if not matches:
        bot.reply(msg, f"🔎 Config search for {query!r}: no matches.")
        return

    shown = matches[:50]
    lines = [f"🔎 Config search for {query!r}: {len(matches)} match(es)", "", *shown]
    if len(matches) > len(shown):
        lines.append("")
        lines.append(f"Output truncated to {len(shown)} matches.")
    bot.reply(msg, "\n".join(lines))


@command("config set", role=Role.ADMIN)
async def config_set(bot, sender, nick, args, msg, is_room):
    """Persist and apply one runtime-writable config value."""
    if len(args) < 2:
        bot.reply_usage(
            msg,
            f"{bot.prefix}config set <KEY> <value>\n"
            f"Example: {bot.prefix}config set LOG_LEVEL DEBUG",
        )
        return

    raw_key = str(args[0]).strip()
    normalized_key = _display_key_to_normalized(raw_key)
    if normalized_key is None:
        bot.reply_error(msg, f"Unknown config option: {raw_key}")
        return
    display_key = _normalized_to_display_key(normalized_key)
    if not _is_runtime_writable_config_key(normalized_key):
        bot.reply_error(msg, f"{display_key} is not a runtime-writable config option.")
        return

    raw_value = " ".join(str(arg) for arg in args[1:])
    new_value = _parse_config_value(raw_value)
    before = dict(config)
    candidate = dict(before)
    candidate[normalized_key] = new_value
    try:
        validate_config(candidate, require_required_keys=True)
    except ConfigError as exc:
        bot.reply_error(msg, f"Invalid value; config.py was not changed.\n{exc}")
        return

    old_value = before.get(normalized_key)
    backup_name = await _maybe_create_config_backup(bot)
    try:
        path, original_source, updated_source = _candidate_config_text(display_key, new_value)
        _write_config_text_with_rollback(path, updated_source, rollback_text=original_source)
        try:
            reloaded = load_config(require_required_keys=True)
            reply = await _apply_config_reload(bot, sender, before, reloaded)
        except Exception:
            _write_config_text_with_rollback(path, original_source, rollback_text=updated_source)
            raise
    except Exception as exc:
        bot.reply_error(msg, f"Failed to write/apply config: {exc}")
        return

    await audit_event(
        bot,
        "config_changed",
        actor=sender,
        target=display_key,
        details={"action": "set", "key": display_key},
    )
    prefix = f"{display_key} updated: {_format_config_display_value(display_key, old_value)} → {_format_config_display_value(display_key, new_value)}"
    if backup_name:
        prefix += f"\nBackup: {backup_name}"
    bot.reply_ok(msg, prefix + "\n\n" + reply)


@command("config unset", role=Role.ADMIN)
async def config_unset(bot, sender, nick, args, msg, is_room):
    """Reset one runtime-writable config value to config_sample.py default."""
    if len(args) != 1:
        bot.reply_usage(msg, f"{bot.prefix}config unset <KEY>")
        return

    raw_key = str(args[0]).strip()
    normalized_key = _display_key_to_normalized(raw_key)
    if normalized_key is None:
        bot.reply_error(msg, f"Unknown config option: {raw_key}")
        return
    display_key = _normalized_to_display_key(normalized_key)
    if not _is_runtime_writable_config_key(normalized_key):
        bot.reply_error(msg, f"{display_key} is not a runtime-writable config option.")
        return

    defaults = load_default_config_for_diff()
    if normalized_key not in defaults:
        bot.reply_error(msg, f"No default value found for {display_key} in config_sample.py.")
        return

    default_value = defaults[normalized_key]
    before = dict(config)
    candidate = dict(before)
    candidate[normalized_key] = default_value
    try:
        validate_config(candidate, require_required_keys=True)
    except ConfigError as exc:
        bot.reply_error(msg, f"Default value is invalid; config.py was not changed.\n{exc}")
        return

    old_value = before.get(normalized_key)
    backup_name = await _maybe_create_config_backup(bot)
    try:
        path, original_source, updated_source = _candidate_config_text(display_key, default_value)
        _write_config_text_with_rollback(path, updated_source, rollback_text=original_source)
        try:
            reloaded = load_config(require_required_keys=True)
            reply = await _apply_config_reload(bot, sender, before, reloaded)
        except Exception:
            _write_config_text_with_rollback(path, original_source, rollback_text=updated_source)
            raise
    except Exception as exc:
        bot.reply_error(msg, f"Failed to write/apply config: {exc}")
        return

    await audit_event(
        bot,
        "config_changed",
        actor=sender,
        target=display_key,
        details={"action": "unset", "key": display_key},
    )
    prefix = f"{display_key} reset to default: {_format_config_display_value(display_key, old_value)} → {_format_config_display_value(display_key, default_value)}"
    if backup_name:
        prefix += f"\nBackup: {backup_name}"
    bot.reply_ok(msg, prefix + "\n\n" + reply)


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

    reply = await _apply_config_reload(bot, sender, before, new_config)
    bot.reply_ok(msg, reply)
