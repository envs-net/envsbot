"""Read-only command registry helpers used by docs/help/diagnostics."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from utils.command import COMMANDS, Role

PLUGIN_SOURCES = (("core_plugins", "core"), ("plugins", "plugins"))


@dataclass(frozen=True, slots=True)
class CommandRecord:
    """One stable command record derived from the command registry."""

    registered_name: str
    primary_name: str
    plugin: str
    source: str
    is_alias: bool
    role: Role
    handler: str
    short: str
    usage: str
    examples: tuple[str, ...]
    category: str
    context: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "registered_name": self.registered_name,
            "primary_name": self.primary_name,
            "plugin": self.plugin,
            "source": self.source,
            "is_alias": self.is_alias,
            "role": self.role,
            "handler": self.handler,
            "short": self.short,
            "usage": self.usage,
            "examples": list(self.examples),
            "category": self.category,
            "context": self.context,
        }


def discover_command_modules() -> list[tuple[str, ModuleType, str]]:
    """Import all plugin modules that may expose decorated commands."""
    modules: list[tuple[str, ModuleType, str]] = []
    seen: set[str] = set()
    for package_name, source in PLUGIN_SOURCES:
        package = importlib.import_module(package_name)
        for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda item: item.name):
            name = module_info.name
            if name in seen:
                continue
            seen.add(name)
            modules.append((name, importlib.import_module(f"{package_name}.{name}"), source))
    return modules


def plugin_metadata(module: ModuleType, name: str, source: str) -> dict[str, Any]:
    """Return normalized plugin metadata for docs and diagnostics."""
    meta = dict(getattr(module, "PLUGIN_META", {}) or {})
    meta.setdefault("name", name)
    meta.setdefault("category", "other")
    meta.setdefault("description", inspect.getdoc(module) or "No description available.")
    meta.setdefault("hidden", False)
    meta["source"] = source
    return meta


def decorated_commands_from_module(module: ModuleType) -> list[Any]:
    """Return primary decorated command objects from one module."""
    seen: set[int] = set()
    commands: list[Any] = []
    for _attr, obj in inspect.getmembers(module):
        if not callable(obj) or not hasattr(obj, "__commands__"):
            continue
        for registered_name, cmd in getattr(obj, "__commands__", []):
            if id(cmd) in seen or registered_name != getattr(cmd, "name", registered_name):
                continue
            seen.add(id(cmd))
            commands.append(cmd)
    return sorted(commands, key=lambda cmd: getattr(cmd, "name", ""))


def decorated_command_records() -> list[tuple[str, dict[str, Any], Any]]:
    """Return command records from decorators, loading plugin modules first."""
    result: list[tuple[str, dict[str, Any], Any]] = []
    for name, module, source in discover_command_modules():
        meta = plugin_metadata(module, name, source)
        if meta.get("hidden"):
            continue
        for cmd in decorated_commands_from_module(module):
            result.append((name, meta, cmd))
    return sorted(result, key=lambda item: (str(item[1].get("category", "")), item[2].name))


def command_records() -> list[dict[str, Any]]:
    """Return stable command metadata records from the live registry."""
    records: list[dict[str, Any]] = []
    for tokens, cmd in sorted(COMMANDS.items(), key=lambda item: item[0]):
        registered_name = " ".join(tokens)
        primary_name = getattr(cmd, "name", registered_name)
        plugin = ""
        for plugin_name, plugin_tokens in COMMANDS.by_plugin.items():
            if tokens in plugin_tokens:
                plugin = plugin_name
                break
        record = CommandRecord(
            registered_name=registered_name,
            primary_name=primary_name,
            plugin=plugin,
            source="core" if plugin.startswith("_") else "plugins",
            is_alias=registered_name != primary_name,
            role=getattr(cmd, "role", Role.NONE),
            handler=getattr(getattr(cmd, "handler", None), "__name__", "unknown"),
            short=getattr(cmd, "short", ""),
            usage=getattr(cmd, "usage", ""),
            examples=tuple(getattr(cmd, "examples", []) or ()),
            category=getattr(cmd, "category", "") or "other",
            context=getattr(cmd, "context", "any") or "any",
        )
        records.append(record.as_dict())
    return records


def primary_command_records() -> list[dict[str, Any]]:
    """Return only primary command records."""
    return [record for record in command_records() if not record["is_alias"]]
