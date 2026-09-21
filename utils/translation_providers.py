"""Provider-specific translation HTTP adapters for envsbot.

The module deliberately contains protocol mechanics only. Provider ordering,
fallback policy, rate-limit state and user-facing diagnostics stay in the
translate plugin.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import unescape
from typing import Any

import aiohttp

from utils.http_fetch import default_user_agent
from utils.url_safety import FetchURLTooLarge

GOOGLE_CLOUD_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"
GOOGLE_CLOUD_LANGUAGES_ENDPOINT = f"{GOOGLE_CLOUD_ENDPOINT}/languages"
DEEPL_FREE_BASE_URL = "https://api-free.deepl.com/v2"
DEEPL_PRO_BASE_URL = "https://api.deepl.com/v2"
DEEPL_FREE_ENDPOINT = f"{DEEPL_FREE_BASE_URL}/translate"
DEEPL_PRO_ENDPOINT = f"{DEEPL_PRO_BASE_URL}/translate"


@dataclass(frozen=True)
class ProviderTranslation:
    """Normalized translation returned by one provider adapter."""

    text: str
    source_language: str | None = None


@dataclass(frozen=True)
class ProviderCapabilities:
    """Normalized language capabilities advertised by one provider.

    ``translation_pairs`` is populated for providers such as LibreTranslate
    that expose exact source-to-target relationships. ``None`` means the
    provider publishes source and target sets separately and the adapter does
    not claim more specific pair knowledge.
    """

    source_languages: frozenset[str]
    target_languages: frozenset[str]
    translation_pairs: frozenset[tuple[str, str]] | None = None


class ProviderHTTPError(RuntimeError):
    """HTTP failure without embedding a URL, payload or credential in the error."""

    def __init__(
        self,
        provider: str,
        status: int,
        *,
        headers: object | None = None,
    ) -> None:
        self.provider = str(provider)
        self.status = int(status)
        self.headers = headers
        super().__init__(
            f"{self.provider} translation request failed with HTTP {self.status}"
        )


class ProviderPayloadError(RuntimeError):
    """Provider returned JSON that cannot be normalized as a translation."""


def _normalize_language(value: object) -> str | None:
    normalized = str(value or "").strip().replace("_", "-").lower()
    return normalized or None


def _limited_json_body(body: bytes, *, max_bytes: int) -> Any:
    if len(body) > max_bytes:
        raise FetchURLTooLarge(f"response exceeds {max_bytes} bytes")
    return json.loads(body.decode("utf-8", errors="strict"))


async def _get_json(
    url: str,
    *,
    params: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float,
    max_bytes: int,
    provider: str,
    session_factory=aiohttp.ClientSession,
) -> Any:
    """GET one bounded JSON response from an operator-selected provider."""
    request_headers = {
        "Accept": "application/json",
        "User-Agent": default_user_agent(),
        **(headers or {}),
    }
    timeout = aiohttp.ClientTimeout(total=float(timeout_seconds))
    try:
        session_cm = session_factory(timeout=timeout, headers=request_headers)
    except TypeError:
        session_cm = session_factory()

    async with session_cm as session:
        try:
            request_cm = session.get(
                str(url),
                params=params,
                allow_redirects=False,
            )
        except TypeError:
            request_cm = session.get(str(url), params=params)

        async with request_cm as response:
            status = int(getattr(response, "status", 0) or 0)
            response_headers = getattr(response, "headers", None)
            if status >= 400 or 300 <= status < 400:
                raise ProviderHTTPError(
                    provider,
                    status,
                    headers=response_headers,
                )

            reader = getattr(response, "read", None)
            if callable(reader):
                body = await reader()
            else:
                body = (await response.text()).encode("utf-8")
            return _limited_json_body(body, max_bytes=max_bytes)


async def _post_json(
    url: str,
    *,
    payload: dict[str, object],
    headers: dict[str, str] | None = None,
    timeout_seconds: float,
    max_bytes: int,
    provider: str,
    session_factory=aiohttp.ClientSession,
) -> Any:
    """POST one bounded JSON request to an operator-controlled provider URL."""
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": default_user_agent(),
        **(headers or {}),
    }
    timeout = aiohttp.ClientTimeout(total=float(timeout_seconds))
    try:
        session_cm = session_factory(timeout=timeout, headers=request_headers)
    except TypeError:
        session_cm = session_factory()

    async with session_cm as session:
        try:
            request_cm = session.post(
                str(url),
                json=payload,
                allow_redirects=False,
            )
        except TypeError:
            request_cm = session.post(str(url), json=payload)

        async with request_cm as response:
            status = int(getattr(response, "status", 0) or 0)
            response_headers = getattr(response, "headers", None)
            if status >= 400 or 300 <= status < 400:
                raise ProviderHTTPError(
                    provider,
                    status,
                    headers=response_headers,
                )

            reader = getattr(response, "read", None)
            if callable(reader):
                body = await reader()
            else:
                body = (await response.text()).encode("utf-8")
            return _limited_json_body(body, max_bytes=max_bytes)


def libretranslate_endpoint(base_url: str) -> str:
    """Return the LibreTranslate ``/translate`` endpoint for one base URL."""
    value = str(base_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("LibreTranslate URL is empty")
    if value.endswith("/translate"):
        return value
    return f"{value}/translate"


def libretranslate_languages_endpoint(base_url: str) -> str:
    """Return the LibreTranslate ``/languages`` endpoint for one base URL."""
    value = str(base_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("LibreTranslate URL is empty")
    if value.endswith("/translate"):
        value = value[: -len("/translate")].rstrip("/")
    return f"{value}/languages"


def deepl_base_url(api_key: str) -> str:
    """Select the documented DeepL Free/Pro base URL from the key shape."""
    key = str(api_key or "").strip()
    return DEEPL_FREE_BASE_URL if key.endswith(":fx") else DEEPL_PRO_BASE_URL


def deepl_endpoint(api_key: str) -> str:
    """Select the documented DeepL Free/Pro translation endpoint."""
    return f"{deepl_base_url(api_key)}/translate"


async def fetch_libretranslate_capabilities(
    *,
    base_url: str,
    languages_url: str | None = None,
    timeout_seconds: float,
    max_bytes: int,
    get_json=_get_json,
) -> ProviderCapabilities:
    """Fetch exact language-pair capabilities from LibreTranslate."""
    endpoint = (
        str(languages_url or "").strip()
        or libretranslate_languages_endpoint(base_url)
    )
    data = await get_json(
        endpoint,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        provider="libretranslate",
    )
    if not isinstance(data, list):
        raise ProviderPayloadError("LibreTranslate returned an invalid language list")

    sources: set[str] = set()
    targets: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        source = _normalize_language(item.get("code"))
        raw_targets = item.get("targets")
        if source is None or not isinstance(raw_targets, list):
            continue
        sources.add(source)
        for raw_target in raw_targets:
            target = _normalize_language(raw_target)
            if target is None:
                continue
            targets.add(target)
            pairs.add((source, target))

    if not sources or not targets:
        raise ProviderPayloadError("LibreTranslate returned no usable languages")
    return ProviderCapabilities(
        source_languages=frozenset(sources),
        target_languages=frozenset(targets),
        translation_pairs=frozenset(pairs),
    )


async def fetch_google_cloud_capabilities(
    *,
    api_key: str,
    timeout_seconds: float,
    max_bytes: int,
    get_json=_get_json,
) -> ProviderCapabilities:
    """Fetch Cloud Translation Basic v2 language capabilities."""
    data = await get_json(
        GOOGLE_CLOUD_LANGUAGES_ENDPOINT,
        headers={"X-goog-api-key": api_key},
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        provider="google",
    )
    try:
        items = data["data"]["languages"]
    except (KeyError, TypeError) as exc:
        raise ProviderPayloadError("Google Cloud returned no language list") from exc
    if not isinstance(items, list):
        raise ProviderPayloadError("Google Cloud returned an invalid language list")

    languages = {
        language
        for item in items
        if isinstance(item, dict)
        if (language := _normalize_language(item.get("language"))) is not None
    }
    if not languages:
        raise ProviderPayloadError("Google Cloud returned no usable languages")
    frozen = frozenset(languages)
    return ProviderCapabilities(
        source_languages=frozen,
        target_languages=frozen,
    )


async def fetch_deepl_capabilities(
    *,
    api_key: str,
    timeout_seconds: float,
    max_bytes: int,
    get_json=_get_json,
) -> ProviderCapabilities:
    """Fetch DeepL source and target language capabilities."""
    endpoint = f"{deepl_base_url(api_key)}/languages"
    headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}
    source_data = await get_json(
        endpoint,
        params={"type": "source"},
        headers=headers,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        provider="deepl",
    )
    target_data = await get_json(
        endpoint,
        params={"type": "target"},
        headers=headers,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        provider="deepl",
    )
    if not isinstance(source_data, list) or not isinstance(target_data, list):
        raise ProviderPayloadError("DeepL returned an invalid language list")

    sources = {
        language
        for item in source_data
        if isinstance(item, dict)
        if (language := _normalize_language(item.get("language"))) is not None
    }
    targets = {
        language
        for item in target_data
        if isinstance(item, dict)
        if (language := _normalize_language(item.get("language"))) is not None
    }
    if not sources or not targets:
        raise ProviderPayloadError("DeepL returned no usable languages")
    return ProviderCapabilities(
        source_languages=frozenset(sources),
        target_languages=frozenset(targets),
    )


async def translate_libretranslate(
    text: str,
    *,
    source_language: str,
    target_language: str,
    base_url: str,
    api_key: str | None,
    timeout_seconds: float,
    max_bytes: int,
    post_json=_post_json,
) -> ProviderTranslation:
    """Translate through a LibreTranslate-compatible API."""
    payload: dict[str, object] = {
        "q": text,
        "source": source_language,
        "target": target_language,
        "format": "text",
    }
    if api_key:
        payload["api_key"] = api_key

    data = await post_json(
        libretranslate_endpoint(base_url),
        payload=payload,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        provider="libretranslate",
    )
    if not isinstance(data, dict):
        raise ProviderPayloadError("LibreTranslate returned a non-object response")
    translated = data.get("translatedText")
    if not isinstance(translated, str) or not translated.strip():
        raise ProviderPayloadError("LibreTranslate returned no translatedText")

    detected = data.get("detectedLanguage")
    source: str | None = None
    if isinstance(detected, dict):
        source = _normalize_language(detected.get("language"))
    return ProviderTranslation(translated.strip(), source)


async def translate_google_cloud(
    text: str,
    *,
    source_language: str,
    target_language: str,
    api_key: str,
    timeout_seconds: float,
    max_bytes: int,
    post_json=_post_json,
) -> ProviderTranslation:
    """Translate through the official Google Cloud Translation Basic v2 API."""
    payload: dict[str, object] = {
        "q": text,
        "target": target_language,
        "format": "text",
    }
    if source_language != "auto":
        payload["source"] = source_language

    data = await post_json(
        GOOGLE_CLOUD_ENDPOINT,
        payload=payload,
        headers={"X-goog-api-key": api_key},
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        provider="google",
    )
    try:
        item = data["data"]["translations"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderPayloadError("Google Cloud returned no translation") from exc
    if not isinstance(item, dict):
        raise ProviderPayloadError("Google Cloud returned an invalid translation")
    translated = item.get("translatedText")
    if not isinstance(translated, str) or not translated.strip():
        raise ProviderPayloadError("Google Cloud returned an empty translation")
    source = _normalize_language(item.get("detectedSourceLanguage"))
    return ProviderTranslation(unescape(translated).strip(), source)


async def translate_deepl(
    text: str,
    *,
    source_language: str,
    target_language: str,
    api_key: str,
    timeout_seconds: float,
    max_bytes: int,
    post_json=_post_json,
) -> ProviderTranslation:
    """Translate through the official DeepL text translation API."""
    payload: dict[str, object] = {
        "text": [text],
        "target_lang": target_language.upper(),
    }
    if source_language != "auto":
        payload["source_lang"] = source_language.upper()

    data = await post_json(
        deepl_endpoint(api_key),
        payload=payload,
        headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        provider="deepl",
    )
    try:
        item = data["translations"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderPayloadError("DeepL returned no translation") from exc
    if not isinstance(item, dict):
        raise ProviderPayloadError("DeepL returned an invalid translation")
    translated = item.get("text")
    if not isinstance(translated, str) or not translated.strip():
        raise ProviderPayloadError("DeepL returned an empty translation")
    source = _normalize_language(item.get("detected_source_language"))
    return ProviderTranslation(translated.strip(), source)
