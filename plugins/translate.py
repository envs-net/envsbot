"""Translate text or an XMPP reply through configurable translation providers.

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

import aiohttp

from core_plugins import _core
from utils import message_cache
from utils.command import Role, command
from utils.command_metadata import (
    help_example,
    help_subcommand,
    room_toggle_subcommands,
)
from utils.config import config
from utils.room_features import get_room_feature
from utils.task_supervisor import (
    create_plugin_task,
    create_resilient_plugin_task,
    sleep_with_heartbeat,
)
from utils.translation_providers import (
    ProviderCapabilities,
    ProviderHTTPError,
    ProviderPayloadError,
    ProviderTranslation,
    fetch_deepl_capabilities,
    fetch_google_cloud_capabilities,
    fetch_libretranslate_capabilities,
    translate_deepl,
    translate_google_cloud,
    translate_libretranslate,
)
from utils.url_safety import FetchURLTooLarge, UnsafeFetchURL

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "translate",
    "version": "0.4.0",
    "description": (
        "Translate text or replied-to messages with multi-provider fallback "
        "and optional source-language auto-detection."
    ),
    "category": "utility",
    "requires": ["rooms", "_core"],
}

FALLBACK_NAMESPACE = "translate-fallback-command"
TRANSLATE_KEY = "TRANSLATE"

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
TRANSLATE_PROVIDER_QUEUE_TIMEOUT_SECONDS = max(
    0.1,
    float(config.get("translate_provider_queue_timeout_seconds", 5) or 5),
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
TRANSLATE_CAPABILITIES_REFRESH_SECONDS = max(
    60.0,
    float(config.get("translate_capabilities_refresh_seconds", 3600) or 3600),
)
TRANSLATE_FROM = str(config.get("translate_from", "auto") or "auto")
_configured_translate_to = config.get("translate_to")
TRANSLATE_TO = (
    None
    if _configured_translate_to is None
    else str(_configured_translate_to)
)
del _configured_translate_to

TRANSLATE_LIBRETRANSLATE_URL = str(
    config.get("translate_libretranslate_url", "https://translate.envs.net/")
    or ""
).strip()
TRANSLATE_LIBRETRANSLATE_API_KEY = str(
    config.get("translate_libretranslate_api_key") or ""
).strip()
TRANSLATE_GOOGLE_API_KEY = str(config.get("translate_google_api_key") or "").strip()
TRANSLATE_DEEPL_API_KEY = str(config.get("translate_deepl_api_key") or "").strip()

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


@dataclass(frozen=True)
class _ProviderAttempt:
    """One concrete upstream attempt in the configured fallback chain."""

    name: str
    state_key: str
    authenticated: bool


class TranslationUsageError(ValueError):
    """Raised for invalid command arguments."""


class TranslationProviderError(RuntimeError):
    """Raised when the remote translation provider returns unusable data."""


class TranslationRateLimitError(RuntimeError):
    """Raised when every usable provider is currently rate-limited."""

    def __init__(self, retry_after_seconds: float, provider: str | None = None):
        self.retry_after_seconds = max(1.0, float(retry_after_seconds))
        self.provider = provider
        super().__init__("translation provider is rate-limited")


class TranslationProviderBusyError(RuntimeError):
    """Raised when a command cannot obtain a serialized provider slot quickly."""


class TranslationProvidersUnavailableError(RuntimeError):
    """Raised after all configured translation providers fail."""


class TranslationLanguagePairUnavailableError(RuntimeError):
    """Raised when usable providers reject the requested language pair."""

    def __init__(
        self,
        source_language: str,
        target_language: str,
        *,
        fallback_temporarily_unavailable: bool = False,
    ) -> None:
        self.source_language = str(source_language)
        self.target_language = str(target_language)
        self.fallback_temporarily_unavailable = bool(
            fallback_temporarily_unavailable
        )
        super().__init__(
            f"translation language pair unavailable: "
            f"{self.source_language} -> {self.target_language}"
        )


@dataclass
class _RateLimitState:
    until_monotonic: float = 0.0
    backoff_seconds: float = 0.0
    total_429_count: int = 0
    streak_429_count: int = 0
    last_429_monotonic: float | None = None


@dataclass
class _CapabilityState:
    capabilities: ProviderCapabilities | None = None
    fetched_at_monotonic: float | None = None
    last_attempt_monotonic: float | None = None
    last_error: str | None = None


_RATE_LIMIT_STATES: dict[str, _RateLimitState] = {
    "google-api": _RateLimitState(),
}
# Compatibility alias retained for focused tests of the default rate-limit helpers.
_RATE_LIMIT_STATE = _RATE_LIMIT_STATES["google-api"]
_PROVIDER_LOCKS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, asyncio.Lock]
] = weakref.WeakKeyDictionary()
_CAPABILITY_STATES: dict[str, _CapabilityState] = {}
_CAPABILITY_REFRESH_TASK: asyncio.Task | None = None


def _monotonic() -> float:
    return time.monotonic()


def _rate_limit_state(provider_key: str = "google-api") -> _RateLimitState:
    state = _RATE_LIMIT_STATES.get(provider_key)
    if state is None:
        state = _RateLimitState()
        _RATE_LIMIT_STATES[provider_key] = state
    return state


def _provider_lock(provider_key: str = "google-api") -> asyncio.Lock:
    """Return one serialization lock per provider and event loop."""
    loop = asyncio.get_running_loop()
    locks = _PROVIDER_LOCKS.get(loop)
    if locks is None:
        locks = {}
        _PROVIDER_LOCKS[loop] = locks
    lock = locks.get(provider_key)
    if lock is None:
        lock = asyncio.Lock()
        locks[provider_key] = lock
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


def _rate_limit_remaining(
    provider_key: str = "google-api",
    *,
    now: float | None = None,
) -> float:
    current = _monotonic() if now is None else float(now)
    state = _rate_limit_state(provider_key)
    return max(0.0, state.until_monotonic - current)


def _activate_rate_limit(
    headers: object | None = None,
    *,
    provider_key: str = "google-api",
) -> tuple[float, float | None]:
    """Advance one provider's local 429 backoff."""
    state = _rate_limit_state(provider_key)
    if state.backoff_seconds > 0:
        backoff = state.backoff_seconds * TRANSLATE_RATE_LIMIT_BACKOFF_MULTIPLIER
    else:
        backoff = TRANSLATE_RATE_LIMIT_INITIAL_SECONDS

    provider_retry_after = _retry_after_seconds(headers)
    if provider_retry_after is not None:
        backoff = max(backoff, provider_retry_after)

    cooldown = min(
        TRANSLATE_RATE_LIMIT_MAX_SECONDS,
        max(1.0, backoff),
    )
    now = _monotonic()
    state.backoff_seconds = cooldown
    state.until_monotonic = now + cooldown
    state.total_429_count += 1
    state.streak_429_count += 1
    state.last_429_monotonic = now
    return cooldown, provider_retry_after


def _reset_rate_limit_backoff(provider_key: str = "google-api") -> None:
    """End one provider's active 429 streak while retaining history."""
    state = _rate_limit_state(provider_key)
    state.backoff_seconds = 0.0
    state.until_monotonic = 0.0
    state.streak_429_count = 0


def _reset_rate_limit_state(provider_key: str | None = None) -> None:
    """Reset provider cooldown diagnostics (primarily for tests)."""
    if provider_key is None:
        _RATE_LIMIT_STATES.clear()
        _RATE_LIMIT_STATES["google-api"] = _RATE_LIMIT_STATE
        states = tuple(_RATE_LIMIT_STATES.values())
    else:
        states = (_rate_limit_state(provider_key),)
    for state in states:
        state.backoff_seconds = 0.0
        state.until_monotonic = 0.0
        state.total_429_count = 0
        state.streak_429_count = 0
        state.last_429_monotonic = None


def _capability_state(provider_key: str) -> _CapabilityState:
    state = _CAPABILITY_STATES.get(provider_key)
    if state is None:
        state = _CapabilityState()
        _CAPABILITY_STATES[provider_key] = state
    return state


def _reset_capability_state(provider_key: str | None = None) -> None:
    """Reset capability cache diagnostics (primarily for tests/reloads)."""
    if provider_key is None:
        _CAPABILITY_STATES.clear()
    else:
        _CAPABILITY_STATES.pop(provider_key, None)


def _capability_age(
    provider_key: str,
    *,
    now: float | None = None,
) -> float | None:
    fetched_at = _capability_state(provider_key).fetched_at_monotonic
    if fetched_at is None:
        return None
    current = _monotonic() if now is None else float(now)
    return max(0.0, current - fetched_at)


def _rate_limit_wait_text(seconds: float) -> str:
    remaining = max(1, int(math.ceil(seconds)))
    if remaining < 60:
        return f"{remaining}s"
    minutes, secs = divmod(remaining, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def _raise_if_rate_limited(provider_key: str = "google-api") -> None:
    remaining = _rate_limit_remaining(provider_key)
    if remaining > 0:
        raise TranslationRateLimitError(remaining, provider_key)


def _last_rate_limit_age(
    provider_key: str = "google-api",
    *,
    now: float | None = None,
) -> float | None:
    last = _rate_limit_state(provider_key).last_429_monotonic
    if last is None:
        return None
    current = _monotonic() if now is None else float(now)
    return max(0.0, current - last)


def _elapsed_text(seconds: float) -> str:
    elapsed = max(0, int(seconds))
    if elapsed < 60:
        return f"{elapsed}s"
    minutes, secs = divmod(elapsed, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


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


def _provider_chain() -> tuple[_ProviderAttempt, ...]:
    """Return provider attempts with authenticated providers first.

    Configured API-key providers are preferred in the deliberate order
    LibreTranslate -> Google -> DeepL. Without a LibreTranslate key, the
    configured LibreTranslate instance remains the unauthenticated fallback.
    Google is supported only through the official Cloud Translation API and
    therefore requires ``TRANSLATE_GOOGLE_API_KEY``. DeepL also requires a key.
    """
    attempts: list[_ProviderAttempt] = []
    if TRANSLATE_LIBRETRANSLATE_API_KEY and TRANSLATE_LIBRETRANSLATE_URL:
        attempts.append(
            _ProviderAttempt("libretranslate", "libretranslate-api", True)
        )
    if TRANSLATE_GOOGLE_API_KEY:
        attempts.append(_ProviderAttempt("google", "google-api", True))
    if TRANSLATE_DEEPL_API_KEY:
        attempts.append(_ProviderAttempt("deepl", "deepl-api", True))

    if not TRANSLATE_LIBRETRANSLATE_API_KEY and TRANSLATE_LIBRETRANSLATE_URL:
        attempts.append(
            _ProviderAttempt("libretranslate", "libretranslate-public", False)
        )
    return tuple(attempts)


def _provider_label(attempt: _ProviderAttempt) -> str:
    mode = "api-key" if attempt.authenticated else "public"
    return f"{attempt.name}({mode})"


def _language_membership(
    languages: frozenset[str],
    code: str,
) -> bool | None:
    """Return exact support, definite absence, or variant ambiguity."""
    if code in languages:
        return True
    base = code.split("-", 1)[0]
    if any(item.split("-", 1)[0] == base for item in languages):
        return None
    return False


def _capability_supports_pair(
    capabilities: ProviderCapabilities,
    source_language: str,
    target_language: str,
) -> bool | None:
    """Return whether cached capabilities can decide one language pair.

    ``None`` is deliberately conservative: regional/script variants can be
    accepted by a provider even if its discovery endpoint reports a related
    base/variant code. Unknown pairs therefore fall through to the provider
    instead of being rejected locally.
    """
    target_status = _language_membership(
        capabilities.target_languages,
        target_language,
    )
    if target_status is False:
        return False
    if source_language == "auto":
        return target_status

    source_status = _language_membership(
        capabilities.source_languages,
        source_language,
    )
    if source_status is False:
        return False
    if source_status is None or target_status is None:
        return None

    pairs = capabilities.translation_pairs
    if pairs is None:
        return True
    return (source_language, target_language) in pairs


def _fresh_provider_capabilities(
    attempt: _ProviderAttempt,
) -> ProviderCapabilities | None:
    state = _capability_state(attempt.state_key)
    if state.capabilities is None or state.fetched_at_monotonic is None:
        return None
    age = max(0.0, _monotonic() - state.fetched_at_monotonic)
    if age > TRANSLATE_CAPABILITIES_REFRESH_SECONDS:
        return None
    return state.capabilities


def _provider_pair_support(
    attempt: _ProviderAttempt,
    *,
    source_language: str,
    target_language: str,
) -> bool | None:
    capabilities = _fresh_provider_capabilities(attempt)
    if capabilities is None:
        return None
    return _capability_supports_pair(
        capabilities,
        source_language,
        target_language,
    )


async def _fetch_provider_capabilities(
    attempt: _ProviderAttempt,
) -> ProviderCapabilities:
    if attempt.name == "libretranslate":
        return await fetch_libretranslate_capabilities(
            base_url=TRANSLATE_LIBRETRANSLATE_URL,
            timeout_seconds=TRANSLATE_TIMEOUT_SECONDS,
            max_bytes=TRANSLATE_MAX_RESPONSE_BYTES,
        )
    if attempt.name == "google":
        return await fetch_google_cloud_capabilities(
            api_key=TRANSLATE_GOOGLE_API_KEY,
            timeout_seconds=TRANSLATE_TIMEOUT_SECONDS,
            max_bytes=TRANSLATE_MAX_RESPONSE_BYTES,
        )
    if attempt.name == "deepl":
        return await fetch_deepl_capabilities(
            api_key=TRANSLATE_DEEPL_API_KEY,
            timeout_seconds=TRANSLATE_TIMEOUT_SECONDS,
            max_bytes=TRANSLATE_MAX_RESPONSE_BYTES,
        )
    raise TranslationProviderError(
        f"unknown translation provider {attempt.name!r}"
    )


async def _refresh_provider_capabilities(attempt: _ProviderAttempt) -> bool:
    """Refresh one provider cache without affecting translation availability."""
    state = _capability_state(attempt.state_key)
    state.last_attempt_monotonic = _monotonic()
    try:
        capabilities = await _fetch_provider_capabilities(attempt)
    except (
        TimeoutError,
        aiohttp.ClientError,
        FetchURLTooLarge,
        json.JSONDecodeError,
        ProviderHTTPError,
        ProviderPayloadError,
        ValueError,
    ) as exc:
        state.last_error = type(exc).__name__
        log.warning(
            "[TRANSLATE] Capability refresh failed provider=%s error=%s",
            attempt.name,
            type(exc).__name__,
        )
        return False

    state.capabilities = capabilities
    state.fetched_at_monotonic = _monotonic()
    state.last_error = None
    log.info(
        "[TRANSLATE] Capability refresh succeeded provider=%s "
        "sources=%d targets=%d",
        attempt.name,
        len(capabilities.source_languages),
        len(capabilities.target_languages),
    )
    return True


async def _refresh_capabilities_once() -> None:
    seen: set[str] = set()
    for attempt in _provider_chain():
        if attempt.state_key in seen:
            continue
        seen.add(attempt.state_key)
        await _refresh_provider_capabilities(attempt)


async def _capability_refresh_loop(bot) -> None:
    while True:
        await _refresh_capabilities_once()
        await sleep_with_heartbeat(
            bot,
            "translate",
            "translate-capabilities",
            TRANSLATE_CAPABILITIES_REFRESH_SECONDS,
        )


async def _call_provider(
    attempt: _ProviderAttempt,
    text: str,
    *,
    source_language: str,
    target_language: str,
) -> ProviderTranslation:
    if attempt.name == "libretranslate":
        return await translate_libretranslate(
            text,
            source_language=source_language,
            target_language=target_language,
            base_url=TRANSLATE_LIBRETRANSLATE_URL,
            api_key=(
                TRANSLATE_LIBRETRANSLATE_API_KEY
                if attempt.authenticated
                else None
            ),
            timeout_seconds=TRANSLATE_TIMEOUT_SECONDS,
            max_bytes=TRANSLATE_MAX_RESPONSE_BYTES,
        )
    if attempt.name == "google":
        return await translate_google_cloud(
            text,
            source_language=source_language,
            target_language=target_language,
            api_key=TRANSLATE_GOOGLE_API_KEY,
            timeout_seconds=TRANSLATE_TIMEOUT_SECONDS,
            max_bytes=TRANSLATE_MAX_RESPONSE_BYTES,
        )
    if attempt.name == "deepl":
        return await translate_deepl(
            text,
            source_language=source_language,
            target_language=target_language,
            api_key=TRANSLATE_DEEPL_API_KEY,
            timeout_seconds=TRANSLATE_TIMEOUT_SECONDS,
            max_bytes=TRANSLATE_MAX_RESPONSE_BYTES,
        )
    raise TranslationProviderError(f"unknown translation provider {attempt.name!r}")


async def _run_provider_attempt(
    attempt: _ProviderAttempt,
    text: str,
    *,
    source_language: str,
    target_language: str,
) -> ProviderTranslation:
    _raise_if_rate_limited(attempt.state_key)
    lock = _provider_lock(attempt.state_key)
    try:
        await asyncio.wait_for(
            lock.acquire(),
            timeout=TRANSLATE_PROVIDER_QUEUE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise TranslationProviderBusyError(
            f"{attempt.name} translation provider request queue is busy"
        ) from None

    try:
        _raise_if_rate_limited(attempt.state_key)
        try:
            result = await _call_provider(
                attempt,
                text,
                source_language=source_language,
                target_language=target_language,
            )
        except ProviderHTTPError as exc:
            if exc.status != 429:
                raise
            cooldown, retry_after = _activate_rate_limit(
                exc.headers,
                provider_key=attempt.state_key,
            )
            log.warning(
                "[TRANSLATE] Provider rate limited request provider=%s "
                "status=429 cooldown_seconds=%.1f retry_after_seconds=%s",
                attempt.name,
                cooldown,
                "n/a" if retry_after is None else f"{retry_after:.1f}",
            )
            raise TranslationRateLimitError(
                cooldown,
                attempt.state_key,
            ) from None
        else:
            _reset_rate_limit_backoff(attempt.state_key)
            return result
    finally:
        lock.release()


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
) -> TranslationResult:
    """Translate text through the configured provider fallback chain."""
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

    attempts = _provider_chain()
    if not attempts:
        raise TranslationProvidersUnavailableError(
            "no translation providers are configured"
        )

    rate_limits: list[TranslationRateLimitError] = []
    busy_count = 0
    failed_count = 0
    language_rejection_count = 0
    for index, attempt in enumerate(attempts, start=1):
        capability_support = _provider_pair_support(
            attempt,
            source_language=source,
            target_language=target,
        )
        if capability_support is False:
            language_rejection_count += 1
            log.info(
                "[TRANSLATE] Provider skipped by capabilities provider=%s "
                "source=%s target=%s fallback=%s",
                attempt.name,
                source,
                target,
                index < len(attempts),
            )
            continue

        try:
            result = await _run_provider_attempt(
                attempt,
                clean_text,
                source_language=source,
                target_language=target,
            )
        except TranslationRateLimitError as exc:
            rate_limits.append(exc)
            continue
        except TranslationProviderBusyError:
            busy_count += 1
            continue
        except ProviderHTTPError as exc:
            if exc.status == 400:
                language_rejection_count += 1
                log.info(
                    "[TRANSLATE] Provider rejected language pair provider=%s "
                    "source=%s target=%s fallback=%s",
                    attempt.name,
                    source,
                    target,
                    index < len(attempts),
                )
            else:
                failed_count += 1
                log.warning(
                    "[TRANSLATE] Provider request failed provider=%s status=%s "
                    "fallback=%s",
                    attempt.name,
                    exc.status,
                    index < len(attempts),
                )
            continue
        except (
            TimeoutError,
            aiohttp.ClientError,
            UnsafeFetchURL,
            FetchURLTooLarge,
            json.JSONDecodeError,
            ProviderPayloadError,
            ValueError,
        ) as exc:
            failed_count += 1
            log.warning(
                "[TRANSLATE] Provider request failed provider=%s error=%s "
                "fallback=%s",
                attempt.name,
                type(exc).__name__,
                index < len(attempts),
            )
            continue

        if index > 1:
            log.info(
                "[TRANSLATE] Provider fallback succeeded provider=%s attempt=%d",
                attempt.name,
                index,
            )
        return TranslationResult(
            text=_clip_output(result.text),
            source_language=result.source_language,
        )

    if language_rejection_count and failed_count == 0:
        raise TranslationLanguagePairUnavailableError(
            source,
            target,
            fallback_temporarily_unavailable=bool(rate_limits or busy_count),
        )
    if rate_limits and failed_count == 0:
        soonest = min(rate_limits, key=lambda exc: exc.retry_after_seconds)
        raise TranslationRateLimitError(
            soonest.retry_after_seconds,
            soonest.provider,
        )
    if busy_count and failed_count == 0 and not rate_limits:
        raise TranslationProviderBusyError(
            "all translation provider request queues are busy"
        )
    raise TranslationProvidersUnavailableError(
        "all configured translation providers failed"
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
    except TranslationProviderBusyError:
        bot.reply(
            msg,
            "🟡 Translation service is busy. Please try again shortly.",
            mention=False,
        )
        return
    except TranslationLanguagePairUnavailableError as exc:
        message = (
            "🟡 The requested language pair "
            f"{exc.source_language} → {exc.target_language} is not supported "
            "by the currently available translation provider(s)."
        )
        if exc.fallback_temporarily_unavailable:
            message += " Another fallback provider is temporarily unavailable."
        bot.reply(msg, message, mention=False)
        return
    except TranslationProvidersUnavailableError:
        bot.reply(
            msg,
            "🔴 No translation provider is currently available.",
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


def _provider_diagnostics() -> tuple[str, str, str]:
    attempts = _provider_chain()
    if not attempts:
        return "none", "unavailable", "0"

    labels = " -> ".join(_provider_label(attempt) for attempt in attempts)
    limited: list[str] = []
    histories: list[str] = []
    available = 0
    for attempt in attempts:
        remaining = _rate_limit_remaining(attempt.state_key)
        state = _rate_limit_state(attempt.state_key)
        if remaining > 0:
            limited.append(
                f"{_provider_label(attempt)}:{_rate_limit_wait_text(remaining)}"
            )
        else:
            available += 1
        if state.total_429_count:
            history = f"{_provider_label(attempt)}:{state.total_429_count}"
            age = _last_rate_limit_age(attempt.state_key)
            if age is not None:
                history += f"@{_elapsed_text(age)}"
            if state.streak_429_count:
                history += f"/streak={state.streak_429_count}"
            histories.append(history)

    rate_limit = "ready" if not limited else "cooldown " + ", ".join(limited)
    history = "none" if not histories else ", ".join(histories)
    return labels, rate_limit, history if available else f"{history}; all cooling down"


def _capability_diagnostics() -> str:
    attempts_by_name = {attempt.name: attempt for attempt in _provider_chain()}
    parts: list[str] = []
    for name in ("libretranslate", "google", "deepl"):
        attempt = attempts_by_name.get(name)
        if attempt is None:
            status = "disabled" if name == "libretranslate" else "not configured"
            parts.append(f"{name}:{status}")
            continue

        state = _capability_state(attempt.state_key)
        capabilities = state.capabilities
        if capabilities is None:
            if state.last_error:
                parts.append(f"{name}:error={state.last_error}")
            else:
                parts.append(f"{name}:pending")
            continue

        languages = len(
            capabilities.source_languages | capabilities.target_languages
        )
        age = _capability_age(attempt.state_key)
        age_text = "unknown" if age is None else _elapsed_text(age)
        freshness = (
            "fresh"
            if age is not None and age <= TRANSLATE_CAPABILITIES_REFRESH_SECONDS
            else "stale"
        )
        detail = f"{name}:{languages} languages/{freshness} {age_text}"
        if state.last_error:
            detail += f"/refresh-error={state.last_error}"
        parts.append(detail)
    return ", ".join(parts)


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return translate plugin diagnostics without calling providers."""
    try:
        default_from = _configured_source_language()
        default_to = _configured_target_language() or "none"
    except TranslationUsageError as exc:
        return [f"❌ Translate: invalid defaults: {exc}"]

    attempts = _provider_chain()
    provider_chain, rate_limit, history = _provider_diagnostics()
    all_cooling = bool(attempts) and all(
        _rate_limit_remaining(attempt.state_key) > 0 for attempt in attempts
    )
    icon = "⚠️" if not attempts or all_cooling else "✅"
    common = (
        f"providers={provider_chain}, default_from={default_from}, "
        f"default_to={default_to}, max_input={TRANSLATE_MAX_INPUT_LENGTH}, "
        f"queue_wait={TRANSLATE_PROVIDER_QUEUE_TIMEOUT_SECONDS:g}s, "
        f"rate_limit={rate_limit}, 429_history={history}"
    )
    capability_line = f"ℹ️ Translate capabilities: {_capability_diagnostics()}"
    if room_jid:
        feature = await get_room_feature(bot, str(room_jid), "translate")
        state = "enabled" if feature.enabled else "disabled"
        return [
            f"{icon} Translate for {room_jid}: {state}, {common}",
            capability_line,
        ]
    return [
        f"{icon} Translate: {common}, timeout={TRANSLATE_TIMEOUT_SECONDS:g}s",
        capability_line,
    ]


async def on_load(bot) -> None:
    """Register handlers and start non-blocking capability discovery."""
    global _CAPABILITY_REFRESH_TASK

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

    if _CAPABILITY_REFRESH_TASK and not _CAPABILITY_REFRESH_TASK.done():
        _CAPABILITY_REFRESH_TASK.cancel()
        try:
            await _CAPABILITY_REFRESH_TASK
        except asyncio.CancelledError:
            pass

    _CAPABILITY_REFRESH_TASK = create_resilient_plugin_task(
        bot,
        "translate",
        lambda: _capability_refresh_loop(bot),
        name="translate-capabilities",
        fallback_creator=create_plugin_task,
    )


async def on_unload(bot) -> None:
    """Stop capability discovery when the plugin is unloaded."""
    del bot
    global _CAPABILITY_REFRESH_TASK

    task = _CAPABILITY_REFRESH_TASK
    _CAPABILITY_REFRESH_TASK = None
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
