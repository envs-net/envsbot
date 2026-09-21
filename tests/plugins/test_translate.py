from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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
    monkeypatch.setattr(translate, "TRANSLATE_LIBRETRANSLATE_URL", "")
    monkeypatch.setattr(translate, "TRANSLATE_LIBRETRANSLATE_API_KEY", "")
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "")
    monkeypatch.setattr(translate, "TRANSLATE_DEEPL_API_KEY", "")
    monkeypatch.setattr(translate, "TRANSLATE_PROVIDER_QUEUE_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(translate, "TRANSLATE_RATE_LIMIT_INITIAL_SECONDS", 60.0)
    monkeypatch.setattr(translate, "TRANSLATE_RATE_LIMIT_MAX_SECONDS", 900.0)
    monkeypatch.setattr(translate, "TRANSLATE_RATE_LIMIT_BACKOFF_MULTIPLIER", 2.0)
    translate._reset_rate_limit_state()
    translate._reset_capability_state()
    translate._CAPABILITY_REFRESH_TASK = None
    translate._PROVIDER_LOCKS.clear()
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
async def test_translate_text_uses_google_cloud_provider(monkeypatch):
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    google = AsyncMock(
        return_value=translate.ProviderTranslation("Привіт, світе!", "en")
    )
    monkeypatch.setattr(translate, "translate_google_cloud", google)

    result = await translate.translate_text(
        "Hello, world!",
        source_language="en",
        target_language="uk",
    )

    assert result == translate.TranslationResult("Привіт, світе!", "en")
    google.assert_awaited_once_with(
        "Hello, world!",
        source_language="en",
        target_language="uk",
        api_key="google-key",
        timeout_seconds=translate.TRANSLATE_TIMEOUT_SECONDS,
        max_bytes=translate.TRANSLATE_MAX_RESPONSE_BYTES,
    )


def test_retry_after_parses_seconds_and_http_date():
    now = translate.datetime(2026, 8, 26, 20, 0, tzinfo=translate.UTC)

    assert translate._retry_after_seconds({"Retry-After": "75"}, now=now) == 75
    assert translate._retry_after_seconds(
        {"Retry-After": "Wed, 26 Aug 2026 20:02:00 GMT"},
        now=now,
    ) == 120
    assert translate._retry_after_seconds({"Retry-After": "invalid"}, now=now) is None


def _rate_limit_error(*, retry_after: str | None = None):
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return translate.ProviderHTTPError("google", 429, headers=headers)


@pytest.mark.asyncio
async def test_translate_text_429_honors_retry_after_and_suppresses_requests(
    monkeypatch, caplog
):
    now = 1000.0
    monkeypatch.setattr(translate, "_monotonic", lambda: now)
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    google = AsyncMock(side_effect=_rate_limit_error(retry_after="120"))
    monkeypatch.setattr(translate, "translate_google_cloud", google)

    with caplog.at_level("WARNING", logger=translate.__name__):
        with pytest.raises(translate.TranslationRateLimitError) as exc_info:
            await translate.translate_text("Hello", target_language="de")

    assert exc_info.value.retry_after_seconds == 120
    assert translate._rate_limit_remaining("google-api") == 120
    assert "status=429" in caplog.text
    assert "cooldown_seconds=120.0" in caplog.text
    assert "retry_after_seconds=120.0" in caplog.text

    with pytest.raises(translate.TranslationRateLimitError) as cooldown:
        await translate.translate_text("Second request", target_language="de")

    assert cooldown.value.retry_after_seconds == 120
    assert google.await_count == 1


@pytest.mark.asyncio
async def test_translate_rate_limit_backoff_grows_and_success_resets(monkeypatch):
    now = 2000.0
    monkeypatch.setattr(translate, "_monotonic", lambda: now)
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    google = AsyncMock(side_effect=_rate_limit_error())
    monkeypatch.setattr(translate, "translate_google_cloud", google)

    with pytest.raises(translate.TranslationRateLimitError) as first:
        await translate.translate_text("one", target_language="de")
    assert first.value.retry_after_seconds == 60

    now += 61
    with pytest.raises(translate.TranslationRateLimitError) as second:
        await translate.translate_text("two", target_language="de")
    assert second.value.retry_after_seconds == 120

    now += 121
    google.side_effect = None
    google.return_value = translate.ProviderTranslation("Hallo", "en")
    result = await translate.translate_text("Hello", target_language="de")

    assert result.text == "Hallo"
    assert translate._rate_limit_remaining("google-api") == 0
    assert translate._RATE_LIMIT_STATE.backoff_seconds == 0
    assert translate._RATE_LIMIT_STATE.total_429_count == 2
    assert translate._RATE_LIMIT_STATE.streak_429_count == 0
    assert translate._RATE_LIMIT_STATE.last_429_monotonic is not None

    google.side_effect = _rate_limit_error()
    now += 1
    with pytest.raises(translate.TranslationRateLimitError) as after_success:
        await translate.translate_text("again", target_language="de")
    assert after_success.value.retry_after_seconds == 60
    assert translate._RATE_LIMIT_STATE.total_429_count == 3
    assert translate._RATE_LIMIT_STATE.streak_429_count == 1


@pytest.mark.asyncio
async def test_translate_rate_limit_backoff_is_capped(monkeypatch):
    now = 3000.0
    monkeypatch.setattr(translate, "_monotonic", lambda: now)
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    monkeypatch.setattr(translate, "TRANSLATE_RATE_LIMIT_INITIAL_SECONDS", 60.0)
    monkeypatch.setattr(translate, "TRANSLATE_RATE_LIMIT_MAX_SECONDS", 90.0)
    monkeypatch.setattr(translate, "TRANSLATE_RATE_LIMIT_BACKOFF_MULTIPLIER", 2.0)
    google = AsyncMock(side_effect=_rate_limit_error(retry_after="600"))
    monkeypatch.setattr(translate, "translate_google_cloud", google)

    with pytest.raises(translate.TranslationRateLimitError) as exc_info:
        await translate.translate_text("Hello", target_language="de")

    assert exc_info.value.retry_after_seconds == 90
    assert translate._RATE_LIMIT_STATE.backoff_seconds == 90


@pytest.mark.asyncio
async def test_concurrent_translation_waiter_is_stopped_after_first_429(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")

    async def google_cloud(text, **kwargs):
        nonlocal calls
        del text, kwargs
        calls += 1
        started.set()
        await release.wait()
        raise _rate_limit_error()

    monkeypatch.setattr(translate, "translate_google_cloud", google_cloud)
    first = asyncio.create_task(
        translate.translate_text("one", target_language="de")
    )
    await started.wait()
    second = asyncio.create_task(
        translate.translate_text("two", target_language="de")
    )
    await asyncio.sleep(0)
    release.set()

    results = await asyncio.gather(first, second, return_exceptions=True)

    assert calls == 1
    assert all(isinstance(item, translate.TranslationRateLimitError) for item in results)


@pytest.mark.asyncio
async def test_translate_provider_queue_wait_is_bounded(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    monkeypatch.setattr(translate, "TRANSLATE_PROVIDER_QUEUE_TIMEOUT_SECONDS", 0.01)

    async def google_cloud(text, **kwargs):
        nonlocal calls
        del text, kwargs
        calls += 1
        started.set()
        await release.wait()
        return translate.ProviderTranslation("Hallo", "en")

    monkeypatch.setattr(translate, "translate_google_cloud", google_cloud)
    first = asyncio.create_task(
        translate.translate_text("one", target_language="de")
    )
    await started.wait()

    with pytest.raises(translate.TranslationProviderBusyError):
        await translate.translate_text("two", target_language="de")

    assert calls == 1
    release.set()
    assert (await first).text == "Hallo"


@pytest.mark.asyncio
async def test_translate_text_rejects_long_input(monkeypatch):
    monkeypatch.setattr(translate, "TRANSLATE_MAX_INPUT_LENGTH", 4)
    with pytest.raises(translate.TranslationUsageError, match="too long"):
        await translate.translate_text(
            "12345",
            source_language="auto",
            target_language="de",
        )


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
async def test_translate_command_reports_rate_limit_without_generic_failure(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(",tr de hello", room="alice@example.org", msg_type="chat")
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        translate,
        "translate_text",
        AsyncMock(side_effect=translate.TranslationRateLimitError(75)),
    )

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["de", "hello"],
        msg,
        False,
    )

    output = bot.reply.call_args.args[1]
    assert "temporarily rate-limited" in output
    assert "1m 15s" in output
    assert "request failed" not in output


@pytest.mark.asyncio
async def test_translate_command_reports_language_pair_unavailable(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(
        ",tr de la Feuerwehrmann",
        room="alice@example.org",
        msg_type="chat",
    )
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        translate,
        "translate_text",
        AsyncMock(
            side_effect=translate.TranslationLanguagePairUnavailableError(
                "de",
                "la",
                fallback_temporarily_unavailable=True,
            )
        ),
    )

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["de", "la", "Feuerwehrmann"],
        msg,
        False,
    )

    output = bot.reply.call_args.args[1]
    assert "de → la" in output
    assert "not supported" in output
    assert "fallback provider is temporarily unavailable" in output
    assert "No translation provider" not in output


@pytest.mark.asyncio
async def test_translate_command_reports_busy_provider_queue(monkeypatch):
    bot = SimpleNamespace(reply=Mock())
    msg = make_message(",tr de hello", room="alice@example.org", msg_type="chat")
    monkeypatch.setattr(
        translate, "_room_translation_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        translate,
        "translate_text",
        AsyncMock(side_effect=translate.TranslationProviderBusyError()),
    )

    await translate.translate_command(
        bot,
        "alice@example.org",
        None,
        ["de", "hello"],
        msg,
        False,
    )

    output = bot.reply.call_args.args[1]
    assert "Translation service is busy" in output
    assert "request failed" not in output


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
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    register_event = Mock()
    task = Mock()
    task.done.return_value = True
    create_resilient = Mock(return_value=task)
    monkeypatch.setattr(translate, "create_resilient_plugin_task", create_resilient)
    bot = SimpleNamespace(bot_plugins=SimpleNamespace(register_event=register_event))

    await translate.on_load(bot)
    assert [call.args[:2] for call in register_event.call_args_list] == [
        ("translate", "groupchat_message"),
        ("translate", "message"),
    ]
    create_resilient.assert_called_once()
    assert create_resilient.call_args.kwargs["name"] == "translate-capabilities"

    global_lines = await translate.doctor(bot)
    assert global_lines[0].startswith("✅ Translate:")
    assert "default_from=auto" in global_lines[0]
    assert "default_to=none" in global_lines[0]
    assert "queue_wait=5s" in global_lines[0]
    assert "rate_limit=ready" in global_lines[0]
    assert "providers=libretranslate(public)" in global_lines[0]
    assert "429_history=none" in global_lines[0]

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
    assert "queue_wait=5s" in room_lines[0]

    now = translate._monotonic()
    libre_state = translate._rate_limit_state("libretranslate-public")
    monkeypatch.setattr(libre_state, "until_monotonic", now + 30)
    monkeypatch.setattr(libre_state, "total_429_count", 3)
    monkeypatch.setattr(libre_state, "streak_429_count", 2)
    monkeypatch.setattr(libre_state, "last_429_monotonic", now - 15)
    cooldown_lines = await translate.doctor(bot)
    assert cooldown_lines[0].startswith("⚠️ Translate:")
    assert "rate_limit=cooldown" in cooldown_lines[0]
    assert "libretranslate(public):30s" in cooldown_lines[0]
    assert "libretranslate(public):3@15s/streak=2" in cooldown_lines[0]


@pytest.mark.asyncio
async def test_get_translate_store_uses_exact_plugin_namespace():
    store = object()
    plugin = Mock(return_value=store)
    bot = SimpleNamespace(
        db=SimpleNamespace(users=SimpleNamespace(plugin=plugin)),
    )

    assert await translate.get_translate_store(bot) is store
    plugin.assert_called_once_with("translate")


def test_provider_chain_defaults_to_libretranslate_only(monkeypatch):
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )

    chain = translate._provider_chain()

    assert [(item.name, item.state_key, item.authenticated) for item in chain] == [
        ("libretranslate", "libretranslate-public", False),
    ]


def test_provider_chain_prefers_configured_api_keys_in_requested_order(monkeypatch):
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(translate, "TRANSLATE_LIBRETRANSLATE_API_KEY", "libre-key")
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    monkeypatch.setattr(translate, "TRANSLATE_DEEPL_API_KEY", "deepl-key")

    chain = translate._provider_chain()

    assert [(item.name, item.state_key, item.authenticated) for item in chain] == [
        ("libretranslate", "libretranslate-api", True),
        ("google", "google-api", True),
        ("deepl", "deepl-api", True),
    ]


def test_provider_chain_puts_single_keyed_provider_before_libretranslate_fallback(monkeypatch):
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(translate, "TRANSLATE_DEEPL_API_KEY", "deepl-key")

    chain = translate._provider_chain()

    assert [(item.name, item.state_key, item.authenticated) for item in chain] == [
        ("deepl", "deepl-api", True),
        ("libretranslate", "libretranslate-public", False),
    ]


@pytest.mark.asyncio
async def test_translate_falls_back_from_rate_limited_libretranslate_to_google_cloud(
    monkeypatch,
):
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(translate, "TRANSLATE_LIBRETRANSLATE_API_KEY", "libre-key")
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    libre = AsyncMock(
        side_effect=translate.ProviderHTTPError(
            "libretranslate",
            429,
            headers={"Retry-After": "120"},
        )
    )
    google = AsyncMock(
        return_value=translate.ProviderTranslation("Hallo Welt", "en")
    )
    monkeypatch.setattr(translate, "translate_libretranslate", libre)
    monkeypatch.setattr(translate, "translate_google_cloud", google)

    result = await translate.translate_text(
        "Hello world",
        source_language="auto",
        target_language="de",
    )

    assert result == translate.TranslationResult("Hallo Welt", "en")
    libre.assert_awaited_once()
    google.assert_awaited_once()
    assert translate._rate_limit_remaining("libretranslate-api") > 0
    assert translate._rate_limit_remaining("google-api") == 0


@pytest.mark.asyncio
async def test_translate_falls_back_after_authenticated_provider_failure(monkeypatch):
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    google_api = AsyncMock(
        side_effect=translate.ProviderHTTPError("google", 403)
    )
    libre = AsyncMock(
        return_value=translate.ProviderTranslation("Hallo", "en")
    )
    monkeypatch.setattr(translate, "translate_google_cloud", google_api)
    monkeypatch.setattr(translate, "translate_libretranslate", libre)

    result = await translate.translate_text(
        "Hello",
        source_language="en",
        target_language="de",
    )

    assert result.text == "Hallo"
    google_api.assert_awaited_once()
    libre.assert_awaited_once()


@pytest.mark.asyncio
async def test_translate_falls_back_after_language_pair_rejection(monkeypatch):
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(translate, "TRANSLATE_LIBRETRANSLATE_API_KEY", "libre-key")
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    libre = AsyncMock(
        side_effect=translate.ProviderHTTPError("libretranslate", 400)
    )
    google = AsyncMock(
        return_value=translate.ProviderTranslation("Vigil ignis", "de")
    )
    monkeypatch.setattr(translate, "translate_libretranslate", libre)
    monkeypatch.setattr(translate, "translate_google_cloud", google)

    result = await translate.translate_text(
        "Feuerwehrmann",
        source_language="de",
        target_language="la",
    )

    assert result == translate.TranslationResult("Vigil ignis", "de")
    libre.assert_awaited_once()
    google.assert_awaited_once()


@pytest.mark.asyncio
async def test_translate_reports_language_pair_when_google_cloud_fallback_is_rate_limited(
    monkeypatch,
):
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(translate, "TRANSLATE_LIBRETRANSLATE_API_KEY", "libre-key")
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    monkeypatch.setattr(
        translate,
        "translate_libretranslate",
        AsyncMock(side_effect=translate.ProviderHTTPError("libretranslate", 400)),
    )
    monkeypatch.setattr(
        translate,
        "translate_google_cloud",
        AsyncMock(
            side_effect=translate.ProviderHTTPError(
                "google",
                429,
                headers={"Retry-After": "60"},
            )
        ),
    )

    with pytest.raises(
        translate.TranslationLanguagePairUnavailableError
    ) as exc_info:
        await translate.translate_text(
            "Feuerwehrmann",
            source_language="de",
            target_language="la",
        )

    exc = exc_info.value
    assert exc.source_language == "de"
    assert exc.target_language == "la"
    assert exc.fallback_temporarily_unavailable is True


@pytest.mark.asyncio
async def test_translate_reports_unavailable_after_all_provider_failures(monkeypatch):
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(translate, "TRANSLATE_LIBRETRANSLATE_API_KEY", "libre-key")
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    monkeypatch.setattr(
        translate,
        "translate_libretranslate",
        AsyncMock(side_effect=translate.ProviderHTTPError("libretranslate", 503)),
    )
    monkeypatch.setattr(
        translate,
        "translate_google_cloud",
        AsyncMock(side_effect=translate.ProviderHTTPError("google", 503)),
    )

    with pytest.raises(translate.TranslationProvidersUnavailableError):
        await translate.translate_text(
            "Hello",
            source_language="en",
            target_language="de",
        )


@pytest.mark.asyncio
async def test_doctor_reports_multi_provider_chain_without_exposing_keys(monkeypatch):
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_API_KEY",
        "secret-libre",
    )
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "secret-google")
    monkeypatch.setattr(translate, "TRANSLATE_DEEPL_API_KEY", "secret-deepl")
    bot = SimpleNamespace()

    line = (await translate.doctor(bot))[0]

    assert (
        "providers=libretranslate(api-key) -> google(api-key) -> deepl(api-key)"
        in line
    )
    assert "secret-libre" not in line
    assert "secret-google" not in line
    assert "secret-deepl" not in line


def test_capability_support_is_conservative_for_language_variants():
    capabilities = translate.ProviderCapabilities(
        source_languages=frozenset({"en", "de"}),
        target_languages=frozenset({"de", "en-gb", "en-us"}),
    )

    assert translate._capability_supports_pair(capabilities, "de", "de") is True
    assert translate._capability_supports_pair(capabilities, "auto", "de") is True
    assert translate._capability_supports_pair(capabilities, "de", "fr") is False
    assert translate._capability_supports_pair(capabilities, "de", "en") is None


def test_libretranslate_capabilities_use_exact_advertised_pairs():
    capabilities = translate.ProviderCapabilities(
        source_languages=frozenset({"de", "en"}),
        target_languages=frozenset({"de", "en", "fr"}),
        translation_pairs=frozenset({("de", "en"), ("en", "de")}),
    )

    assert translate._capability_supports_pair(capabilities, "de", "en") is True
    assert translate._capability_supports_pair(capabilities, "de", "fr") is False


@pytest.mark.asyncio
async def test_fresh_capabilities_skip_unsupported_provider_before_translation(
    monkeypatch,
):
    now = 5000.0
    monkeypatch.setattr(translate, "_monotonic", lambda: now)
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(translate, "TRANSLATE_LIBRETRANSLATE_API_KEY", "libre-key")
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")

    libre_attempt, google_attempt = translate._provider_chain()
    libre_state = translate._capability_state(libre_attempt.state_key)
    libre_state.capabilities = translate.ProviderCapabilities(
        source_languages=frozenset({"de", "en"}),
        target_languages=frozenset({"de", "en"}),
        translation_pairs=frozenset({("de", "en"), ("en", "de")}),
    )
    libre_state.fetched_at_monotonic = now
    google_state = translate._capability_state(google_attempt.state_key)
    google_state.capabilities = translate.ProviderCapabilities(
        source_languages=frozenset({"de", "en", "la"}),
        target_languages=frozenset({"de", "en", "la"}),
    )
    google_state.fetched_at_monotonic = now

    libre = AsyncMock(return_value=translate.ProviderTranslation("wrong", "de"))
    google = AsyncMock(return_value=translate.ProviderTranslation("Vigil ignis", "de"))
    monkeypatch.setattr(translate, "translate_libretranslate", libre)
    monkeypatch.setattr(translate, "translate_google_cloud", google)

    result = await translate.translate_text(
        "Feuerwehrmann",
        source_language="de",
        target_language="la",
    )

    assert result == translate.TranslationResult("Vigil ignis", "de")
    libre.assert_not_awaited()
    google.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_capabilities_do_not_block_provider_attempt(monkeypatch):
    now = 8000.0
    monkeypatch.setattr(translate, "_monotonic", lambda: now)
    monkeypatch.setattr(translate, "TRANSLATE_CAPABILITIES_REFRESH_SECONDS", 3600.0)
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    attempt = translate._provider_chain()[0]
    state = translate._capability_state(attempt.state_key)
    state.capabilities = translate.ProviderCapabilities(
        source_languages=frozenset({"de", "en"}),
        target_languages=frozenset({"de", "en"}),
        translation_pairs=frozenset({("de", "en"), ("en", "de")}),
    )
    state.fetched_at_monotonic = now - 3601

    libre = AsyncMock(return_value=translate.ProviderTranslation("Vigil ignis", "de"))
    monkeypatch.setattr(translate, "translate_libretranslate", libre)

    result = await translate.translate_text(
        "Feuerwehrmann",
        source_language="de",
        target_language="la",
    )

    assert result.text == "Vigil ignis"
    libre.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_fresh_capability_rejections_avoid_translation_requests(monkeypatch):
    now = 9000.0
    monkeypatch.setattr(translate, "_monotonic", lambda: now)
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")

    for attempt in translate._provider_chain():
        state = translate._capability_state(attempt.state_key)
        state.capabilities = translate.ProviderCapabilities(
            source_languages=frozenset({"de", "en"}),
            target_languages=frozenset({"de", "en"}),
        )
        state.fetched_at_monotonic = now

    libre = AsyncMock()
    google = AsyncMock()
    monkeypatch.setattr(translate, "translate_libretranslate", libre)
    monkeypatch.setattr(translate, "translate_google_cloud", google)

    with pytest.raises(translate.TranslationLanguagePairUnavailableError):
        await translate.translate_text(
            "Feuerwehrmann",
            source_language="de",
            target_language="la",
        )

    libre.assert_not_awaited()
    google.assert_not_awaited()


@pytest.mark.asyncio
async def test_capability_refresh_populates_cache_and_preserves_it_on_failure(
    monkeypatch,
):
    now = 10000.0
    monkeypatch.setattr(translate, "_monotonic", lambda: now)
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "google-key")
    attempt = translate._provider_chain()[0]
    capabilities = translate.ProviderCapabilities(
        source_languages=frozenset({"en", "de"}),
        target_languages=frozenset({"en", "de"}),
    )
    fetch = AsyncMock(return_value=capabilities)
    monkeypatch.setattr(translate, "_fetch_provider_capabilities", fetch)

    assert await translate._refresh_provider_capabilities(attempt) is True
    state = translate._capability_state(attempt.state_key)
    assert state.capabilities == capabilities
    assert state.fetched_at_monotonic == now
    assert state.last_error is None

    now += 10
    fetch.side_effect = translate.ProviderHTTPError("google", 503)
    assert await translate._refresh_provider_capabilities(attempt) is False
    assert state.capabilities == capabilities
    assert state.fetched_at_monotonic == 10000.0
    assert state.last_attempt_monotonic == now
    assert state.last_error == "ProviderHTTPError"


@pytest.mark.asyncio
async def test_doctor_reports_capability_cache_without_exposing_credentials(
    monkeypatch,
):
    now = 12000.0
    monkeypatch.setattr(translate, "_monotonic", lambda: now)
    monkeypatch.setattr(
        translate,
        "TRANSLATE_LIBRETRANSLATE_URL",
        "https://translate.envs.net/",
    )
    monkeypatch.setattr(translate, "TRANSLATE_GOOGLE_API_KEY", "secret-google")
    attempts = {item.name: item for item in translate._provider_chain()}

    libre_state = translate._capability_state(attempts["libretranslate"].state_key)
    libre_state.capabilities = translate.ProviderCapabilities(
        source_languages=frozenset({"de", "en", "fr"}),
        target_languages=frozenset({"de", "en", "fr"}),
    )
    libre_state.fetched_at_monotonic = now - 17 * 60

    google_state = translate._capability_state(attempts["google"].state_key)
    google_state.capabilities = translate.ProviderCapabilities(
        source_languages=frozenset({"de", "en", "fr", "la"}),
        target_languages=frozenset({"de", "en", "fr", "la"}),
    )
    google_state.fetched_at_monotonic = now - 30

    lines = await translate.doctor(SimpleNamespace())

    assert len(lines) == 2
    assert "libretranslate:3 languages/fresh 17m" in lines[1]
    assert "google:4 languages/fresh 30s" in lines[1]
    assert "deepl:not configured" in lines[1]
    assert "secret-google" not in "\n".join(lines)


@pytest.mark.asyncio
async def test_on_unload_cancels_capability_refresh_task():
    started = asyncio.Event()

    async def forever():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(forever())
    translate._CAPABILITY_REFRESH_TASK = task
    await started.wait()

    await translate.on_unload(SimpleNamespace())

    assert task.cancelled()
    assert translate._CAPABILITY_REFRESH_TASK is None
