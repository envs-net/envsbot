"""envsbot's real adapters consume the same contract vectors as BanBot."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from envs_xmpp_core.runtime.rooms import RoomLifecycleRegistry
from envs_xmpp_ops.contract_cases import CONFIG_CASES, ENCRYPTION_CASES, INCOMING_CASES, ROOM_CASES

from bot import messages as messages_module
from bot.messages import MessageMixin
from bot.routing import MessageRoutingMixin
from core_plugins.rooms import commands as rooms_commands
from utils.config.runtime import config_change_lines


class _Sender:
    def __init__(self, jid: str) -> None:
        self.bare, _, self.resource = jid.partition("/")
        self.jid = jid

    def __str__(self) -> str:
        return self.jid


class _IncomingBot(MessageRoutingMixin):
    accepting_commands = True
    bot_plugins = None

    def __init__(self) -> None:
        self.presence = SimpleNamespace(joined_rooms={"room@conference.example.test": "Bot"})
        self.handled: list[tuple[object, ...]] = []
        self.cached: list[bool] = []
        self.encryption: list[bool] = []

    async def handle_command(self, *args: object) -> None:
        self.handled.append(args)

    async def _cache_incoming_message(self, _msg: object, *, is_room: bool) -> None:
        self.cached.append(is_room)

    def _set_reply_encryption_context(self, encrypted: bool) -> object:
        self.encryption.append(encrypted)
        return "token"

    def _reset_reply_encryption_context(self, token: object) -> None:
        assert token == "token"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", INCOMING_CASES, ids=lambda case: case.name)
async def test_incoming_transport_routes_and_retains_policy(case) -> None:
    bot = _IncomingBot()
    msg = {"from": _Sender(case.sender), "type": case.message_type, "mucnick": "Alice", "body": ",status"}
    await bot.on_muc_message(msg)
    await bot.on_private_message(msg)
    assert len(bot.handled) == int(case.public_command) + int(case.private_command)
    assert bot.cached == ([True] if case.public_command else [False] if case.private_command else [])
    if bot.handled:
        assert bot.handled[0][-1] is case.public_command
        assert bot.encryption == [False]


@pytest.mark.asyncio
async def test_decryption_failure_cannot_dispatch_or_cache_plaintext() -> None:
    bot = _IncomingBot()

    async def decrypt(_msg: object) -> tuple[None, bool]:
        return None, True

    bot._decrypt_incoming_omemo_message = decrypt  # type: ignore[attr-defined]
    await bot.on_muc_message({"from": _Sender("room@conference.example.test/Alice"),
                              "type": "groupchat", "mucnick": "Alice", "body": "cipher"})
    assert not bot.handled and not bot.cached


@pytest.mark.parametrize("case", ROOM_CASES, ids=lambda case: case.name)
def test_room_inventory_uses_authoritative_presence(monkeypatch: pytest.MonkeyPatch, case) -> None:
    room = "room@conference.example.test"
    registry = RoomLifecycleRegistry()
    if case.lifecycle == "joining":
        registry.begin_join(room)
    elif case.lifecycle == "failed":
        registry.mark_failed(room)
    elif case.lifecycle == "deferred":
        registry.mark_deferred(room)
    elif case.lifecycle == "leaving":
        registry.begin_leave(room)
    elif case.lifecycle == "joined":
        registry.confirm_self_presence(room, "Bot")
    monkeypatch.setattr(rooms_commands, "ROOM_LIFECYCLE", registry)
    monkeypatch.setattr(rooms_commands, "JOINED_ROOMS", {})
    bot = SimpleNamespace(presence=SimpleNamespace(joined_rooms={room: "Bot"} if case.presence_verified else {}))
    view = rooms_commands._muc_room_views(bot, [(room, "Bot", True, None)])[0]
    assert view.joined is case.presence_verified
    assert view.state == case.expected_state
    assert view.needs_attention is case.needs_attention


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ENCRYPTION_CASES, ids=lambda case: case.name)
async def test_reply_encryption_adapter_preserves_explicit_choice(
    monkeypatch: pytest.MonkeyPatch, case
) -> None:
    class _Message:
        def __init__(self) -> None:
            self.plain_sends = 0

        def send(self) -> bool:
            self.plain_sends += 1
            return True

    class _Bot(MessageMixin):
        async def _send_omemo_message_object(self, _message: object) -> None:
            self.encrypted_sends += 1

    monkeypatch.setattr(messages_module, "session_is_ready", lambda _bot: True)
    bot = _Bot()
    bot.encrypted_sends = 0
    message = _Message()
    token = bot._set_reply_encryption_context(case.inherited)
    try:
        result = await bot._safe_send_message(message, encrypted=case.explicit)
    finally:
        bot._reset_reply_encryption_context(token)
    assert result is True
    assert bot.encrypted_sends == int(case.effective is True)
    assert message.plain_sends == int(case.effective is not True)


@pytest.mark.asyncio
async def test_rejected_omemo_transport_is_not_reported_as_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit False must not advance a caller's delivery cursor."""
    class _Bot(MessageMixin):
        omemo_plaintext_fallback = False

        async def _send_omemo_message_object(self, _message: object) -> bool:
            return False

    class _Message:
        def send(self) -> None:
            raise AssertionError("encrypted reply fell back to plaintext")

    monkeypatch.setattr(messages_module, "session_is_ready", lambda _bot: True)
    bot = _Bot()
    assert await bot._safe_send_message(_Message(), encrypted=True) is False


@pytest.mark.parametrize("case", CONFIG_CASES, ids=lambda case: case.name)
def test_config_diff_adapter_redacts_secrets(case) -> None:
    lines = config_change_lines(case.before, case.after)
    assert lines
    assert case.secret not in "\n".join(lines)
    assert "<redacted>" in "\n".join(lines)


def test_task_snapshot_uses_the_canonical_shared_model() -> None:
    from envs_xmpp_core.runtime import TaskInfo as SharedTaskInfo

    from utils.task_supervisor import TaskInfo as BotTaskInfo

    assert BotTaskInfo is SharedTaskInfo
    item = BotTaskInfo(
        scope="rss", name="refresh", status="running", created_at="2026-09-30T00:00:00+00:00",
        done_at=None, cancelled=False, last_error=None,
    )
    assert item.identity == ("rss", "refresh")
    assert item.plugin == item.group == "rss"  # Compatibility adapters must not fork identity.


@pytest.mark.asyncio
async def test_plaintext_fallback_only_when_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Bot(MessageMixin):
        omemo_plaintext_fallback = True

        async def _send_omemo_message_object(self, _message: object) -> bool:
            return False

    class _Message:
        plain_sends = 0

        def send(self) -> bool:
            self.plain_sends += 1
            return True

    monkeypatch.setattr(messages_module, "session_is_ready", lambda _bot: True)
    bot = _Bot()
    message = _Message()
    assert await bot._safe_send_message(message, encrypted=True) is True
    assert message.plain_sends == 1
