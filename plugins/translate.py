"""Translate text or an XMPP reply using Google Translate's public endpoint.

Examples
--------
Explicit source and target language::

    {prefix}tr en uk Hello, world!

Automatic source-language detection::

    {prefix}tr uk Hallo Welt!
    {prefix}tr auto uk Hallo Welt!

Reply to a message in a room, MUC PM or direct chat and omit the text::

    {prefix}tr en uk
    {prefix}tr uk

The command behavior is inspired by ``maubot/translate`` while using the
existing envsbot XEP-0461 reply and stanza cache helpers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import partial
from typing import Any
from urllib.parse import urlencode

import aiohttp

from core_plugins import _core
from utils import message_cache
from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand, room_toggle_subcommands
from utils.config import config
from utils.http_fetch import fetch_json, passthrough_validator
from utils.room_features import get_room_feature
from utils.url_safety import FetchURLTooLarge, UnsafeFetchURL

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "translate",
    "version": "0.2.4",
    "description": (
        "Translate text or replied-to messages with optional "
        "source-language auto-detection."
    ),
    "category": "utility",
    "requires": ["rooms", "_core"],
}

FALLBACK_NAMESPACE = "translate-fallback-command"
TRANSLATE_KEY = "TRANSLATE"
GOOGLE_TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"

TRANSLATE_TIMEOUT_SECONDS = max(
    1.0,
    float(
        config.get("translate_timeout_seconds")
        or config.get("http_timeout_seconds")
        or 8
    ),
)
TRANSLATE_MAX_INPUT_LENGTH = max(
    1,
    int(config.get("translate_max_input_length", 2000) or 2000),
)
TRANSLATE_MAX_OUTPUT_LENGTH = max(
    1,
    int(config.get("translate_max_output_length", 6000) or 6000),
)
TRANSLATE_MAX_RESPONSE_BYTES = max(
    4096,
    int(config.get("translate_max_response_bytes", 262144) or 262144),
)
TRANSLATE_RATE_LIMIT_INITIAL_SECONDS = max(
    1.0,
    float(config.get("translate_rate_limit_initial_seconds", 60) or 60),
)
TRANSLATE_RATE_LIMIT_MAX_SECONDS = max(
    TRANSLATE_RATE_LIMIT_INITIAL_SECONDS,
    float(config.get("translate_rate_limit_max_seconds", 900) or 900),
)
TRANSLATE_RATE_LIMIT_BACKOFF_MULTIPLIER = max(
    1.0,
    float(config.get("translate_rate_limit_backoff_multiplier", 2.0) or 2.0),
)
TRANSLATE_FROM = str(config.get("translate_from", "auto") or "auto")
_configured_translate_to = config.get("translate_to")
TRANSLATE_TO = (
    None
    if _configured_translate_to is None
    else str(_configured_translate_to)
)
del _configured_translate_to
# Google Cloud's NMT language-code list is intentionally kept as codes rather
# than display names. Regional/script variants are normalized case-insensitively.
# ``auto`` is valid only for the source language.
SUPPORTED_LANGUAGE_CODES = frozenset("""
    ab ace ach af ak alz am ar ar-sa as awa ay az ba
    ban bbc be bem bew bg bho bik bm bn bn-in br bs bs-cyrl
    bts btx bua ca ceb cgg chm ckb cnh co crh crs cs cv
    cy da de din doi dov dv dz ee el en en-au en-ca en-gb
    en-nz en-ph en-us en-za eo es es-419 es-ar es-cl es-co es-cr es-ec es-es es-gt
    es-hn es-ht es-mx es-ni es-pa es-pe es-pr es-py es-sv es-us es-uy es-ve et eu
    fa ff fi fil fj fr fr-ca fr-ch fr-fr fy ga gaa gd gl
    gn gom gu ha haw he hi hil hmn hr hrx ht hu hy
    id ig ilo is it iw ja jv jw ka kk km kn ko
    kri ktu ku ky la lb lg li lij lmo ln lo lt ltg
    luo lus lv mai mak mg mi min mk ml mn mni-mtei mr ms
    ms-arab mt my ne new nl nl-be no nr nso nus ny oc om
    or pa pa-arab pa-pk pag pam pap pl ps pt pt-br pt-pt qu rn
    ro rom ru rw sa scn sd sg shn si sk sl sm sn
    so sq sr ss st su sv sw szl ta te tet tg th
    ti tk tl tn tr ts tt ug uk ur uz vi xh yi
    yo yua yue zh zh-cn zh-hans zh-hant zh-hk zh-tw zu
    """.split())


@dataclass(frozen=True)
class TranslationRequest:
    """Parsed command request."""

    source_language: str
    target_language: str
    text: str


@dataclass(frozen=True)
class TranslationResult:
    """Normalized provider response."""

    text: str
    source_language: str | None = None


class TranslationUsageError(ValueError):
    """Raised for invalid command arguments."""


class TranslationProviderError(RuntimeError):
    """Raised when the remote translation provider returns unusable data."""


class TranslationRateLimitError(RuntimeError):
    """Raised when the provider is in a local or upstream rate-limit cooldown."""

    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = max(1.0, float(retry_after_seconds))
        super().__init__("translation provider is rate-limited")


@dataclass
class _RateLimitState:
    until_monotonic: float = 0.0
    backoff_seconds: float = 0.0


_RATE_LIMIT_STATE = _RateLimitState()
_PROVIDER_LOCKS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Lock
] = weakref.WeakKeyDictionary()


def _monotonic() -> float:
    return time.monotonic()


def _provider_lock() -> asyncio.Lock:
    """Return one serialization lock per event loop."""
    loop = asyncio.get_running_loop()
    lock = _PROVIDER_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _PROVIDER_LOCKS[loop] = lock
    return lock


def _retry_after_seconds(
    headers: object | None,
    *,
    now: datetime | None = None,
) -> float | None:
    """Parse an HTTP Retry-After value as delta seconds or an HTTP date."""
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    value = getter("Retry-After")
    if value is None:
        value = getter("retry-after")
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return max(0.0, (retry_at - current).total_seconds())


def _rate_limit_remaining(*, now: float | None = None) -> float:
    current = _monotonic() if now is None else float(now)
    return max(0.0, _RATE_LIMIT_STATE.until_monotonic - current)


def _activate_rate_limit(
    headers: object | None = None,
) -> tuple[float, float | None]:
    """Advance the local backoff and return (cooldown, provider Retry-After)."""
    if _RATE_LIMIT_STATE.backoff_seconds > 0:
        backoff = (
            _RATE_LIMIT_STATE.backoff_seconds
            * TRANSLATE_RATE_LIMIT_BACKOFF_MULTIPLIER
        )
    else:
        backoff = TRANSLATE_RATE_LIMIT_INITIAL_SECONDS

    provider_retry_after = _retry_after_seconds(headers)
    if provider_retry_after is not None:
        backoff = max(backoff, provider_retry_after)

    cooldown = min(
        TRANSLATE_RATE_LIMIT_MAX_SECONDS,
        max(1.0, backoff),
    )
    _RATE_LIMIT_STATE.backoff_seconds = cooldown
    _RATE_LIMIT_STATE.until_monotonic = _monotonic() + cooldown
    return cooldown, provider_retry_after


def _reset_rate_limit_state() -> None:
    _RATE_LIMIT_STATE.backoff_seconds = 0.0
    _RATE_LIMIT_STATE.until_monotonic = 0.0


def _rate_limit_wait_text(seconds: float) -> str:
    remaining = max(1, int(math.ceil(seconds)))
    if remaining < 60:
        return f"{remaining}s"
    minutes, secs = divmod(remaining, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def _raise_if_rate_limited() -> None:
    remaining = _rate_limit_remaining()
    if remaining > 0:
        raise TranslationRateLimitError(remaining)


def _prefix() -> str:
    return str(config.get("prefix", ",") or ",")


def _usage() -> str:
    prefix = _prefix()
    return (
        f"{prefix}tr <from> <to> <text> | "
        f"{prefix}tr <to> <text> | with TRANSLATE_TO: "
        f"{prefix}tr [text] | reply with {prefix}tr [from] [to]"
    )


def _normalize_language_code(value: object) -> str:
    return str(value or "").strip().replace("_", "-").lower()


def _is_supported_language(code: object, *, allow_auto: bool = True) -> bool:
    normalized = _normalize_language_code(code)
    if allow_auto and normalized == "auto":
        return True
    return normalized in SUPPORTED_LANGUAGE_CODES


def _configured_source_language() -> str:
    source = _normalize_language_code(TRANSLATE_FROM) or "auto"
    if not _is_supported_language(source):
        raise TranslationUsageError(
            f"Configured source language '{TRANSLATE_FROM}' is unsupported."
        )
    return source


def _configured_target_language() -> str | None:
    target = _normalize_language_code(TRANSLATE_TO)
    if target in {"", "none"}:
        return None
    if not _is_supported_language(target, allow_auto=False):
        raise TranslationUsageError(
            f"Configured target language '{TRANSLATE_TO}' is unsupported."
        )
    return target


def _default_source_for_target(source: str, target: str) -> str:
    """Avoid a no-op when a shorthand target equals the default source."""
    return "auto" if source == target else source


def _parse_translation_args(args: list[str] | tuple[str, ...]) -> TranslationRequest:
    """Parse compatible arguments with optional configured defaults.

    When the first two tokens are language codes they are interpreted as an
    explicit source/target pair. A leading language code otherwise overrides
    the configured target. When no leading language code is present, the
    complete argument list is text for the configured target language. Since
    ``auto`` cannot be a target language, it remains text unless a supported
    target code follows it explicitly.
    """
    tokens = [str(item) for item in args]
    source = _configured_source_language()
    configured_target = _configured_target_language()

    if not tokens:
        if configured_target is None:
            raise TranslationUsageError("Missing target language.")
        return TranslationRequest(
            source_language=_default_source_for_target(source, configured_target),
            target_language=configured_target,
            text="",
        )

    first = _normalize_language_code(tokens[0])
    if not _is_supported_language(first):
        if configured_target is None:
            raise TranslationUsageError(
                f"Unsupported language code '{tokens[0]}'. Use ISO language codes such as de, en, pl or uk."
            )
        return TranslationRequest(
            source_language=_default_source_for_target(source, configured_target),
            target_language=configured_target,
            text=" ".join(tokens).strip(),
        )

    target = first
    text_start = 1
    explicit_source = False

    if len(tokens) >= 2:
        second = _normalize_language_code(tokens[1])
        if _is_supported_language(second, allow_auto=False):
            source = first
            target = second
            text_start = 2
            explicit_source = True

    if target == "auto" and configured_target is not None:
        return TranslationRequest(
            source_language=source,
            target_language=configured_target,
            text=" ".join(tokens).strip(),
        )

    if target == "auto":
        raise TranslationUsageError("The target language cannot be 'auto'.")

    if not explicit_source:
        source = _default_source_for_target(source, target)

    return TranslationRequest(
        source_language=source,
        target_language=target,
        text=" ".join(tokens[text_start:]).strip(),
    )


def _room_from_message(msg, is_room: bool) -> str | None:
    try:
        room = str(msg["from"].bare)
    except Exception:
        return None
    if is_room or _core._is_muc_pm(msg):
        return room
    return None


def _body_without_reply_quote(body: str) -> str:
    """Remove the leading XEP-0461 plain-text fallback quote."""
    if not body:
        return ""
    lines = body.splitlines()
    index = 0
    while index < len(lines) and lines[index].startswith(">"):
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    return "\n".join(lines[index:]).strip()


def _is_translate_command_body(body: str) -> bool:
    stripped = str(body or "").strip().lower()
    prefix = _prefix().lower()
    return any(
        stripped == f"{prefix}{name}" or stripped.startswith(f"{prefix}{name} ")
        for name in ("tr", "translate")
    )


def _safe_room_nick(msg) -> str | None:
    try:
        return str(msg.get("mucnick") or msg["from"].resource or "") or None
    except Exception:
        return None


def _is_own_room_message(bot, msg) -> bool:
    nick = _safe_room_nick(msg)
    if not nick:
        return False
    try:
        room = str(msg["from"].bare)
        presence = getattr(bot, "presence", None)
        joined_rooms = getattr(presence, "joined_rooms", {})
        joined_nick = joined_rooms.get(room)
        if joined_nick and str(joined_nick) == nick:
            return True
    except Exception as exc:
        log.debug("[TRANSLATE] Could not resolve joined room nick: %s", exc)
    return nick == str(getattr(bot, "nick", "") or "")


def _clip_output(text: str) -> str:
    value = str(text or "").strip()
    if len(value) <= TRANSLATE_MAX_OUTPUT_LENGTH:
        return value
    return value[: TRANSLATE_MAX_OUTPUT_LENGTH - 1].rstrip() + "…"


def _translation_text_from_payload(data: Any) -> str:
    if not isinstance(data, list) or not data:
        raise TranslationProviderError("provider returned an unexpected response")
    segments = data[0]
    if not isinstance(segments, list):
        raise TranslationProviderError("provider response has no translation segments")

    translated_parts: list[str] = []
    for segment in segments:
        if not isinstance(segment, list) or not segment:
            continue
        part = segment[0]
        if isinstance(part, str):
            translated_parts.append(part)

    translated = "".join(translated_parts).strip()
    if not translated:
        raise TranslationProviderError("provider returned an empty translation")
    return translated


def _detected_language_from_payload(data: Any) -> str | None:
    if not isinstance(data, list):
        return None
    if len(data) > 2 and isinstance(data[2], str) and data[2].strip():
        return _normalize_language_code(data[2])
    try:
        nested = data[8][0][0]
    except (IndexError, KeyError, TypeError):
        return None
    return _normalize_language_code(nested) or None


def _normalized_translation_text(value: object) -> str:
    """Normalize provider text for unchanged-result detection."""
    return " ".join(str(value or "").split()).casefold()


def _format_translation_response(
    original_text: str,
    request: TranslationRequest,
    result: TranslationResult,
    *,
    is_room: bool,
) -> str:
    """Format a translation and explain ambiguous automatic no-op results."""
    translated = result.text
    if (
        request.source_language == "auto"
        and _normalized_translation_text(original_text)
        == _normalized_translation_text(result.text)
    ):
        detected = result.source_language or "unknown"
        example_source = "de" if request.target_language == "en" else "en"
        translated = (
            "🟡️ Auto-detection returned the text unchanged "
            f"(detected: {detected}). Specify the source language for short "
            f"or ambiguous text, e.g. {_prefix()}tr {example_source} "
            f"{request.target_language} <text>."
        )
    return f"> {original_text}\n\n{translated}" if is_room else translated


async def translate_text(
    text: str,
    *,
    target_language: str,
    source_language: str = "auto",
    fetcher=fetch_json,
) -> TranslationResult:
    """Translate one text through the fixed Google Translate endpoint."""
    clean_text = str(text or "").strip()
    if not clean_text:
        raise TranslationUsageError("No text to translate.")
    if len(clean_text) > TRANSLATE_MAX_INPUT_LENGTH:
        raise TranslationUsageError(
            f"Text is too long ({len(clean_text)} characters; maximum {TRANSLATE_MAX_INPUT_LENGTH})."
        )

    source = _normalize_language_code(source_language) or "auto"
    target = _normalize_language_code(target_language)
    if not _is_supported_language(source):
        raise TranslationUsageError(
            f"Unsupported source language code '{source_language}'."
        )
    if not _is_supported_language(target, allow_auto=False):
        raise TranslationUsageError(
            f"Unsupported target language code '{target_language}'."
        )

    query = urlencode(
        {
            "client": "gtx",
            "dt": "t",
            "q": clean_text,
            "sl": source,
            "tl": target,
        }
    )
    _raise_if_rate_limited()
    async with _provider_lock():
        # Another command may have received HTTP 429 while this one was waiting
        # for the provider lock. Re-check before sending anything upstream.
        _raise_if_rate_limited()
        try:
            result = await fetcher(
                f"{GOOGLE_TRANSLATE_ENDPOINT}?{query}",
                timeout_seconds=TRANSLATE_TIMEOUT_SECONDS,
                max_redirects=0,
                max_bytes=TRANSLATE_MAX_RESPONSE_BYTES,
                allow_private=False,
                validator=passthrough_validator,
                headers={"Accept": "application/json"},
            )
        except aiohttp.ClientResponseError as exc:
            if exc.status != 429:
                raise
            cooldown, retry_after = _activate_rate_limit(exc.headers)
            log.warning(
                "[TRANSLATE] Provider rate limited request status=429 "
                "cooldown_seconds=%.1f retry_after_seconds=%s",
                cooldown,
                "n/a" if retry_after is None else f"{retry_after:.1f}",
            )
            raise TranslationRateLimitError(cooldown) from None
        else:
            # A successful provider response ends the current 429 failure streak.
            _reset_rate_limit_state()

    data = result.data
    return TranslationResult(
        text=_clip_output(_translation_text_from_payload(data)),
        source_language=_detected_language_from_payload(data),
    )


def _reply_text_from_cache_or_quote(bot, msg, conversation: str | None) -> str | None:
    reply_id = _core.get_reply_target(msg)
    if reply_id and conversation:
        cached = bot.message_cache.get_by_id(conversation, reply_id)
        if cached:
            body = str(cached.get("body") or "").strip()
            if body:
                return body
    return _core.extract_reply_quote(str(msg.get("body", "") or ""))


async def _room_translation_enabled(bot, msg, is_room: bool) -> bool:
    room = _room_from_message(msg, is_room)
    if room is None:
        return True
    state = await get_room_feature(bot, room, "translate")
    return state.enabled


async def get_translate_store(bot):
    return bot.db.users.plugin("translate")


async def _handle_room_toggle_command(bot, msg, is_room: bool, args: list[str]) -> bool:
    """Delegate Translate room controls to the shared effective-state helper."""
    return await _core.handle_room_toggle_command(
        bot,
        msg,
        is_room,
        args,
        store_getter=get_translate_store,
        key=TRANSLATE_KEY,
        label="Translate plugin",
        plugin="translate",
        storage="dict",
        log_prefix="[TRANSLATE]",
    )


@command(
    "translate",
    role=Role.USER,
    aliases=["tr"],
    short="Translate text or a replied-to message.",
    usage="{prefix}tr [from] [to] [text or reply]",
    subcommands=[
        help_subcommand(
            "<languages>",
            "{prefix}tr [from] [to] <text>",
            "Translate provided text with explicit or configured language defaults.",
            examples=[
                help_example("{prefix}tr en uk Hello, world!", "Translate English text into Ukrainian."),
                help_example("{prefix}tr auto pl Guten Morgen", "Detect the source language automatically and translate into Polish."),
            ],
        ),
        help_subcommand(
            "<reply>",
            "Reply to a message with {prefix}tr [from] [to]",
            "Translate the replied-to message without copying its text into the command.",
            examples=[help_example("Reply with {prefix}tr en uk", "Translate the replied-to message from English into Ukrainian.")],
        ),
        *room_toggle_subcommands("translate", "translation commands"),
    ],
    examples=[
        "{prefix}tr en uk Hello, world!",
        "{prefix}tr uk Hallo Welt!",
        "{prefix}tr auto pl Guten Morgen",
        "With TRANSLATE_TO configured: {prefix}tr Hello, world!",
        "With TRANSLATE_TO configured: {prefix}tr auto",
        "With TRANSLATE_TO configured, reply with {prefix}tr",
        "Reply in a room, MUC PM or private chat with {prefix}tr en uk",
        "Reply in a room, MUC PM or private chat with {prefix}tr uk",
        "{prefix}translate status",
        "{prefix}rooms enable translate",
    ],
    category="utility",
    context="any",
)
async def translate_command(bot, sender_jid, nick, args, msg, is_room):
    """Translate text, or the replied-to message when text is omitted."""
    del sender_jid, nick

    if is_room or _core._is_muc_pm(msg):
        handled = await _handle_room_toggle_command(bot, msg, is_room, args)
        if handled:
            return

    if not await _room_translation_enabled(bot, msg, is_room):
        bot.reply(msg, "ℹ️ Translate is disabled in this room.", mention=False)
        return

    try:
        request = _parse_translation_args(args)
        text: str | None = request.text
        if not text:
            conversation = message_cache.conversation_key(
                msg,
                is_room=is_room,
                joined_rooms=bot.presence.joined_rooms,
            )
            text = _reply_text_from_cache_or_quote(
                bot,
                msg,
                conversation,
            )
        if not text:
            raise TranslationUsageError(
                "No text was provided and the replied-to message could not be resolved."
            )
        result = await translate_text(
            text,
            target_language=request.target_language,
            source_language=request.source_language,
        )
    except TranslationUsageError as exc:
        bot.reply(msg, f"🟡️ {exc}\nUsage: {_usage()}", mention=False)
        return
    except TranslationRateLimitError as exc:
        bot.reply(
            msg,
            "🟡 Translation service is temporarily rate-limited. "
            f"Try again in {_rate_limit_wait_text(exc.retry_after_seconds)}.",
            mention=False,
        )
        return
    except (TimeoutError, aiohttp.ClientError, UnsafeFetchURL) as exc:
        log.warning(
            "[TRANSLATE] Translation request failed error=%s status=%s",
            type(exc).__name__,
            getattr(exc, "status", "n/a"),
        )
        bot.reply(msg, "🔴 Translation service request failed.", mention=False)
        return
    except (
        FetchURLTooLarge,
        json.JSONDecodeError,
        TranslationProviderError,
        ValueError,
    ) as exc:
        log.warning(
            "[TRANSLATE] Invalid provider response error=%s",
            type(exc).__name__,
        )
        bot.reply(
            msg, "🔴 Translation service returned an invalid response.", mention=False
        )
        return
    except Exception as exc:
        # Do not log exception text here: aiohttp errors may embed the full GET
        # URL, including the private text in the q= query parameter.
        log.error(
            "[TRANSLATE] Unexpected translation error type=%s",
            type(exc).__name__,
        )
        bot.reply(msg, "🔴 Translation failed due to an internal error.", mention=False)
        return

    response = _format_translation_response(
        text,
        request,
        result,
        is_room=is_room,
    )
    bot.reply(msg, response, mention=False)


async def _redispatch_reply_fallback(bot, msg, *, is_room: bool) -> None:
    """Redispatch a quoted XEP-0461 command through normal command routing."""
    try:
        msg_type = str(msg.get("type") or "")
        if is_room:
            if msg_type != "groupchat" or _is_own_room_message(bot, msg):
                return
        elif msg_type not in {"chat", "normal"}:
            return

        body = str(msg.get("body", "") or "").strip()
        if not body:
            return

        quote = _core.extract_reply_quote(body)
        if not quote:
            return

        command_body = _body_without_reply_quote(body)
        if not _is_translate_command_body(command_body):
            return

        stanza_id = _core.get_stanza_id(msg)
        if not _core.remember_stanza(FALLBACK_NAMESPACE, stanza_id):
            return
        await bot.handle_command(
            command_body,
            msg["from"],
            _safe_room_nick(msg) if is_room else None,
            msg,
            is_room,
        )
    except Exception:
        log.exception("[TRANSLATE] Error handling reply fallback command")


async def _on_groupchat_message(bot, msg) -> None:
    """Handle a visible XEP-0461 fallback in a public room."""
    await _redispatch_reply_fallback(bot, msg, is_room=True)


async def _on_private_message(bot, msg) -> None:
    """Handle a visible XEP-0461 fallback in a MUC PM or direct chat."""
    await _redispatch_reply_fallback(bot, msg, is_room=False)


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return translate plugin diagnostics without calling the provider."""
    try:
        default_from = _configured_source_language()
        default_to = _configured_target_language() or "none"
    except TranslationUsageError as exc:
        return [f"❌ Translate: invalid defaults: {exc}"]

    remaining = _rate_limit_remaining()
    rate_limit = (
        f"cooldown {_rate_limit_wait_text(remaining)}"
        if remaining > 0
        else "ready"
    )
    icon = "⚠️" if remaining > 0 else "✅"
    if room_jid:
        feature = await get_room_feature(bot, str(room_jid), "translate")
        state = "enabled" if feature.enabled else "disabled"
        return [
            f"{icon} Translate for {room_jid}: {state}, provider=google, "
            f"default_from={default_from}, default_to={default_to}, "
            f"max_input={TRANSLATE_MAX_INPUT_LENGTH}, rate_limit={rate_limit}"
        ]
    return [
        f"{icon} Translate: provider=google, "
        f"default_from={default_from}, default_to={default_to}, "
        f"max_input={TRANSLATE_MAX_INPUT_LENGTH}, "
        f"timeout={TRANSLATE_TIMEOUT_SECONDS:g}s, rate_limit={rate_limit}"
    ]


async def on_load(bot) -> None:
    """Register reply-fallback handlers for room and private messages."""
    bot.bot_plugins.register_event(
        "translate",
        "groupchat_message",
        partial(_on_groupchat_message, bot),
    )
    bot.bot_plugins.register_event(
        "translate",
        "message",
        partial(_on_private_message, bot),
    )
