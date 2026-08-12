"""Pure parsing/normalization helpers for deployment systemd checks."""

from __future__ import annotations

import re
import shlex
from pathlib import Path


def _unit_service_values(rendered: str) -> dict[str, list[str]]:
    """Return assignments from the rendered [Service] section."""
    values: dict[str, list[str]] = {}
    section = ""
    for raw_line in rendered.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "Service" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key, []).append(value)
    return values

def _environment_assignment(value: str, name: str) -> str | None:
    try:
        fields = shlex.split(value)
    except ValueError:
        fields = value.split()
    prefix = f"{name}="
    for field in fields:
        if field.startswith(prefix):
            return field[len(prefix):]
    return None

def _exec_start_executable(value: str) -> str:
    if "path=" in value:
        return value.split("path=", 1)[1].split(";", 1)[0].strip()
    try:
        fields = shlex.split(value)
    except ValueError:
        fields = value.split()
    return fields[0] if fields else ""

def _bool_value(value: str) -> bool | None:
    normalized = value.strip().casefold()
    if normalized in {"1", "yes", "true", "on"}:
        return True
    if normalized in {"0", "no", "false", "off"}:
        return False
    return None

def _duration_seconds(value: str) -> float | None:
    """Parse the compact duration forms used by systemctl show."""
    normalized = value.strip().casefold().replace(" ", "")
    if not normalized or normalized in {"infinity", "infinite"}:
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(usec|us|ms|msec|s|sec|min|h|hr)?", normalized)
    if match is None:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or "s"
    factor = {
        "usec": 0.000001,
        "us": 0.000001,
        "ms": 0.001,
        "msec": 0.001,
        "s": 1.0,
        "sec": 1.0,
        "min": 60.0,
        "h": 3600.0,
        "hr": 3600.0,
    }[unit]
    return amount * factor

def _path_set(value: str) -> set[str]:
    try:
        fields = shlex.split(value)
    except ValueError:
        fields = value.split()
    result: set[str] = set()
    for field in fields:
        item = field.strip()
        if not item:
            continue
        prefix = ""
        while item.startswith(("-", "+", "!")):
            prefix += item[0]
            item = item[1:]
        if item:
            result.add(prefix + str(Path(item).expanduser().resolve()))
    return result

def _umask_value(value: str) -> int | None:
    text = value.strip()
    try:
        return int(text, 8) if text else None
    except ValueError:
        return None

def _resolved_path_text(value: str) -> str:
    text = value.strip()
    return str(Path(text).expanduser().resolve()) if text else ""

def _display_systemd_value(name: str, value: object) -> str:
    if name in {"Restart delay", "Watchdog", "Stop timeout"}:
        return f"{value:g}s" if isinstance(value, (int, float)) else str(value)
    if name == "UMask" and isinstance(value, int):
        return f"{value:04o}"
    if name == "ReadWritePaths" and isinstance(value, set):
        return " ".join(sorted(value)) or "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "-"
    return str(value)
