"""Optional OMEMO transport support for EnvsBot.

The feature is deliberately transport-oriented: incoming OMEMO messages are
first decrypted and ordinary bot/plugin code then sees the normal plaintext
stanza. Replies produced while processing that stanza inherit the incoming
encryption mode. Plaintext input therefore stays plaintext, while an encrypted
message gets an encrypted reply whenever OMEMO is available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from slixmpp import JID

from bot.room_state import JOINED_ROOMS
from utils.file_security import PRIVATE_FILE_MODE, ensure_private_directory
from utils.runtime_paths import omemo_identity_file, omemo_storage_file

log = logging.getLogger(__name__)

try:  # Optional dependency; only required when OMEMO_ENABLED=True.
    import slixmpp_omemo as XEP_0384_module
    from omemo.storage import Just, Maybe, Nothing, Storage
    from omemo.types import DeviceInformation, JSONType
    from slixmpp.plugins import register_plugin

    XEP_0384: Any = XEP_0384_module.XEP_0384
    OMEMO_AVAILABLE = True
except Exception:  # pragma: no cover - depends on optional runtime dependency
    Just = Maybe = Nothing = Storage = None
    DeviceInformation = JSONType = Any
    XEP_0384 = None
    XEP_0384_module = None
    OMEMO_AVAILABLE = False

XEP_0384Impl: Any = None


class _OmemoHost(Protocol):
    """Minimal host surface OmemoMixin expects from the concrete XMPP client."""

    config: Mapping[str, Any]
    plugin: Mapping[str, Any]

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


def _resolve_storage_path(config: Mapping[str, Any]) -> Path:
    """Return the configured OMEMO store or the runtime-data default."""
    return omemo_storage_file(config).resolve()


def _identity_metadata_path(storage_path: Path) -> Path:
    """Return the metadata file tied to one OMEMO storage file."""
    # Keep this helper for the OMEMO implementation/tests while sharing the
    # public runtime-path policy used by backup/systemd code.
    return omemo_identity_file({"omemo_storage_file": str(storage_path)})


def _current_identity(config: Mapping[str, Any]) -> dict[str, str]:
    """Return the configured identity that makes an OMEMO store safe to reuse."""
    return {
        "jid": str(config.get("jid") or "").strip(),
        "resource": str(config.get("resource") or "").strip(),
        "nick": str(config.get("nick") or "").strip(),
    }


def _read_identity_metadata(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise RuntimeError(f"OMEMO identity metadata is not an object: {path}")
    return {
        "jid": str(data.get("jid", "")).strip(),
        "resource": str(data.get("resource", "")).strip(),
        "nick": str(data.get("nick", "")).strip(),
    }


def _write_identity_metadata(path: Path, identity: dict[str, str]) -> None:
    ensure_private_directory(path.parent)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp_path, flags, PRIVATE_FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf8") as handle:
        json.dump(identity, handle, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp_path, PRIVATE_FILE_MODE)
    tmp_path.replace(path)
    os.chmod(path, PRIVATE_FILE_MODE)


def _backup_path(path: Path, timestamp: str) -> Path:
    candidate = path.with_name(f"{path.name}.bak-{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak-{timestamp}-{counter}")
        counter += 1
    return candidate


def _backup_existing_path(path: Path, timestamp: str) -> Path | None:
    if not path.exists():
        return None
    backup = _backup_path(path, timestamp)
    shutil.move(str(path), str(backup))
    os.chmod(backup, PRIVATE_FILE_MODE)
    return backup


def _ensure_identity_metadata(
    storage_path: Path,
    identity: dict[str, str],
    *,
    reset_on_change: bool,
) -> Path | None:
    """Keep OMEMO state bound to the configured JID/resource/nick identity."""
    metadata_path = _identity_metadata_path(storage_path)
    previous_identity = _read_identity_metadata(metadata_path)

    if previous_identity is None:
        storage_backup = None
        if reset_on_change and storage_path.exists() and storage_path.is_file():
            try:
                existing_content = storage_path.read_text(encoding="utf8").strip()
            except UnicodeDecodeError:
                existing_content = "<binary>"
            if existing_content and existing_content != "{}":
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                storage_backup = _backup_existing_path(storage_path, timestamp)
                if storage_backup is not None:
                    log.warning(
                        "[OMEMO] Existing storage had no identity metadata; moved it to %s",
                        storage_backup,
                    )
        _write_identity_metadata(metadata_path, identity)
        log.info("[OMEMO] Wrote identity metadata %s", metadata_path)
        return storage_backup

    if previous_identity == identity:
        return None

    log.warning(
        "[OMEMO] Identity changed (old jid=%s resource=%s nick=%s; new jid=%s resource=%s nick=%s)",
        previous_identity.get("jid", ""),
        previous_identity.get("resource", ""),
        previous_identity.get("nick", ""),
        identity.get("jid", ""),
        identity.get("resource", ""),
        identity.get("nick", ""),
    )

    if not reset_on_change:
        log.warning("[OMEMO] Keeping existing storage because OMEMO_RESET_ON_IDENTITY_CHANGE=False")
        return None

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    storage_backup = _backup_existing_path(storage_path, timestamp)
    _backup_existing_path(metadata_path, timestamp)
    _write_identity_metadata(metadata_path, identity)
    if storage_backup is not None:
        log.warning("[OMEMO] Storage moved to %s after identity change", storage_backup)
    return storage_backup


def _prepare_storage_file(path: Path) -> Path:
    """Create and secure the JSON storage used by slixmpp-omemo."""
    if not str(path).strip():
        raise RuntimeError("OMEMO storage path must not be empty")
    ensure_private_directory(path.parent)
    if path.exists():
        if path.is_dir():
            raise RuntimeError(f"OMEMO storage path is a directory: {path}")
        os.chmod(path, PRIVATE_FILE_MODE)
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, PRIVATE_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf8") as handle:
            handle.write("{}\n")
    return path


if OMEMO_AVAILABLE and XEP_0384 is not None:

    class JsonFileStorage(Storage):
        """Small private JSON-file backed OMEMO storage."""

        def __init__(self, json_file_path: Path) -> None:
            super().__init__()
            self._json_file_path = _prepare_storage_file(Path(json_file_path))
            self._data: dict[str, JSONType] = {}
            with self._json_file_path.open(encoding="utf8") as handle:
                content = handle.read().strip()
                self._data = json.loads(content) if content else {}

        async def _load(self, key: str) -> Maybe[JSONType]:
            if key in self._data:
                return Just(self._data[key])
            return Nothing()

        async def _store(self, key: str, value: JSONType) -> None:
            self._data[key] = value
            self._write()

        async def _delete(self, key: str) -> None:
            self._data.pop(key, None)
            self._write()

        def _write(self) -> None:
            tmp_path = self._json_file_path.with_suffix(self._json_file_path.suffix + ".tmp")
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(tmp_path, flags, PRIVATE_FILE_MODE)
            with os.fdopen(fd, "w", encoding="utf8") as handle:
                json.dump(self._data, handle)
            os.chmod(tmp_path, PRIVATE_FILE_MODE)
            tmp_path.replace(self._json_file_path)
            os.chmod(self._json_file_path, PRIVATE_FILE_MODE)

    class _XEP_0384Impl(XEP_0384):
        """slixmpp-omemo plugin implementation for EnvsBot."""

        default_config = {
            "fallback_message": "This message is OMEMO encrypted.",
            "json_file_path": None,
        }

        def plugin_init(self) -> None:
            if not self.json_file_path:
                raise RuntimeError("OMEMO JSON storage path not specified")
            storage_factory = cast(Callable[[Path], Storage], JsonFileStorage)
            self._storage = storage_factory(Path(self.json_file_path))
            super().plugin_init()

        @property
        def storage(self) -> Storage:
            return self._storage

        @property
        def _btbv_enabled(self) -> bool:
            return True

        async def _devices_blindly_trusted(
            self,
            blindly_trusted: frozenset[DeviceInformation],
            identifier: str | None,
        ) -> None:
            jid_count = len(
                {
                    getattr(device, "bare_jid", None)
                    for device in blindly_trusted
                    if getattr(device, "bare_jid", None)
                }
            )
            log.info(
                "[OMEMO] [%s] blindly trusted %d device(s) for %d JID(s)",
                identifier,
                len(blindly_trusted),
                jid_count,
            )

        async def _prompt_manual_trust(
            self,
            manually_trusted: frozenset[DeviceInformation],
            identifier: str | None,
        ) -> None:
            log.warning(
                "[OMEMO] [%s] manual trust requested for %d device(s), but interactive trust is disabled",
                identifier,
                len(manually_trusted),
            )

    XEP_0384Impl = _XEP_0384Impl
    register_plugin(_XEP_0384Impl)


class OmemoMixin:
    """Transparent incoming decrypt / matching outgoing reply encryption."""

    def _omemo_host(self) -> _OmemoHost:
        """Return the concrete XMPP-client surface required by this mixin."""
        return cast(_OmemoHost, self)

    def _configure_omemo_dependency_logging(self) -> None:
        if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
            return
        for logger_name in (
            "omemo",
            "omemo.core",
            "slixmpp_omemo",
            "slixmpp_omemo.xep_0384",
        ):
            logging.getLogger(logger_name).setLevel(logging.ERROR)

    def configure_omemo(self) -> None:
        """Register OMEMO when enabled; plaintext operation remains optional."""
        host = self._omemo_host()
        config = host.config
        self.omemo_enabled = bool(config.get("omemo_enabled", False))
        self.omemo_plaintext_fallback = bool(config.get("omemo_plaintext_fallback", False))
        self.omemo_reset_on_identity_change = bool(config.get("omemo_reset_on_identity_change", True))
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
                "Install the required system libraries plus the 'omemo' extra or "
                "requirements-omemo.txt and restart."
            )
            self.omemo_enabled = False
            return

        try:
            identity = _current_identity(config)
            _ensure_identity_metadata(
                storage_path,
                identity,
                reset_on_change=self.omemo_reset_on_identity_change,
            )
            storage_path = _prepare_storage_file(storage_path)
        except Exception as exc:
            log.error("[OMEMO] Could not prepare secure storage %s: %s", storage_path, exc)
            raise RuntimeError(f"Could not prepare OMEMO storage: {exc}") from exc

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
        if not getattr(self, "omemo_enabled", False):
            return False
        if self.omemo_ready.is_set():
            return True
        timeout = max(0, int(getattr(self, "omemo_ready_timeout", 15)))
        try:
            await asyncio.wait_for(self.omemo_ready.wait(), timeout=timeout)
            return True
        except TimeoutError:
            log.warning("[OMEMO] Initialization did not complete within %ss", timeout)
            return False

    @staticmethod
    def _normalize_bare_jid(value: object) -> str | None:
        try:
            text = str(value).strip()
            if not text:
                return None
            bare = str(JID(text).bare).strip().lower()
        except Exception:
            return None
        return bare or None

    def _bare_jid(self, value: object) -> str:
        bare = self._normalize_bare_jid(value)
        if not bare:
            raise ValueError("OMEMO recipient does not contain a valid bare JID")
        return bare

    async def _omemo_recipients_for_room(self, room_jid: str) -> set[JID]:
        """Collect visible real bare JIDs for a MUC encrypted reply."""
        room = self._normalize_bare_jid(room_jid)
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

        own_bare = self._normalize_bare_jid(getattr(getattr(self, "boundjid", None), "bare", ""))
        recipients: set[JID] = set()
        for info in (room_data.get("nicks", {}) or {}).values():
            jid = info.get("jid") if isinstance(info, dict) else None
            bare = self._normalize_bare_jid(jid) if jid else None
            if bare and bare != own_bare:
                recipients.add(JID(bare))

        # Keep the bot's other OMEMO devices in sync when there are actual
        # recipients. Never encrypt a MUC reply only to the bot itself.
        if recipients and own_bare:
            recipients.add(JID(own_bare))
        return recipients

    def _omemo_recipient_for_chat(self, target: object) -> JID:
        """Resolve a direct chat or MUC-PM target to the real OMEMO bare JID."""
        jid = JID(str(target))
        room = str(jid.bare).strip()
        nick = str(jid.resource or "").strip()
        if nick and room:
            room_data = JOINED_ROOMS.get(room)
            if room_data is None:
                for cached_room, cached_data in JOINED_ROOMS.items():
                    if str(cached_room).casefold() == room.casefold():
                        room_data = cached_data
                        break
            if isinstance(room_data, dict):
                nicks = room_data.get("nicks", {}) or {}
                info = nicks.get(nick)
                if info is None:
                    for cached_nick, cached_info in nicks.items():
                        if str(cached_nick).casefold() == nick.casefold():
                            info = cached_info
                            break
                if isinstance(info, dict):
                    real_bare = self._normalize_bare_jid(info.get("jid"))
                    if real_bare:
                        return JID(real_bare)
        return JID(jid.bare)

    async def _send_omemo_message_object(self, msg: Any) -> Any:
        """Encrypt and send an already-built outbound Message stanza."""
        if not await self._wait_for_omemo_ready():
            raise RuntimeError("OMEMO is not initialized")
        plugin = self._omemo_host().plugin
        if "xep_0384" not in plugin:
            raise RuntimeError("OMEMO plugin is not registered")

        mto = msg["to"]
        mtype = str(msg["type"] or "chat")
        if mtype == "groupchat":
            recipients: set[JID] | JID = await self._omemo_recipients_for_room(str(mto))
        else:
            recipients = self._omemo_recipient_for_chat(mto)

        if isinstance(recipients, set) and not recipients:
            raise RuntimeError(f"No OMEMO recipients available for {mto}")
        return await self._encrypt_and_send_omemo_message(msg, recipients, mto=str(mto))

    async def _encrypt_and_send_omemo_message(
        self,
        msg: Any,
        recipients: set[JID] | JID,
        *,
        mto: str,
    ) -> Any:
        if not isinstance(recipients, set):
            return await self._encrypt_and_send_omemo_once(msg, recipients, mto=mto)

        current_recipients = set(recipients)
        skipped_recipients: set[str] = set()
        max_attempts = max(1, len(current_recipients) + 1)
        for _attempt in range(max_attempts):
            if not current_recipients:
                raise RuntimeError(f"No usable OMEMO recipients left for {mto}")
            try:
                return await self._encrypt_and_send_omemo_once(msg, current_recipients, mto=mto)
            except Exception as exc:
                missing = self._extract_unusable_omemo_recipients(exc)
                if not missing:
                    raise
                before = set(current_recipients)
                current_recipients = {
                    jid for jid in current_recipients if self._bare_jid(jid).lower() not in missing
                }
                removed = {
                    self._bare_jid(jid).lower()
                    for jid in before
                    if self._bare_jid(jid).lower() in missing
                }
                if not removed:
                    raise
                skipped_recipients.update(removed)
                log.warning(
                    "[OMEMO] Skipping %d recipient(s) without usable devices for %s",
                    len(removed),
                    mto,
                )
                if not current_recipients:
                    raise RuntimeError(
                        f"No usable OMEMO recipients left for {mto}; "
                        f"skipped {len(skipped_recipients)} recipient(s)"
                    ) from exc
        raise RuntimeError(
            f"Could not encrypt OMEMO message for {mto}; skipped {len(skipped_recipients)} recipient(s)"
        )

    async def _encrypt_and_send_omemo_once(
        self,
        msg: Any,
        recipients: set[JID] | JID,
        *,
        mto: str,
    ) -> Any:
        encrypted_result = await self._omemo_host().plugin["xep_0384"].encrypt_message(
            msg, recipients
        )
        errors = None
        encrypted_messages = encrypted_result
        if isinstance(encrypted_result, tuple) and len(encrypted_result) == 2:
            encrypted_messages, errors = encrypted_result
        if errors:
            error_count = len(errors) if hasattr(errors, "__len__") else 1
            log.warning("[OMEMO] Encryption returned %d error(s) for %s", error_count, mto)
        if not encrypted_messages:
            raise RuntimeError(f"OMEMO produced no encrypted messages for {mto}")

        echo = None
        if isinstance(encrypted_messages, Mapping):
            for _jid, encrypted_msg in encrypted_messages.items():
                echo = encrypted_msg
                encrypted_msg.send()
        else:
            echo = encrypted_messages
            echo.send()
        return echo

    def _extract_unusable_omemo_recipients(self, exc: Exception) -> set[str]:
        text = str(exc)
        matches = re.findall(r"['\"]([^'\"]+@[^'\"]+)['\"]", text)
        recipients: set[str] = set()
        for match in matches:
            bare = self._normalize_bare_jid(match)
            if bare:
                recipients.add(bare)
        return recipients

    @staticmethod
    def _message_has_omemo_payload(msg: Any) -> bool:
        namespaces = (
            "eu.siacs.conversations.axolotl",
            "urn:xmpp:omemo:2",
        )
        try:
            xml = msg.xml
        except Exception:
            return False
        return any(xml.find(f".//{{{namespace}}}encrypted") is not None for namespace in namespaces)

    async def _decrypt_incoming_omemo_message(self, msg: Any) -> tuple[Any | None, bool]:
        """Return ``(decrypted_message, was_encrypted)`` for one incoming stanza."""
        if not self._message_has_omemo_payload(msg):
            return msg, False

        if not getattr(self, "omemo_enabled", False):
            log.info("[OMEMO] Encrypted incoming message ignored while OMEMO is disabled")
            return None, True
        plugin = self._omemo_host().plugin
        if "xep_0384" not in plugin:
            log.warning("[OMEMO] Encrypted incoming message ignored because the plugin is unavailable")
            return None, True

        omemo = plugin["xep_0384"]
        try:
            namespace = omemo.is_encrypted(msg)
        except Exception:
            log.warning("[OMEMO] Could not inspect encrypted incoming message; ignoring stanza")
            return None, True
        if not namespace:
            log.info("[OMEMO] Encrypted payload was not recognized by the active plugin; ignoring stanza")
            return None, True
        if not await self._wait_for_omemo_ready():
            log.warning("[OMEMO] Encrypted incoming message received before OMEMO was ready")
            return None, True

        try:
            result = await omemo.decrypt_message(msg)
            decrypted_msg = result[0] if isinstance(result, tuple) else result
            return decrypted_msg, True
        except Exception as exc:
            if self._is_expected_device_info_error(exc):
                log.info("[OMEMO] Sender device information unavailable; encrypted message ignored")
            else:
                log.warning("[OMEMO] Failed to decrypt incoming message")
            return None, True

    @staticmethod
    def _is_expected_device_info_error(exc: Exception) -> bool:
        error_text = str(exc)
        known_markers = (
            "Couldn't find public information about the device",
            "device either does not appear in the device list",
            "bundle of the sending device could not be downloaded",
            "Bundle download failed",
            "Bundle not available",
            "could not be downloaded",
        )
        return any(marker in error_text for marker in known_markers)

    def omemo_status(self) -> dict[str, Any]:
        """Return compact runtime state for status/diagnostics."""
        storage = Path(str(getattr(self, "omemo_storage_file", "")))
        return {
            "enabled": bool(getattr(self, "omemo_enabled", False)),
            "available": OMEMO_AVAILABLE,
            "ready": bool(getattr(self, "omemo_ready", None) and self.omemo_ready.is_set()),
            "storage": str(storage) if str(storage) else "-",
            "plaintext_fallback": bool(getattr(self, "omemo_plaintext_fallback", False)),
        }


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
