"""Optional OMEMO adapter built on the shared envs-xmpp core."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from envs_xmpp_core.xmpp.omemo import (
    OMEMO_AVAILABLE,
    XEP_0384_module,
    XEP_0384Impl,
    collect_storage_device_hints,
    current_identity,
    decrypt_incoming_message,
    encrypt_and_send,
    ensure_identity_metadata,
    extract_unusable_recipients,
    format_device_ids,
    identity_metadata_path,
    message_has_omemo_payload,
    normalize_bare_jid,
    prepare_storage_file,
    read_identity_metadata,
    recipient_bare_jids,
    rotate_storage_identity,
    wait_for_omemo_ready,
)
from slixmpp import JID

from bot.room_state import JOINED_ROOMS
from utils.runtime_paths import omemo_storage_file

log = logging.getLogger(__name__)


class _OmemoHost(Protocol):
    config: Mapping[str, Any]
    plugin: Mapping[str, Any]
    boundjid: Any

    def register_plugin(
        self,
        plugin: str,
        pconfig: Mapping[str, Any] | None = None,
        module: Any = None,
    ) -> Any: ...

    def add_event_handler(
        self,
        name: str,
        pointer: Callable[..., Any],
        disposable: bool = False,
    ) -> Any: ...


# Compatibility aliases kept for the existing EnvsBot OMEMO tests/API.
def _resolve_storage_path(config: Mapping[str, Any]) -> Path:
    return omemo_storage_file(config).resolve()


def _identity_metadata_path(storage_path: Path) -> Path:
    return identity_metadata_path(storage_path)


def _current_identity(config: Mapping[str, Any]) -> dict[str, str]:
    return current_identity(config)


def _read_identity_metadata(path: Path) -> dict[str, str] | None:
    return read_identity_metadata(path)


def _ensure_identity_metadata(
    storage_path: Path,
    identity: dict[str, str],
    *,
    reset_on_change: bool,
) -> Path | None:
    backup, changed = ensure_identity_metadata(
        storage_path,
        identity,
        reset_on_change=reset_on_change,
    )
    if changed:
        log.info("[OMEMO] Identity metadata checked for %s", storage_path)
    return backup


def _prepare_storage_file(path: Path) -> Path:
    return prepare_storage_file(path)


class OmemoMixin:
    """EnvsBot policy adapter over the shared OMEMO mechanism."""

    def _omemo_host(self) -> _OmemoHost:
        return cast(_OmemoHost, self)

    def _configure_omemo_dependency_logging(self) -> None:
        if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
            return
        for logger_name in ("omemo", "omemo.core", "slixmpp_omemo", "slixmpp_omemo.xep_0384"):
            logging.getLogger(logger_name).setLevel(logging.ERROR)

    def configure_omemo(self) -> None:
        host = self._omemo_host()
        config = host.config
        self.omemo_enabled = bool(config.get("omemo_enabled", False))
        self.omemo_plaintext_fallback = bool(config.get("omemo_plaintext_fallback", False))
        self.omemo_reset_on_identity_change = bool(config.get("omemo_reset_on_identity_change", True))
        self.omemo_reset_pending_restart = False
        self.omemo_ready_timeout = 15
        self.omemo_ready = asyncio.Event()
        storage_path = _resolve_storage_path(config)
        self.omemo_storage_file = str(storage_path)

        if not self.omemo_enabled:
            log.info("[OMEMO] Disabled")
            return
        self._configure_omemo_dependency_logging()
        if not OMEMO_AVAILABLE or XEP_0384Impl is None or XEP_0384_module is None:
            log.warning(
                "[OMEMO] Enabled but optional dependencies are missing; continuing with OMEMO disabled. "
                "Install the required system libraries plus envsbot[omemo] or requirements-omemo.txt."
            )
            self.omemo_enabled = False
            return

        identity = _current_identity(config)
        backup = _ensure_identity_metadata(
            storage_path,
            identity,
            reset_on_change=self.omemo_reset_on_identity_change,
        )
        if backup is not None:
            log.warning("[OMEMO] Previous storage moved to %s", backup)
        storage_path = _prepare_storage_file(storage_path)
        self.omemo_storage_file = str(storage_path)
        host.register_plugin(
            "xep_0384",
            {"json_file_path": self.omemo_storage_file},
            module=XEP_0384_module,
        )
        host.add_event_handler("omemo_initialized", self._on_omemo_initialized)
        log.info("[OMEMO] Enabled with storage %s", self.omemo_storage_file)

    async def _on_omemo_initialized(self, _event: object) -> None:
        log.info("[OMEMO] Initialized")
        self.omemo_ready.set()

    async def _wait_for_omemo_ready(self) -> bool:
        ready = await wait_for_omemo_ready(
            self.omemo_ready,
            enabled=bool(getattr(self, "omemo_enabled", False)),
            timeout=getattr(self, "omemo_ready_timeout", 15),
            reset_pending=bool(getattr(self, "omemo_reset_pending_restart", False)),
        )
        if not ready and getattr(self, "omemo_enabled", False):
            log.warning("[OMEMO] Initialization is not ready")
        return ready

    @staticmethod
    def _normalize_bare_jid(value: object) -> str | None:
        return normalize_bare_jid(value)

    def _bare_jid(self, value: object) -> str:
        bare = normalize_bare_jid(value)
        if not bare:
            raise ValueError("OMEMO recipient does not contain a valid bare JID")
        return bare

    @staticmethod
    def _message_has_omemo_payload(msg: Any) -> bool:
        return message_has_omemo_payload(msg)

    def _extract_unusable_omemo_recipients(self, exc: Exception) -> set[str]:
        return extract_unusable_recipients(exc)

    def _visible_room_jids(self, room_jid: str) -> set[object]:
        room = normalize_bare_jid(room_jid)
        if not room:
            return set()
        room_data = JOINED_ROOMS.get(room)
        if room_data is None:
            for cached_room, cached_data in JOINED_ROOMS.items():
                if str(cached_room).casefold() == room.casefold():
                    room_data = cached_data
                    break
        if not isinstance(room_data, dict):
            return set()
        values: set[object] = set()
        for info in (room_data.get("nicks", {}) or {}).values():
            if isinstance(info, dict) and info.get("jid"):
                values.add(info["jid"])
        return values

    async def _omemo_recipients_for_room(self, room_jid: str) -> set[JID]:
        own = getattr(getattr(self, "boundjid", None), "bare", None)
        bare_recipients = recipient_bare_jids(self._visible_room_jids(room_jid), own_jid=own)
        return {JID(jid) for jid in bare_recipients}

    def _omemo_recipient_for_chat(self, target: object) -> JID:
        jid = JID(str(target))
        room = str(jid.bare).strip()
        nick = str(jid.resource or "").strip()
        if nick and room:
            room_data = JOINED_ROOMS.get(room)
            if isinstance(room_data, dict):
                nicks = room_data.get("nicks", {}) or {}
                info = nicks.get(nick)
                if info is None:
                    info = next(
                        (value for key, value in nicks.items() if str(key).casefold() == nick.casefold()),
                        None,
                    )
                if isinstance(info, dict) and (real := normalize_bare_jid(info.get("jid"))):
                    return JID(real)
        return JID(jid.bare)

    async def _send_omemo_message_object(self, msg: Any) -> Any:
        if not await self._wait_for_omemo_ready():
            raise RuntimeError("OMEMO is not initialized")
        plugin = self._omemo_host().plugin.get("xep_0384")
        if plugin is None:
            raise RuntimeError("OMEMO plugin is not registered")
        mto = msg["to"]
        mtype = str(msg["type"] or "chat")
        recipients: set[JID] | JID
        if mtype == "groupchat":
            recipients = await self._omemo_recipients_for_room(str(mto))
        else:
            recipients = self._omemo_recipient_for_chat(mto)
        if isinstance(recipients, set) and not recipients:
            raise RuntimeError(f"No OMEMO recipients available for {mto}")
        return await encrypt_and_send(plugin, msg, recipients, mto=str(mto))

    async def _decrypt_incoming_omemo_message(self, msg: Any) -> tuple[Any | None, bool]:
        decrypted, encrypted, reason = await decrypt_incoming_message(
            msg,
            enabled=bool(getattr(self, "omemo_enabled", False)),
            plugin_map=self._omemo_host().plugin,
            ready_event=getattr(self, "omemo_ready", asyncio.Event()),
            timeout=getattr(self, "omemo_ready_timeout", 15),
            reset_pending=bool(getattr(self, "omemo_reset_pending_restart", False)),
        )
        if reason == "device-info-unavailable":
            log.info("[OMEMO] Sender device information unavailable; encrypted message ignored")
        elif reason:
            log.warning("[OMEMO] Encrypted message ignored: %s", reason)
        return decrypted, encrypted

    def omemo_status(self) -> dict[str, Any]:
        storage = Path(str(getattr(self, "omemo_storage_file", "")))
        metadata = identity_metadata_path(storage) if str(storage) else None
        try:
            stored_identity = read_identity_metadata(metadata) if metadata else None
        except Exception:
            stored_identity = None
        return {
            "enabled": bool(getattr(self, "omemo_enabled", False)),
            "available": OMEMO_AVAILABLE,
            "ready": bool(getattr(self, "omemo_ready", None) and self.omemo_ready.is_set()),
            "storage": str(storage) if str(storage) else "-",
            "plaintext_fallback": bool(getattr(self, "omemo_plaintext_fallback", False)),
            "reset_on_identity_change": bool(getattr(self, "omemo_reset_on_identity_change", True)),
            "reset_pending_restart": bool(getattr(self, "omemo_reset_pending_restart", False)),
            "identity": _current_identity(self._omemo_host().config),
            "stored_identity": stored_identity,
        }

    def omemo_device_hints(self) -> dict[str, set[str]]:
        return collect_storage_device_hints(Path(self.omemo_storage_file))

    @staticmethod
    def format_omemo_device_ids(ids: set[str]) -> str:
        return format_device_ids(ids)

    def reset_omemo_storage(self) -> tuple[Path | None, Path | None]:
        storage = Path(self.omemo_storage_file)
        identity = _current_identity(self._omemo_host().config)
        backups = rotate_storage_identity(storage, identity)
        self.omemo_ready.clear()
        self.omemo_enabled = False
        self.omemo_reset_pending_restart = True
        return backups


__all__ = [
    "OMEMO_AVAILABLE",
    "OmemoMixin",
    "XEP_0384Impl",
    "_current_identity",
    "_ensure_identity_metadata",
    "_identity_metadata_path",
    "_prepare_storage_file",
    "_resolve_storage_path",
]
