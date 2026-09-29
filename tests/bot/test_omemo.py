from __future__ import annotations

import asyncio
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from xml.etree import ElementTree as ET

import pytest

from bot.omemo import (
    OMEMO_AVAILABLE,
    OmemoMixin,
    _ensure_identity_metadata,
    _identity_metadata_path,
    _prepare_storage_file,
    _read_identity_metadata,
    _resolve_storage_path,
)


class DummyOmemoBot(OmemoMixin):
    def __init__(self, config=None):
        self.config = dict(config or {})
        self.plugin = {}
        self.boundjid = SimpleNamespace(bare="bot@example.org")
        self.register_plugin = MagicMock()
        self.add_event_handler = MagicMock()


class StrictPluginManager:
    """Mirror Slixmpp PluginManager.get(name, default)."""

    def __init__(self, plugins):
        self._plugins = dict(plugins)

    def get(self, name, default):
        return self._plugins.get(name, default)


class FakeMessage(dict):
    def __init__(self, *, xml=None, **values):
        super().__init__(values)
        self.xml = xml if xml is not None else ET.Element("message")


def test_omemo_storage_defaults_to_runtime_data_dir(tmp_path, monkeypatch):
    import utils.runtime_paths as runtime_paths

    monkeypatch.setattr(runtime_paths, "BASE_DIR", tmp_path)
    assert _resolve_storage_path({"runtime_data_dir": str(tmp_path / "runtime")}) == (
        tmp_path / "runtime" / "omemo.json"
    ).resolve()
    assert _resolve_storage_path({"omemo_storage_file": "data/custom-omemo.json"}) == (
        tmp_path / "data" / "custom-omemo.json"
    ).resolve()


def test_omemo_storage_and_identity_metadata_are_owner_only(tmp_path):
    storage = _prepare_storage_file(tmp_path / "state" / "omemo.json")
    identity = {"jid": "bot@example.org", "resource": "service", "nick": "Bot"}
    _ensure_identity_metadata(storage, identity, reset_on_change=True)
    metadata = _identity_metadata_path(storage)

    assert storage.read_text(encoding="utf-8").strip() == "{}"
    assert _read_identity_metadata(metadata) == identity
    assert stat.S_IMODE(storage.stat().st_mode) == 0o600
    assert stat.S_IMODE(metadata.stat().st_mode) == 0o600
    assert stat.S_IMODE(storage.parent.stat().st_mode) == 0o700


def test_identity_change_rotates_existing_storage(tmp_path):
    storage = _prepare_storage_file(tmp_path / "omemo.json")
    old = {"jid": "old@example.org", "resource": "service", "nick": "Bot"}
    new = {"jid": "new@example.org", "resource": "service", "nick": "Bot"}
    _ensure_identity_metadata(storage, old, reset_on_change=True)
    storage.write_text('{"session": "old"}\n', encoding="utf-8")

    backup = _ensure_identity_metadata(storage, new, reset_on_change=True)

    assert backup is not None
    assert backup.read_text(encoding="utf-8").strip() == '{"session": "old"}'
    assert not storage.exists()
    assert _read_identity_metadata(_identity_metadata_path(storage)) == new


def test_configure_omemo_disabled_is_noop(tmp_path):
    bot = DummyOmemoBot({"runtime_data_dir": str(tmp_path)})
    bot.configure_omemo()

    assert bot.omemo_enabled is False
    assert bot.omemo_plaintext_fallback is False
    assert bot.omemo_storage_file == str((tmp_path / "omemo.json").resolve())
    bot.register_plugin.assert_not_called()


def test_configure_omemo_missing_runtime_dependency_disables_cleanly(tmp_path):
    if OMEMO_AVAILABLE:
        pytest.skip("OMEMO runtime dependency is installed in this environment")
    bot = DummyOmemoBot({"omemo_enabled": True, "runtime_data_dir": str(tmp_path)})

    bot.configure_omemo()

    assert bot.omemo_enabled is False
    bot.register_plugin.assert_not_called()


@pytest.mark.asyncio
async def test_omemo_room_recipients_use_real_visible_jids(monkeypatch):
    import bot.omemo as omemo

    rooms = {
        "room@conference.example.org": {
            "nicks": {
                "Alice": {"jid": "alice@example.org/phone"},
                "Bob": {"jid": "bob@example.org/laptop"},
                "Hidden": {"jid": None},
                "Bot": {"jid": "bot@example.org/service"},
            }
        }
    }
    monkeypatch.setattr(omemo, "JOINED_ROOMS", rooms)
    bot = DummyOmemoBot()

    recipients = await bot._omemo_recipients_for_room("room@conference.example.org")

    assert {str(jid) for jid in recipients} == {
        "alice@example.org",
        "bob@example.org",
        "bot@example.org",
    }


def test_omemo_muc_pm_recipient_resolves_real_jid(monkeypatch):
    import bot.omemo as omemo

    monkeypatch.setattr(
        omemo,
        "JOINED_ROOMS",
        {
            "room@conference.example.org": {
                "nicks": {"Alice": {"jid": "alice@example.org/mobile"}}
            }
        },
    )
    bot = DummyOmemoBot()

    recipient = bot._omemo_recipient_for_chat("room@conference.example.org/Alice")

    assert str(recipient) == "alice@example.org"
    assert str(bot._omemo_recipient_for_chat("carol@example.org/desktop")) == "carol@example.org"


def test_omemo_payload_detection_requires_real_encrypted_element():
    legacy = ET.fromstring(
        "<message><encrypted xmlns='eu.siacs.conversations.axolotl'/></message>"
    )
    omemo2 = ET.fromstring("<message><encrypted xmlns='urn:xmpp:omemo:2'/></message>")
    fallback_only = ET.fromstring("<message><body>This message is OMEMO encrypted.</body></message>")

    assert OmemoMixin._message_has_omemo_payload(FakeMessage(xml=legacy)) is True
    assert OmemoMixin._message_has_omemo_payload(FakeMessage(xml=omemo2)) is True
    assert OmemoMixin._message_has_omemo_payload(FakeMessage(xml=fallback_only)) is False


@pytest.mark.asyncio
async def test_decrypt_incoming_omemo_success_and_plaintext_passthrough():
    bot = DummyOmemoBot()
    bot.omemo_enabled = True
    bot.omemo_ready = asyncio.Event()
    bot.omemo_ready.set()
    encrypted_xml = ET.fromstring(
        "<message><encrypted xmlns='eu.siacs.conversations.axolotl'/></message>"
    )
    encrypted = FakeMessage(xml=encrypted_xml, body="fallback")
    decrypted = FakeMessage(body=",status")
    plugin = SimpleNamespace(
        is_encrypted=MagicMock(return_value="eu.siacs.conversations.axolotl"),
        decrypt_message=AsyncMock(return_value=(decrypted, object())),
    )
    bot.plugin = {"xep_0384": plugin}

    result, was_encrypted = await bot._decrypt_incoming_omemo_message(encrypted)
    plain = FakeMessage(body=",help")
    plain_result, plain_encrypted = await bot._decrypt_incoming_omemo_message(plain)

    assert result is decrypted
    assert was_encrypted is True
    assert plain_result is plain
    assert plain_encrypted is False
    plugin.decrypt_message.assert_awaited_once_with(encrypted)


@pytest.mark.asyncio
async def test_omemo_accepts_slixmpp_style_plugin_manager_get_signature():
    bot = DummyOmemoBot()
    bot.omemo_enabled = True
    bot.omemo_ready = asyncio.Event()
    bot.omemo_ready.set()
    encrypted_xml = ET.fromstring(
        "<message><encrypted xmlns='eu.siacs.conversations.axolotl'/></message>"
    )
    encrypted = FakeMessage(xml=encrypted_xml, body="fallback")
    decrypted = FakeMessage(body=",status")
    plugin = SimpleNamespace(
        is_encrypted=MagicMock(return_value="eu.siacs.conversations.axolotl"),
        decrypt_message=AsyncMock(return_value=(decrypted, object())),
    )
    bot.plugin = StrictPluginManager({"xep_0384": plugin})

    result, was_encrypted = await bot._decrypt_incoming_omemo_message(encrypted)

    assert result is decrypted
    assert was_encrypted is True


@pytest.mark.asyncio
async def test_encrypted_fallback_body_is_never_reinterpreted_as_plaintext():
    bot = DummyOmemoBot()
    bot.omemo_enabled = False
    encrypted_xml = ET.fromstring(
        "<message><encrypted xmlns='urn:xmpp:omemo:2'/><body>,dangerous</body></message>"
    )
    message = FakeMessage(xml=encrypted_xml, body=",dangerous")

    result, was_encrypted = await bot._decrypt_incoming_omemo_message(message)

    assert result is None
    assert was_encrypted is True


@pytest.mark.asyncio
async def test_send_omemo_message_object_encrypts_direct_message():
    bot = DummyOmemoBot()
    bot.omemo_enabled = True
    bot.omemo_ready = asyncio.Event()
    bot.omemo_ready.set()
    encrypted_stanza = MagicMock()
    omemo_plugin = SimpleNamespace(
        encrypt_message=AsyncMock(return_value=encrypted_stanza),
    )
    bot.plugin = {"xep_0384": omemo_plugin}
    message = FakeMessage(to="alice@example.org/desktop", type="chat", body="secret")

    result = await bot._send_omemo_message_object(message)

    assert result is encrypted_stanza
    encrypted_stanza.send.assert_called_once_with()
    args = omemo_plugin.encrypt_message.await_args.args
    assert args[0] is message
    assert str(args[1]) == "alice@example.org"


def test_unusable_recipient_extraction_and_status(tmp_path):
    bot = DummyOmemoBot()
    bot.omemo_enabled = True
    bot.omemo_plaintext_fallback = False
    bot.omemo_storage_file = str(tmp_path / "omemo.json")
    bot.omemo_ready = asyncio.Event()
    bot.omemo_ready.set()

    missing = bot._extract_unusable_omemo_recipients(
        RuntimeError("devices unavailable for 'Alice@Example.org/phone' and 'bob@example.org'")
    )
    status = bot.omemo_status()

    assert missing == {"alice@example.org", "bob@example.org"}
    assert status["enabled"] is True
    assert status["ready"] is True
    assert status["plaintext_fallback"] is False
