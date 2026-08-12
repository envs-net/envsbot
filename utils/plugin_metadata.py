"""Plugin metadata validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

REQUIRED_PLUGIN_META_KEYS = ("name", "description", "category")
KNOWN_PLUGIN_META_KEYS = frozenset({
    "name",
    "version",
    "description",
    "category",
    "requires",
    "hidden",
    "room_state",
})


@dataclass(frozen=True)
class PluginMetadataIssue:
    """One plugin metadata validation issue."""

    plugin: str
    severity: str
    message: str

    def format(self) -> str:
        return f"{self.severity.upper()} {self.plugin}: {self.message}"


def validate_plugin_metadata(plugin: str, meta: Any, *, core: bool = False) -> list[PluginMetadataIssue]:
    """Validate one PLUGIN_META mapping and return issues."""
    issues: list[PluginMetadataIssue] = []
    if not isinstance(meta, dict):
        return [PluginMetadataIssue(plugin, "error", "PLUGIN_META must be a dict")]

    for key in REQUIRED_PLUGIN_META_KEYS:
        value = meta.get(key)
        if not isinstance(value, str) or not value.strip():
            issues.append(PluginMetadataIssue(plugin, "error", f"missing non-empty {key!r}"))

    name = str(meta.get("name", "") or "").strip()
    if name and name != plugin:
        issues.append(PluginMetadataIssue(plugin, "warning", f"name is {name!r}, expected {plugin!r}"))

    requires = meta.get("requires", [])
    if requires is None:
        requires = []
    if not isinstance(requires, list) or not all(isinstance(item, str) and item.strip() for item in requires):
        issues.append(PluginMetadataIssue(plugin, "error", "requires must be a list of plugin names"))

    room_state = meta.get("room_state")
    if room_state is not None and room_state not in {"custom", "shared", "none"}:
        issues.append(
            PluginMetadataIssue(
                plugin,
                "error",
                "room_state must be one of: custom, shared, none",
            )
        )

    unknown = sorted(set(meta) - KNOWN_PLUGIN_META_KEYS)
    if unknown:
        issues.append(PluginMetadataIssue(plugin, "warning", f"unknown metadata keys: {', '.join(unknown)}"))

    return issues


def validate_plugin_lifecycle(plugin: str, meta: Any, module: Any) -> list[PluginMetadataIssue]:
    """Validate lifecycle hooks implied by declarative plugin metadata."""
    if not isinstance(meta, dict) or meta.get("room_state") != "custom":
        return []
    cleanup = getattr(module, "cleanup_room_state", None)
    legacy = getattr(module, "on_room_delete", None)
    if callable(cleanup) or callable(legacy):
        return []
    return [
        PluginMetadataIssue(
            plugin,
            "error",
            "room_state='custom' requires cleanup_room_state(bot, room_jid)",
        )
    ]
