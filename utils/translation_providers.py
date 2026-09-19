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
from urllib.parse import urlencode

import aiohttp

from utils.http_fetch import default_user_agent, fetch_json
from utils.url_safety import FetchURLTooLarge

GOOGLE_PUBLIC_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
GOOGLE_CLOUD_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"
DEEPL_FREE_ENDPOINT = "https://api-free.deepl.com/v2/translate"
DEEPL_PRO_ENDPOINT = "https://api.deepl.com/v2/translate"


@dataclass(frozen=True)
class ProviderTranslation:
    """Normalized translation returned by one provider adapter."""

    text: str
    source_language: str | None = None


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
        super().__init__(f"{self.provider} translation request failed with HTTP {self.status}")


class ProviderPayloadError(RuntimeError):
    """Provider returned JSON that cannot be normalized as a translation."""


def _normalize_language(value: object) -> str | None:
    normalized = str(value or "").strip().replace("_", "-").lower()
    return normalized or None


def _limited_json_body(body: bytes, *, max_bytes: int) -> Any:
    if len(body) > max_bytes:
        raise FetchURLTooLarge(f"response exceeds {max_bytes} bytes")
    return json.loads(body.decode("utf-8", errors="strict"))


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


def deepl_endpoint(api_key: str) -> str:
    """Select the documented DeepL Free/Pro endpoint from the key shape."""
    key = str(api_key or "").strip()
    return DEEPL_FREE_ENDPOINT if key.endswith(":fx") else DEEPL_PRO_ENDPOINT


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


def _google_public_translation_text(data: Any) -> str:
    if not isinstance(data, list) or not data:
        raise ProviderPayloadError("Google public endpoint returned an unexpected response")
    segments = data[0]
    if not isinstance(segments, list):
        raise ProviderPayloadError("Google public endpoint returned no translation segments")

    translated_parts: list[str] = []
    for segment in segments:
        if not isinstance(segment, list) or not segment:
            continue
        part = segment[0]
        if isinstance(part, str):
            translated_parts.append(part)
    translated = "".join(translated_parts).strip()
    if not translated:
        raise ProviderPayloadError("Google public endpoint returned an empty translation")
    return translated


def _google_public_detected_language(data: Any) -> str | None:
    if not isinstance(data, list):
        return None
    if len(data) > 2 and isinstance(data[2], str) and data[2].strip():
        return _normalize_language(data[2])
    try:
        nested = data[8][0][0]
    except (IndexError, KeyError, TypeError):
        return None
    return _normalize_language(nested)


async def translate_google_public(
    text: str,
    *,
    source_language: str,
    target_language: str,
    timeout_seconds: float,
    max_bytes: int,
    fetcher=fetch_json,
) -> ProviderTranslation:
    """Translate through Google's legacy unauthenticated public endpoint."""
    query = urlencode(
        {
            "client": "gtx",
            "dt": "t",
            "q": text,
            "sl": source_language,
            "tl": target_language,
        }
    )
    try:
        result = await fetcher(
            f"{GOOGLE_PUBLIC_ENDPOINT}?{query}",
            timeout_seconds=timeout_seconds,
            max_redirects=0,
            max_bytes=max_bytes,
            allow_private=False,
            headers={"Accept": "application/json"},
        )
    except aiohttp.ClientResponseError as exc:
        raise ProviderHTTPError(
            "google",
            exc.status,
            headers=exc.headers,
        ) from None

    return ProviderTranslation(
        _google_public_translation_text(result.data),
        _google_public_detected_language(result.data),
    )


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
