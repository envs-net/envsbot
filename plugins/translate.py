"""Translate text or an XMPP reply using Google Translate's public endpoint.

Examples
--------
Explicit source and target language::

    {prefix}tr en uk Hello, world!

Automatic source-language detection::

    {prefix}tr uk Hallo Welt!
    {prefix}tr auto uk Hallo Welt!

Reply to a room message and omit the text::

    {prefix}tr en uk
    {prefix}tr uk

The command behavior is inspired by ``maubot/translate`` while using the
existing envsbot XEP-0461 reply and stanza cache helpers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from functools import partial
from typing import Any
from urllib.parse import urlencode

import aiohttp

from core_plugins import _core
from utils.command import Role, command
from utils.config import config
from utils.http_fetch import fetch_json, passthrough_validator
from utils import message_cache
from utils.url_safety import FetchURLTooLarge, UnsafeFetchURL

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "translate",
    "version": "0.1.0",
    "description": (
        "Translate text or replied-to room messages with optional "
        "source-language auto-detection."
    ),
    "category": "utility",
    "requires": ["rooms", "_core"],
}

TRANSLATE_KEY = "TRANSLATE"
FALLBACK_NAMESPACE = "translate-fallback-command"
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


def _prefix() -> str:
    return str(config.get("prefix", ",") or ",")


def _usage() -> str:
    prefix = _prefix()
    return (
        f"{prefix}tr <from> <to> <text> | "
        f"{prefix}tr <to> <text> | reply with "
        f"{prefix}tr [from] <to>"
    )


def _normalize_language_code(value: object) -> str:
    return str(value or "").strip().replace("_", "-").lower()


def _is_supported_language(code: object, *, allow_auto: bool = True) -> bool:
    normalized = _normalize_language_code(code)
    if allow_auto and normalized == "auto":
        return True
    return normalized in SUPPORTED_LANGUAGE_CODES


def _parse_translation_args(args: list[str] | tuple[str, ...]) -> TranslationRequest:
    """Parse maubot-compatible ``[from] to [text]`` arguments.

    When the first two tokens are language codes they are interpreted as an
    explicit source/target pair. Otherwise the first token is the target and
    the source defaults to ``auto``.
    """
    tokens = [str(item) for item in args]
    if not tokens:
        raise TranslationUsageError("Missing target language.")

    first = _normalize_language_code(tokens[0])
    if not _is_supported_language(first):
        raise TranslationUsageError(
            f"Unsupported language code '{tokens[0]}'. Use ISO language codes such as de, en, pl or uk."
        )

    source = "auto"
    target = first
    text_start = 1

    if len(tokens) >= 2:
        second = _normalize_language_code(tokens[1])
        if _is_supported_language(second, allow_auto=False):
            source = first
            target = second
            text_start = 2

    if target == "auto":
        raise TranslationUsageError("The target language cannot be 'auto'.")

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
        joined_nick = getattr(bot.presence, "joined_rooms", {}).get(room)
        if joined_nick and str(joined_nick) == nick:
            return True
    except Exception:
        pass
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
    result = await fetcher(
        f"{GOOGLE_TRANSLATE_ENDPOINT}?{query}",
        timeout_seconds=TRANSLATE_TIMEOUT_SECONDS,
        max_redirects=0,
        max_bytes=TRANSLATE_MAX_RESPONSE_BYTES,
        allow_private=False,
        validator=passthrough_validator,
        headers={"Accept": "application/json"},
    )
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


async def get_translate_store(bot):
    return bot.db.users.plugin("translate")


async def _room_translation_enabled(bot, msg, is_room: bool) -> bool:
    room = _room_from_message(msg, is_room)
    if room is None:
        return True
    enabled_rooms = await _core._get_enabled_rooms(
        bot,
        TRANSLATE_KEY,
        "translate",
    )
    return room in enabled_rooms


@command(
    "translate",
    role=Role.USER,
    aliases=["tr"],
    short="Translate text or a replied-to room message.",
    usage="{prefix}tr [from] <to> [text or reply]",
    examples=[
        "{prefix}tr en uk Hello, world!",
        "{prefix}tr uk Hallo Welt!",
        "Reply to a message with {prefix}tr en uk",
        "Reply to a message with {prefix}tr uk",
        "{prefix}translate status",
        "{prefix}rooms enable translate",
    ],
    category="utility",
    context="any",
)
async def translate_command(bot, sender_jid, nick, args, msg, is_room):
    """Translate text, or the replied-to room message when text is omitted."""
    del sender_jid, nick

    if is_room or _core._is_muc_pm(msg):
        handled = await _core.handle_room_toggle_command(
            bot,
            msg,
            is_room,
            args,
            store_getter=get_translate_store,
            key=TRANSLATE_KEY,
            label="Translate plugin",
            storage="dict",
            log_prefix="[TRANSLATE]",
        )
        if handled:
            return

    if not await _room_translation_enabled(bot, msg, is_room):
        bot.reply(msg, "ℹ️ Translate is disabled in this room.", mention=False)
        return

    try:
        request = _parse_translation_args(args)
        text = request.text
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
    except (asyncio.TimeoutError, aiohttp.ClientError, UnsafeFetchURL):
        log.warning("[TRANSLATE] Translation request failed", exc_info=True)
        bot.reply(msg, "🔴 Translation service request failed.", mention=False)
        return
    except (
        FetchURLTooLarge,
        json.JSONDecodeError,
        TranslationProviderError,
        ValueError,
    ):
        log.warning("[TRANSLATE] Invalid translation provider response", exc_info=True)
        bot.reply(
            msg, "🔴 Translation service returned an invalid response.", mention=False
        )
        return
    except Exception:
        log.exception("[TRANSLATE] Unexpected translation error")
        bot.reply(msg, "🔴 Translation failed due to an internal error.", mention=False)
        return

    bot.reply(msg, result.text, mention=False)


async def _on_groupchat_message(bot, msg) -> None:
    """Redispatch a quoted XEP-0461 fallback while keeping `,tr` unchanged."""
    try:
        if msg.get("type") != "groupchat":
            return
        body = str(msg.get("body", "") or "").strip()
        if not body or _is_own_room_message(bot, msg):
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
            _safe_room_nick(msg),
            msg,
            True,
        )
    except Exception:
        log.exception("[TRANSLATE] Error handling reply fallback command")


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return translate plugin diagnostics without calling the provider."""
    if room_jid:
        enabled = await _core._is_enabled_for_room(
            bot,
            TRANSLATE_KEY,
            "translate",
            str(room_jid),
        )
        state = "enabled" if enabled else "disabled"
        return [
            f"✅ Translate for {room_jid}: {state}, provider=google, "
            f"max_input={TRANSLATE_MAX_INPUT_LENGTH}"
        ]
    return [
        "✅ Translate: provider=google, auto-detection=yes, "
        f"max_input={TRANSLATE_MAX_INPUT_LENGTH}, timeout={TRANSLATE_TIMEOUT_SECONDS:g}s"
    ]


async def on_load(bot) -> None:
    bot.bot_plugins.register_event(
        "translate",
        "groupchat_message",
        partial(_on_groupchat_message, bot),
    )
