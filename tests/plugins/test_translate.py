from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest

import plugins.translate as translate
from core_plugins import _core
from utils import message_cache


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
    monkeypatch.setattr(translate, "FALLBACK_NAMESPACE", "translate-test-fallback")
    monkeypatch.setattr(translate, "TRANSLATE_FROM", "auto")
    monkeypatch.setattr(translate, "TRANSLATE_TO", None)
    message_cache._PROCESSED_STANZAS.clear()
    message_cache._PROCESSED_STANZA_ORDER.clear()


def _bot_with_cache(*, room: str = "room@conference.example.org"):
    return SimpleNamespace(
        reply=Mock(),
        nick="EnvsBot",
        presence=SimpleNamespace(joined_rooms={room: "EnvsBot"}),
        message_cache=message_cache.MessageCache(max_messages=20),
        handle_command=AsyncMock(),
    )


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


def test_parse_translation_args_uses_configured_defaults(monkeypatch):
    monkeypatch.setattr(translate, "TRANSLATE_FROM", "en")
    monkeypatch.setattr(translate, "TRANSLATE_TO", "de")

    reply = translate._parse_translation_args([])
    assert reply == translate.TranslationRequest("en", "de", "")

    direct = translate._parse_translation_args(["Hello", "world"])
    assert direct == translate.TranslationRequest("en", "de", "Hello world")

    target_override = translate._parse_translation_args(["pl", "Good", "morning"])
    assert target_override == translate.TranslationRequest(
        "en",
        "pl",
        "Good morning",
    )

    explicit = translate._parse_translation_args(["auto", "uk", "Hello"])
    assert explicit == translate.TranslationRequest("auto", "uk", "Hello")


def test_parse_translation_args_auto_detects_when_shorthand_would_be_noop(
    monkeypatch,
):
    monkeypatch.setattr(translate, "TRANSLATE_FROM", "en")
    monkeypatch.setattr(translate, "TRANSLATE_TO", "en")

    reply = translate._parse_translation_args([])
    direct = translate._parse_translation_args(["Hausaufgaben"])
    target_override = translate._parse_translation_args(["en", "Blume"])
    explicit = translate._parse_translation_args(["en", "en", "flower"])

    assert reply == translate.TranslationRequest("auto", "en", "")
    assert direct == translate.TranslationRequest("auto", "en", "Hausaufgaben")
    assert target_override == translate.TranslationRequest("auto", "en", "Blume")
    assert explicit == translate.TranslationRequest("en", "en", "flower")


def test_parse_translation_args_treats_auto_as_text_with_configured_target(
    monkeypatch,
):
    monkeypatch.setattr(translate, "TRANSLATE_FROM", "en")
    monkeypatch.setattr(translate, "TRANSLATE_TO", "de")

    single_word = translate._parse_translation_args(["auto"])
    phrase = translate._parse_translation_args(["auto", "repair", "shop"])
    explicit_languages = translate._parse_translation_args(["auto", "de"])

    assert single_word == translate.TranslationRequest("en", "de", "auto")
    assert phrase == translate.TranslationRequest("en", "de", "auto repair shop")
    assert explicit_languages == translate.TranslationRequest("auto", "de", "")


def test_parse_translation_args_validates_configured_defaults(monkeypatch):
    monkeypatch.setattr(translate, "TRANSLATE_TO", "none")
    with pytest.raises(translate.TranslationUsageError, match="Missing target"):
        translate._parse_translation_args([])

    monkeypatch.setattr(translate, "TRANSLATE_FROM", "invalid-source")
    with pytest.raises(translate.TranslationUsageError, match="Configured source"):
        translate._parse_translation_args(["de", "Hello"])

    monkeypatch.setattr(translate, "TRANSLATE_FROM", "auto")
    monkeypatch.setattr(translate, "TRANSLATE_TO", "invalid-target")
    with pytest.raises(translate.TranslationUsageError, match="Configured target"):
        translate._parse_translation_args([])


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


def test_auto_detection_noop_response_recommends_explicit_source():
    request = translate.TranslationRequest("auto", "en", "Blume")
    result = translate.TranslationResult("Blume", "en")

    direct = translate._format_translation_response(
        "Blume", request, result, is_room=False
    )
    room = translate._format_translation_response(
        "Blume", request, result, is_room=True
    )

    assert "Auto-detection returned the text unchanged" in direct
    assert "detected: en" in direct
    assert ",tr de en <text>" in direct
    assert room == f"> Blume\n\n{direct}"


def test_explicit_source_keeps_unchanged_provider_response():
    request = translate.TranslationRequest("de", "en", "Blume")
    result = translate.TranslationResult("Blume", "de")

    assert translate._format_translation_response(
        "Blume", request, result, is_room=False
    ) == "Blume"




@pytest.mark.asyncio
async def test_translate_request_failure_does_not_log_private_text(
    monkeypatch, caplog
):
    secret = "private-homework-secret"
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(f",tr de {secret}", room="alice@example.org", msg_type="chat")
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        translate,
        "translate_text",
        AsyncMock(side_effect=aiohttp.ClientError(f"https://provider/?q={secret}")),
    )

    with caplog.at_level("WARNING", logger=translate.__name__):
        await translate.translate_command(
            bot,
            "alice@example.org",
            None,
            ["de", secret],
            msg,
            False,
        )

    assert secret not in caplog.text
    assert "ClientError" in caplog.text
    bot.reply.assert_called_once_with(
        msg, "🔴 Translation service request failed.", mention=False
    )


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
async def test_translate_command_uses_defaults_for_direct_text(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(
        ",tr Hello, world!",
        room="alice@example.org",
        msg_type="chat",
    )
    monkeypatch.setattr(translate, "TRANSLATE_FROM", "en")
    monkeypatch.setattr(translate, "TRANSLATE_TO", "de")
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    worker = AsyncMock(
        return_value=translate.TranslationResult("Hallo Welt!", "en")
    )
    monkeypatch.setattr(translate, "translate_text", worker)

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["Hello,", "world!"],
        msg,
        False,
    )

    worker.assert_awaited_once_with(
        "Hello, world!",
        target_language="de",
        source_language="en",
    )
    bot.reply.assert_called_once_with(msg, "Hallo Welt!", mention=False)


@pytest.mark.asyncio
async def test_translate_command_treats_auto_as_text_with_default_target(
    monkeypatch,
):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(
        ",tr auto",
        room="alice@example.org",
        msg_type="chat",
    )
    monkeypatch.setattr(translate, "TRANSLATE_FROM", "en")
    monkeypatch.setattr(translate, "TRANSLATE_TO", "de")
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    worker = AsyncMock(return_value=translate.TranslationResult("Auto", "en"))
    monkeypatch.setattr(translate, "translate_text", worker)

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["auto"],
        msg,
        False,
    )

    worker.assert_awaited_once_with(
        "auto",
        target_language="de",
        source_language="en",
    )
    bot.reply.assert_called_once_with(msg, "Auto", mention=False)




@pytest.mark.asyncio
async def test_translate_command_translates_direct_text_in_muc_pm(monkeypatch):
    room = "room@conference.example.org"
    bot = _bot_with_cache(room=room)
    msg = make_message(
        ",tr de Hello from a MUC PM",
        room=room,
        msg_type="chat",
    )
    monkeypatch.setattr(_core, "_is_muc_pm", lambda _msg: True)
    monkeypatch.setattr(
        _core, "handle_room_toggle_command", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    worker = AsyncMock(return_value=translate.TranslationResult("Hallo aus einer MUC-PM", "en"))
    monkeypatch.setattr(translate, "translate_text", worker)

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["de", "Hello", "from", "a", "MUC", "PM"],
        msg,
        False,
    )

    worker.assert_awaited_once_with(
        "Hello from a MUC PM",
        target_language="de",
        source_language="auto",
    )
    bot.reply.assert_called_once_with(
        msg,
        "Hallo aus einer MUC-PM",
        mention=False,
    )


@pytest.mark.asyncio
async def test_translate_command_quotes_original_text_in_room(monkeypatch):
    bot = _bot_with_cache()
    msg = make_message(",tr de hello world")
    monkeypatch.setattr(
        _core, "handle_room_toggle_command", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    worker = AsyncMock(return_value=translate.TranslationResult("Hallo Welt", "en"))
    monkeypatch.setattr(translate, "translate_text", worker)

    await translate.translate_command(
        bot,
        "alice@example.org",
        "alice",
        ["de", "hello", "world"],
        msg,
        True,
    )

    bot.reply.assert_called_once_with(
        msg,
        "> hello world\n\nHallo Welt",
        mention=False,
    )


@pytest.mark.asyncio
async def test_translate_command_uses_cached_reply_target(monkeypatch):
    room = "room@conference.example.org"
    bot = _bot_with_cache(room=room)
    msg = make_message(",tr uk", room=room, reply_id="original")
    await bot.message_cache.add_entry(
        {
            "conversation": room,
            "nick": "bob",
            "body": "Hello from the cache",
            "stanza_id": "original",
        }
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
    bot.reply.assert_called_once_with(
        msg,
        "> Hello from the cache\n\nПривіт із кешу",
        mention=False,
    )


@pytest.mark.asyncio
async def test_translate_command_uses_default_target_for_reply(monkeypatch):
    room = "room@conference.example.org"
    bot = _bot_with_cache(room=room)
    msg = make_message(",tr", room=room, reply_id="original-default")
    await bot.message_cache.add_entry(
        {
            "conversation": room,
            "nick": "bob",
            "body": "Hello with defaults",
            "stanza_id": "original-default",
        }
    )
    monkeypatch.setattr(translate, "TRANSLATE_TO", "de")
    monkeypatch.setattr(
        _core, "handle_room_toggle_command", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    worker = AsyncMock(
        return_value=translate.TranslationResult("Hallo mit Defaults", "en")
    )
    monkeypatch.setattr(translate, "translate_text", worker)

    await translate.translate_command(
        bot,
        "alice@example.org",
        "alice",
        [],
        msg,
        True,
    )

    worker.assert_awaited_once_with(
        "Hello with defaults",
        target_language="de",
        source_language="auto",
    )
    bot.reply.assert_called_once_with(
        msg,
        "> Hello with defaults\n\nHallo mit Defaults",
        mention=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sender", "joined_room", "conversation"),
    [
        ("alice@example.org", "room@conference.example.org", "alice@example.org"),
        (
            "room@conference.example.org",
            "room@conference.example.org",
            "mucpm:room@conference.example.org/alice",
        ),
    ],
    ids=["direct-message", "muc-pm"],
)
async def test_translate_command_uses_cached_reply_in_private_contexts(
    monkeypatch,
    sender,
    joined_room,
    conversation,
):
    bot = _bot_with_cache(room=joined_room)
    msg = make_message(
        ",tr de",
        room=sender,
        msg_type="chat",
        reply_id="private-original",
    )
    await bot.message_cache.add_entry(
        {
            "conversation": conversation,
            "nick": "alice",
            "body": "Hello from a private reply",
            "stanza_id": "private-original",
        }
    )
    monkeypatch.setattr(
        _core,
        "_is_muc_pm",
        lambda _msg: sender == "room@conference.example.org",
    )
    monkeypatch.setattr(
        _core, "handle_room_toggle_command", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    worker = AsyncMock(return_value=translate.TranslationResult("Hallo privat", "en"))
    monkeypatch.setattr(translate, "translate_text", worker)

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["de"],
        msg,
        False,
    )

    worker.assert_awaited_once_with(
        "Hello from a private reply",
        target_language="de",
        source_language="auto",
    )
    bot.reply.assert_called_once_with(msg, "Hallo privat", mention=False)


@pytest.mark.asyncio
async def test_translate_command_uses_xep0461_quote_fallback(monkeypatch):
    bot = _bot_with_cache()
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
    bot.reply.assert_called_once_with(
        msg,
        "> Hello from fallback\n\nHallo aus dem Fallback",
        mention=False,
    )


@pytest.mark.asyncio
async def test_translate_command_reports_missing_reply_text(monkeypatch):
    bot = _bot_with_cache()
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
async def test_room_translation_uses_effective_default(monkeypatch):
    bot = SimpleNamespace()
    msg = make_message(",tr de hello")
    feature = SimpleNamespace(enabled=True, default=True, modified=False)
    get_feature = AsyncMock(return_value=feature)
    monkeypatch.setattr(translate, "get_room_feature", get_feature)

    assert await translate._room_translation_enabled(bot, msg, True) is True
    get_feature.assert_awaited_once_with(
        bot,
        "room@conference.example.org",
        "translate",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("subcmd", "current", "expected_override", "expected_text"),
    [
        ("status", True, None, "enabled"),
        ("status", False, None, "disabled"),
        ("on", True, None, "already enabled"),
        ("off", False, None, "already disabled"),
        ("on", False, True, "enabled"),
        ("off", True, False, "disabled"),
    ],
)
async def test_translate_room_controls_use_effective_state(
    monkeypatch,
    subcmd,
    current,
    expected_override,
    expected_text,
):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(f",translate {subcmd}")
    monkeypatch.setattr(
        _core,
        "muc_pm_sender_can_manage_room",
        AsyncMock(
            return_value=(True, "room@conference.example.org", None)
        ),
    )
    monkeypatch.setattr(
        _core,
        "get_room_feature",
        AsyncMock(
            return_value=SimpleNamespace(
                enabled=current,
                default=True,
                modified=False,
            )
        ),
    )
    set_feature = AsyncMock()
    monkeypatch.setattr(_core, "set_room_feature", set_feature)

    handled = await translate._handle_room_toggle_command(
        bot,
        msg,
        True,
        [subcmd],
    )

    assert handled is True
    if expected_override is None:
        set_feature.assert_not_awaited()
    else:
        set_feature.assert_awaited_once_with(
            bot,
            "room@conference.example.org",
            "translate",
            expected_override,
        )
    assert expected_text in bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_translate_room_control_rejects_unauthorized_sender(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(",translate off")
    monkeypatch.setattr(
        _core,
        "muc_pm_sender_can_manage_room",
        AsyncMock(return_value=(False, "room@conference.example.org", "denied")),
    )
    get_feature = AsyncMock()
    set_feature = AsyncMock()
    monkeypatch.setattr(_core, "get_room_feature", get_feature)
    monkeypatch.setattr(_core, "set_room_feature", set_feature)

    handled = await translate._handle_room_toggle_command(
        bot,
        msg,
        True,
        ["off"],
    )

    assert handled is True
    get_feature.assert_not_awaited()
    set_feature.assert_not_awaited()
    bot.reply.assert_called_once_with(msg, "denied")


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
async def test_groupchat_handler_ignores_regular_messages():
    room = "room@conference.example.org"
    bot = _bot_with_cache(room=room)
    msg = make_message("A message to translate later", room=room, stanza_id="source-1")

    await translate._on_groupchat_message(bot, msg)

    bot.handle_command.assert_not_awaited()
    assert bot.message_cache.get_messages(room) == []


@pytest.mark.asyncio
async def test_groupchat_handler_redispatches_quote_fallback_command(monkeypatch):
    room = "room@conference.example.org"
    bot = _bot_with_cache(room=room)
    msg = make_message("> Original text\n,tr uk", room=room, stanza_id="reply-command")

    await translate._on_groupchat_message(bot, msg)

    bot.handle_command.assert_awaited_once_with(
        ",tr uk",
        msg["from"],
        "alice",
        msg,
        True,
    )
    assert bot.message_cache.get_messages(room) == []


@pytest.mark.asyncio
async def test_groupchat_handler_skips_own_and_non_commands():
    room = "room@conference.example.org"
    bot = _bot_with_cache(room=room)

    await translate._on_groupchat_message(
        bot,
        make_message("bot output", room=room, nick="EnvsBot", stanza_id="own"),
    )
    await translate._on_groupchat_message(
        bot,
        make_message("user output", room=room, nick="alice", stanza_id="regular"),
    )

    bot.handle_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "room",
    ["alice@example.org", "room@conference.example.org"],
    ids=["direct-message", "muc-pm"],
)
async def test_private_handler_redispatches_quote_fallback_command(room):
    bot = _bot_with_cache(room="room@conference.example.org")
    msg = make_message(
        "> Original private text\n,tr de",
        room=room,
        msg_type="chat",
        stanza_id=f"private-reply-{room}",
    )

    await translate._on_private_message(bot, msg)

    bot.handle_command.assert_awaited_once_with(
        ",tr de",
        msg["from"],
        None,
        msg,
        False,
    )


@pytest.mark.asyncio
async def test_private_handler_ignores_non_private_messages_and_non_commands():
    bot = _bot_with_cache()

    await translate._on_private_message(
        bot,
        make_message(
            "> Original\n,tr de",
            msg_type="groupchat",
            stanza_id="not-private",
        ),
    )
    await translate._on_private_message(
        bot,
        make_message(
            "> Original\nregular text",
            room="alice@example.org",
            msg_type="chat",
            stanza_id="not-command",
        ),
    )

    bot.handle_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_doctor_and_on_load(monkeypatch):
    register_event = Mock()
    bot = SimpleNamespace(bot_plugins=SimpleNamespace(register_event=register_event))

    await translate.on_load(bot)
    assert [call.args[:2] for call in register_event.call_args_list] == [
        ("translate", "groupchat_message"),
        ("translate", "message"),
    ]

    global_lines = await translate.doctor(bot)
    assert global_lines[0].startswith("✅ Translate:")
    assert "default_from=auto" in global_lines[0]
    assert "default_to=none" in global_lines[0]

    monkeypatch.setattr(translate, "TRANSLATE_TO", "invalid-target")
    assert (await translate.doctor(bot))[0].startswith(
        "❌ Translate: invalid defaults:"
    )

    monkeypatch.setattr(translate, "TRANSLATE_TO", None)
    monkeypatch.setattr(
        translate,
        "get_room_feature",
        AsyncMock(return_value=SimpleNamespace(enabled=True)),
    )
    room_lines = await translate.doctor(bot, "room@conference.example.org")
    assert "enabled" in room_lines[0]
    assert "default_from=auto" in room_lines[0]
    assert "default_to=none" in room_lines[0]


@pytest.mark.asyncio
async def test_get_translate_store_uses_exact_plugin_namespace():
    store = object()
    plugin = Mock(return_value=store)
    bot = SimpleNamespace(
        db=SimpleNamespace(users=SimpleNamespace(plugin=plugin)),
    )

    assert await translate.get_translate_store(bot) is store
    plugin.assert_called_once_with("translate")
