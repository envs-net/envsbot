"""Metadata and diagnostic views for the plugin manager."""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any

from utils.plugin_manager_diagnostics import call_doctor_hook
from utils.plugin_metadata import validate_plugin_lifecycle, validate_plugin_metadata


class PluginManagerInspectionMixin:
    """Metadata validation and operator-facing plugin diagnostics."""

    bot: Any
    plugins: dict[str, Any]
    meta: dict[str, dict[str, Any]]

    if TYPE_CHECKING:
        async def _import(self, module_path: str) -> Any: ...
        def _module_path(self, name: str) -> str: ...
        def is_core_plugin(self, name: str) -> bool: ...
        def discover(self) -> list[str]: ...
        async def plugin_state(
            self, name: str, room_jid: str | None = None
        ) -> dict[str, Any]: ...
    async def metadata_issues(self, name: str) -> builtins.list:
        """Return metadata validation issues for one plugin."""
        try:
            module = self.plugins.get(name) or await self._import(self._module_path(name))
            meta = getattr(module, "PLUGIN_META", {})
        except Exception as exc:
            from utils.plugin_metadata import PluginMetadataIssue
            return [PluginMetadataIssue(name, "error", f"cannot import metadata: {exc}")]
        return [
            *validate_plugin_metadata(name, meta, core=self.is_core_plugin(name)),
            *validate_plugin_lifecycle(name, meta, module),
        ]

    async def all_metadata_issues(self) -> builtins.list:
        """Return metadata validation issues for all discoverable plugins."""
        issues: builtins.list = []
        for name in self.discover():
            issues.extend(await self.metadata_issues(name))
        return issues

    async def plugin_doctor(self, name: str, room_jid: str | None = None) -> builtins.list[str]:
        """Return plugin-provided doctor lines for diagnostics."""
        module = self.plugins.get(name)
        if module is None:
            return [f"🔴 {name}: not loaded"]

        async def _state_getter(plugin_name: str, state_room: str | None):
            return await self.plugin_state(plugin_name, room_jid=state_room)

        return await call_doctor_hook(
            self.bot,
            name,
            getattr(module, "doctor", None),
            room_jid=room_jid,
            state_getter=_state_getter,
        )

    async def get_plugin_info(self, name):
        """
        Retrieve PLUGIN_META for a plugin.

        Args:
            name (str): Plugin name.

        Returns:
            dict | None: Plugin metadata or None if not found.
        """
        if name in self.meta:
            meta = dict(self.meta[name])
            meta["source"] = "core" if self.is_core_plugin(name) else "plugins"
            return meta

        try:
            module = await self._import(self._module_path(name))
            meta = dict(getattr(module, "PLUGIN_META", {}) or {})
            meta["source"] = "core" if self.is_core_plugin(name) else "plugins"
            return meta
        except Exception:
            return None

    async def list_detailed(self):
        """
        Get plugin status grouped by source.

        Returns:
            dict: {group: {"loaded": [...], "available": [...]}}
        """
        loaded = set(self.plugins.keys())
        available = set(self.discover()) - loaded

        result: dict[str, dict[str, builtins.list[str]]] = {
            "core": {"loaded": [], "available": []},
            "plugins": {"loaded": [], "available": []},
        }

        for name in loaded:
            group = "core" if self.is_core_plugin(name) else "plugins"
            result[group]["loaded"].append(name)

        for name in available:
            group = "core" if self.is_core_plugin(name) else "plugins"
            result[group]["available"].append(name)

        return result
