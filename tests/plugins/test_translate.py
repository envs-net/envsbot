from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest

import plugins.translate as translate
from core_plugins import _core


class DummyFrom:
    def __init__(self, bare: str, resource: str | None = None):
        self.bare = bare
        self.resource = resource


def make_message(
    body: str,
    *,
    room: str = "room@conference.example.org",
    nick: str = "alice",
    msg_type: str = "groupchat",
    stanza_id: str | None = "msg-1",
    reply_id: str | None = None,
):
    msg = {
        "body": body,
        "from": DummyFrom(room, nick),
        "type": msg_type,
        "mucnick": nick if msg_type == "groupchat" else None,
    }
    if stanza_id is not None:
        msg["id"] = stanza_id
    if reply_id is not None:
        msg["reply"] = {"id": reply_id}
    return msg


@pytest.fixture(autouse=True)
def clear_translate_caches(monkeypatch):
    monkeypatch.setattr(translate, "CACHE_NAMESPACE", "translate-test")
    for namespace in ("translate-test", "translate-test-fallback-command"):
        _core._SHARED_MESSAGE_CACHES[namespace].clear()
        _core._SHARED_PROCESSED_STANZAS[namespace].clear()
        _core._SHARED_PROCESSED_STANZA_ORDER[namespace].clear()
    yield
    for namespace in ("translate-test", "translate-test-fallback-command"):
        _core._SHARED_MESSAGE_CACHES[namespace].clear()
        _core._SHARED_PROCESSED_STANZAS[namespace].clear()
        _core._SHARED_PROCESSED_STANZA_ORDER[namespace].clear()


def test_parse_translation_args_explicit_languages():
    request = translate._parse_translation_args(["en", "uk", "Hello,", "world!"])
    assert request.source_language == "en"
    assert request.target_language == "uk"
    assert request.text == "Hello, world!"


def test_parse_translation_args_auto_detection_forms():
    omitted = translate._parse_translation_args(["de", "Hello", "world"])
    assert omitted.source_language == "auto"
    assert omitted.target_language == "de"
    assert omitted.text == "Hello world"

    explicit = translate._parse_translation_args(["auto", "pl", "Hallo"])
    assert explicit.source_language == "auto"
    assert explicit.target_language == "pl"
    assert explicit.text == "Hallo"


def test_parse_translation_args_rejects_missing_or_auto_target():
    with pytest.raises(translate.TranslationUsageError, match="Missing target"):
        translate._parse_translation_args([])
    with pytest.raises(translate.TranslationUsageError, match="target language"):
        translate._parse_translation_args(["auto", "hello"])
    with pytest.raises(translate.TranslationUsageError, match="Unsupported language"):
        translate._parse_translation_args(["english", "de", "hello"])


def test_language_code_normalization_supports_bcp47():
    assert translate._normalize_language_code("ZH_CN") == "zh-cn"
    assert translate._is_supported_language("zh-CN") is True
    assert translate._is_supported_language("lv") is True
    assert translate._is_supported_language("auto") is True
    assert translate._is_supported_language("auto", allow_auto=False) is False


@pytest.mark.asyncio
async def test_translate_text_builds_provider_request_and_parses_result():
    calls = []

    async def fake_fetcher(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(
            data=[[["Привіт, світе!", "Hello, world!", None, None]], None, "en"]
        )

    result = await translate.translate_text(
        "Hello, world!",
        source_language="en",
        target_language="uk",
        fetcher=fake_fetcher,
    )

    assert result.text == "Привіт, світе!"
    assert result.source_language == "en"
    parsed = urlparse(calls[0][0])
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "translate.googleapis.com"
    assert query["sl"] == ["en"]
    assert query["tl"] == ["uk"]
    assert query["q"] == ["Hello, world!"]
    assert calls[0][1]["max_redirects"] == 0
    assert calls[0][1]["allow_private"] is False


@pytest.mark.asyncio
async def test_translate_text_rejects_long_input(monkeypatch):
    monkeypatch.setattr(translate, "TRANSLATE_MAX_INPUT_LENGTH", 4)
    with pytest.raises(translate.TranslationUsageError, match="too long"):
        await translate.translate_text(
            "12345",
            source_language="auto",
            target_language="de",
            fetcher=AsyncMock(),
        )


def test_provider_payload_helpers_cover_nested_detection_and_errors():
    nested = [[["Hallo", "Hello"]], None, None, None, None, None, None, None, [["en"]]]
    assert translate._translation_text_from_payload(nested) == "Hallo"
    assert translate._detected_language_from_payload(nested) == "en"
    with pytest.raises(translate.TranslationProviderError):
        translate._translation_text_from_payload({"bad": "shape"})
    with pytest.raises(translate.TranslationProviderError):
        translate._translation_text_from_payload([[]])


@pytest.mark.asyncio
async def test_translate_command_translates_direct_text(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(
        ",tr en uk Hello, world!",
        room="alice@example.org",
        msg_type="chat",
    )
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    worker = AsyncMock(return_value=translate.TranslationResult("Привіт, світе!", "en"))
    monkeypatch.setattr(translate, "translate_text", worker)

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["en", "uk", "Hello,", "world!"],
        msg,
        False,
    )

    worker.assert_awaited_once_with(
        "Hello, world!",
        target_language="uk",
        source_language="en",
    )
    bot.reply.assert_called_once_with(msg, "Привіт, світе!", mention=False)


@pytest.mark.asyncio
async def test_translate_command_uses_cached_reply_target(monkeypatch):
    room = "room@conference.example.org"
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(",tr uk", room=room, reply_id="original")
    _core.cache_message(
        translate.CACHE_NAMESPACE,
        room,
        "bob",
        "Hello from the cache",
        "original",
        maxlen=20,
    )
    monkeypatch.setattr(
        _core, "handle_room_toggle_command", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    worker = AsyncMock(return_value=translate.TranslationResult("Привіт із кешу", "en"))
    monkeypatch.setattr(translate, "translate_text", worker)

    await translate.translate_command(
        bot, "alice@example.org", "alice", ["uk"], msg, True
    )

    worker.assert_awaited_once_with(
        "Hello from the cache",
        target_language="uk",
        source_language="auto",
    )
    bot.reply.assert_called_once_with(msg, "Привіт із кешу", mention=False)


@pytest.mark.asyncio
async def test_translate_command_uses_xep0461_quote_fallback(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message("> Hello from fallback\n,tr de", reply_id="not-cached")
    monkeypatch.setattr(
        _core, "handle_room_toggle_command", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    worker = AsyncMock(
        return_value=translate.TranslationResult("Hallo aus dem Fallback", "en")
    )
    monkeypatch.setattr(translate, "translate_text", worker)

    await translate.translate_command(
        bot, "alice@example.org", "alice", ["de"], msg, True
    )

    worker.assert_awaited_once_with(
        "Hello from fallback",
        target_language="de",
        source_language="auto",
    )


@pytest.mark.asyncio
async def test_translate_command_reports_missing_reply_text(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(",tr de")
    monkeypatch.setattr(
        _core, "handle_room_toggle_command", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )

    await translate.translate_command(
        bot, "alice@example.org", "alice", ["de"], msg, True
    )

    output = bot.reply.call_args.args[1]
    assert "could not be resolved" in output
    assert "Usage:" in output


@pytest.mark.asyncio
async def test_translate_command_respects_room_toggle(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(",tr de hello")
    monkeypatch.setattr(
        _core, "handle_room_toggle_command", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=False)
    )

    await translate.translate_command(
        bot, "alice@example.org", "alice", ["de", "hello"], msg, True
    )

    assert "disabled" in bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_translate_command_handles_provider_failure(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(",tr de hello", room="alice@example.org", msg_type="chat")
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        translate,
        "translate_text",
        AsyncMock(side_effect=translate.TranslationProviderError("bad payload")),
    )

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["de", "hello"],
        msg,
        False,
    )

    assert "invalid response" in bot.reply.call_args.args[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [asyncio.TimeoutError(), aiohttp.ClientError()])
async def test_translate_command_handles_request_failure(monkeypatch, error):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(",tr de hello", room="alice@example.org", msg_type="chat")
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        translate,
        "translate_text",
        AsyncMock(side_effect=error),
    )

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["de", "hello"],
        msg,
        False,
    )

    assert "request failed" in bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_translate_command_handles_unexpected_failure(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(",tr de hello", room="alice@example.org", msg_type="chat")
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        translate,
        "translate_text",
        AsyncMock(side_effect=RuntimeError("unexpected")),
    )

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["de", "hello"],
        msg,
        False,
    )

    assert "internal error" in bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_groupchat_handler_caches_regular_messages(monkeypatch):
    room = "room@conference.example.org"
    bot = SimpleNamespace(
        nick="EnvsBot",
        presence=SimpleNamespace(joined_rooms={room: "EnvsBot"}),
        handle_command=AsyncMock(),
    )
    monkeypatch.setattr(_core, "JOINED_ROOMS", {room: {"nicks": {"alice": {}}}})
    monkeypatch.setattr(_core, "_is_enabled_for_room", AsyncMock(return_value=True))
    msg = make_message("A message to translate later", room=room, stanza_id="source-1")

    await translate._on_groupchat_message(bot, msg)

    cached = _core.get_cached_message_by_id(
        translate.CACHE_NAMESPACE,
        room,
        "source-1",
    )
    assert cached["body"] == "A message to translate later"
    assert cached["nick"] == "alice"
    bot.handle_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_groupchat_handler_redispatches_quote_fallback_command(monkeypatch):
    room = "room@conference.example.org"
    bot = SimpleNamespace(
        nick="EnvsBot",
        presence=SimpleNamespace(joined_rooms={room: "EnvsBot"}),
        handle_command=AsyncMock(),
    )
    monkeypatch.setattr(_core, "JOINED_ROOMS", {room: {"nicks": {"alice": {}}}})
    monkeypatch.setattr(_core, "_is_enabled_for_room", AsyncMock(return_value=True))
    msg = make_message("> Original text\n,tr uk", room=room, stanza_id="reply-command")

    await translate._on_groupchat_message(bot, msg)

    bot.handle_command.assert_awaited_once_with(
        ",tr uk",
        msg["from"],
        "alice",
        msg,
        True,
    )
    assert (
        _core.get_cached_message_by_id(
            translate.CACHE_NAMESPACE,
            room,
            "reply-command",
        )
        is None
    )


@pytest.mark.asyncio
async def test_groupchat_handler_skips_own_and_disabled_messages(monkeypatch):
    room = "room@conference.example.org"
    bot = SimpleNamespace(
        nick="EnvsBot",
        presence=SimpleNamespace(joined_rooms={room: "EnvsBot"}),
        handle_command=AsyncMock(),
    )
    monkeypatch.setattr(_core, "JOINED_ROOMS", {room: {}})
    enabled = AsyncMock(return_value=False)
    monkeypatch.setattr(_core, "_is_enabled_for_room", enabled)

    await translate._on_groupchat_message(
        bot,
        make_message("bot output", room=room, nick="EnvsBot", stanza_id="own"),
    )
    await translate._on_groupchat_message(
        bot,
        make_message("user output", room=room, nick="alice", stanza_id="disabled"),
    )

    enabled.assert_awaited_once()
    assert (
        _core.get_cached_message_by_id(translate.CACHE_NAMESPACE, room, "own") is None
    )
    assert (
        _core.get_cached_message_by_id(translate.CACHE_NAMESPACE, room, "disabled")
        is None
    )


@pytest.mark.asyncio
async def test_doctor_and_on_load(monkeypatch):
    register_event = Mock()
    bot = SimpleNamespace(bot_plugins=SimpleNamespace(register_event=register_event))

    await translate.on_load(bot)
    assert register_event.call_args.args[:2] == ("translate", "groupchat_message")

    global_lines = await translate.doctor(bot)
    assert global_lines[0].startswith("✅ Translate:")

    monkeypatch.setattr(_core, "_is_enabled_for_room", AsyncMock(return_value=True))
    room_lines = await translate.doctor(bot, "room@conference.example.org")
    assert "enabled" in room_lines[0]
