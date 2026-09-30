"""Integration tests for the shared incoming message context in envsbot routing."""

from types import SimpleNamespace

import pytest

from bot import routing as routing_module
from bot.routing import MessageRoutingMixin


class _Sender:
    def __init__(self, bare: str, resource: str = "Alice") -> None:
        self.bare = bare
        self.resource = resource

    def __str__(self) -> str:
        return f"{self.bare}/{self.resource}" if self.resource else self.bare


class _Bot(MessageRoutingMixin):
    def __init__(self) -> None:
        self.accepting_commands = True
        self.presence = SimpleNamespace(joined_rooms={"room@conference.example.org": "Bot"})
        self.cached: list[bool] = []
        self.cached_stanzas: list[object] = []
        self.handled: list[tuple[object, ...]] = []
        self.tokens: list[bool] = []
        self.resets: list[object] = []
        self.bot_plugins = None

    async def _cache_incoming_message(self, msg: object, *, is_room: bool) -> None:
        self.cached.append(is_room)
        self.cached_stanzas.append(msg)

    async def handle_command(self, *args: object) -> None:
        self.handled.append(args)

    def _set_reply_encryption_context(self, encrypted: bool) -> object:
        self.tokens.append(encrypted)
        return object()

    def _reset_reply_encryption_context(self, token: object) -> None:
        self.resets.append(token)


def _msg(msg_type: str, *, body: str = "hi") -> dict[str, object]:
    return {
        "from": _Sender("room@conference.example.org" if msg_type == "groupchat" else "alice@example.org"),
        "type": msg_type,
        "mucnick": "Alice",
        "body": body,
    }


@pytest.mark.asyncio
async def test_groupchat_shared_context_keeps_plaintext_cache_and_dispatch() -> None:
    bot = _Bot()
    msg = _msg("groupchat", body="  ,status  ")
    await bot.on_muc_message(msg)
    assert bot.cached == [True]
    assert bot.handled == [("  ,status  ", msg["from"], "Alice", msg, True)]
    assert bot.tokens == [False]
    assert len(bot.resets) == 1


@pytest.mark.asyncio
async def test_encrypted_groupchat_never_caches_decrypted_text() -> None:
    bot = _Bot()
    original = _msg("groupchat", body="encrypted-placeholder")
    clear = _msg("groupchat", body=",status")

    async def decrypt(_msg: object) -> tuple[object, bool]:
        return clear, True

    bot._decrypt_incoming_omemo_message = decrypt  # type: ignore[attr-defined]
    await bot.on_muc_message(original)
    assert bot.cached == []
    assert bot.handled == [(",status", clear["from"], "Alice", clear, True)]
    assert bot.tokens == [True]
    assert len(bot.resets) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("message_type", ["chat", "normal"])
async def test_direct_and_normal_messages_use_same_context_without_changing_cache(message_type: str) -> None:
    bot = _Bot()
    msg = _msg(message_type, body="hello")
    await bot.on_private_message(msg)
    assert bot.cached == [False]
    assert bot.cached_stanzas == [msg]
    assert bot.handled == [("hello", msg["from"], None, msg, False)]
    assert bot.tokens == [False]
    assert len(bot.resets) == 1


@pytest.mark.asyncio
async def test_private_routing_classifies_joined_room_occupants_as_muc_pm(monkeypatch) -> None:
    """MUC occupant JIDs must not be classified as ordinary account DMs."""
    bot = _Bot()
    msg = _msg("chat", body=",status")
    msg["from"] = _Sender("room@conference.example.org", "Alice")

    observed_contexts = []
    original_context = routing_module.message_context_from_stanza

    def capture_context(stanza, **kwargs):
        context = original_context(stanza, **kwargs)
        observed_contexts.append(context)
        return context

    monkeypatch.setattr(routing_module, "message_context_from_stanza", capture_context)
    await bot.on_private_message(msg)

    assert len(observed_contexts) == 2
    assert not observed_contexts[0].is_muc_pm  # Initial wire-type check has no room state.
    assert observed_contexts[1].is_muc_pm
    assert observed_contexts[1].room == "room@conference.example.org"
    assert observed_contexts[1].real_jid is None  # A MUC nick is not an account identity.
    assert bot.cached_stanzas == [msg]
    assert bot.handled == [(",status", msg["from"], None, msg, False)]
