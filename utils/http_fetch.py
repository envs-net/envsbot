"""Shared async HTTP fetch helper with timeout, redirect and SSRF guardrails."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urljoin
from collections.abc import Callable
from typing import Any

import aiohttp

from utils.config import config
from utils.url_safety import FetchURLTooLarge, UnsafeFetchURL, validate_fetch_url_async

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class HTTPFetchResult:
    """Small immutable HTTP response payload."""

    body: bytes
    url: str
    content_type: str
    status: int


@dataclass(frozen=True)
class HTTPTextResult:
    """HTTP response payload decoded as text."""

    text: str
    url: str
    content_type: str
    status: int


@dataclass(frozen=True)
class HTTPJsonResult:
    """HTTP response payload decoded as JSON."""

    data: Any
    url: str
    content_type: str
    status: int



async def passthrough_validator(url: str, **_: Any) -> str:
    """Return URL unchanged for fixed, operator-controlled API endpoints."""
    return str(url)


def default_user_agent() -> str:
    return str(
        config.get("http_user_agent")
        or "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)"
    )


def _session_from_factory(
    session_factory: Callable[..., aiohttp.ClientSession],
    *,
    timeout: aiohttp.ClientTimeout,
    headers: dict[str, str],
):
    """Create a ClientSession while keeping tests with tiny fakes simple."""
    try:
        return session_factory(timeout=timeout, headers=headers)
    except TypeError:
        try:
            return session_factory(timeout=timeout)
        except TypeError:
            return session_factory()


def _session_get(session: aiohttp.ClientSession, url: str, timeout: aiohttp.ClientTimeout):
    """Call session.get with fallbacks for small test doubles."""
    try:
        return session.get(url, allow_redirects=False)
    except TypeError:
        try:
            return session.get(url, timeout=timeout, allow_redirects=False)
        except TypeError:
            return session.get(url, allow_redirects=False)


def _response_url(resp: aiohttp.ClientResponse, fallback_url: str) -> str:
    return str(getattr(resp, "url", fallback_url) or fallback_url)


def _response_headers(resp: aiohttp.ClientResponse) -> dict[str, str]:
    headers = getattr(resp, "headers", None)
    return headers if isinstance(headers, dict) else {}


def _response_content_type(resp: aiohttp.ClientResponse) -> str:
    return _response_headers(resp).get("Content-Type", "")


def _response_location(resp: aiohttp.ClientResponse) -> str | None:
    return _response_headers(resp).get("Location")


def _maybe_raise_for_status(resp: aiohttp.ClientResponse, *, raise_for_status: bool) -> None:
    if not raise_for_status:
        return
    raiser = getattr(resp, "raise_for_status", None)
    if callable(raiser):
        raiser()
        return
    status = int(getattr(resp, "status", 0) or 0)
    if status >= 400:
        raise aiohttp.ClientResponseError(
            request_info=None,
            history=(),
            status=status,
            message="HTTP request failed",
            headers=getattr(resp, "headers", None),
        )


async def _read_limited_response(resp: aiohttp.ClientResponse, max_bytes: int) -> bytes:
    chunks = bytearray()
    content = getattr(resp, "content", None)
    if content is not None and hasattr(content, "iter_chunked"):
        async for chunk in content.iter_chunked(8192):
            chunks.extend(chunk)
            if len(chunks) > max_bytes:
                raise FetchURLTooLarge(f"response exceeds {max_bytes} bytes")
        return bytes(chunks)

    text_reader = getattr(resp, "text", None)
    if callable(text_reader):
        data = (await text_reader()).encode("utf-8", errors="replace")
        if len(data) > max_bytes:
            raise FetchURLTooLarge(f"response exceeds {max_bytes} bytes")
        return data

    json_reader = getattr(resp, "json", None)
    if callable(json_reader):
        data = json.dumps(await json_reader()).encode("utf-8")
        if len(data) > max_bytes:
            raise FetchURLTooLarge(f"response exceeds {max_bytes} bytes")
        return data

    return b""


def _decode_text(body: bytes, content_type: str, encoding: str | None = None) -> str:
    selected = encoding or "utf-8"
    if encoding is None and "charset=" in content_type.lower():
        try:
            selected = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        except Exception:
            selected = "utf-8"
    return body.decode(selected, errors="replace")


async def fetch_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
    max_redirects: int | None = None,
    max_bytes: int | None = None,
    allow_private: bool | None = None,
    validator: Callable[..., object] | None = None,
    session_factory: Callable[..., aiohttp.ClientSession] | None = None,
    raise_for_status: bool = True,
) -> HTTPFetchResult:
    """Fetch URL bytes with consistent redirect, timeout and size limits."""
    timeout_seconds = float(timeout_seconds or config.get("http_timeout_seconds", 8) or 8)
    max_redirects = int(max_redirects if max_redirects is not None else config.get("http_max_redirects", 5) or 5)
    max_bytes = int(max_bytes if max_bytes is not None else config.get("http_max_read_bytes", 1048576) or 1048576)
    allow_private = bool(config.get("allow_private_fetch_urls", False) if allow_private is None else allow_private)
    effective_headers = {"User-Agent": default_user_agent(), **(headers or {})}
    validator = validator or validate_fetch_url_async
    session_factory = session_factory or aiohttp.ClientSession

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    current_url = str(url)
    async with _session_from_factory(session_factory, timeout=timeout, headers=effective_headers) as session:
        for _ in range(max_redirects + 1):
            current_url = await validator(current_url, allow_private=allow_private)
            async with _session_get(session, current_url, timeout) as resp:
                status = int(getattr(resp, "status", 0) or 0)
                if status in REDIRECT_STATUSES:
                    location = _response_location(resp)
                    if not location:
                        raise UnsafeFetchURL("redirect response without Location header")
                    current_url = urljoin(_response_url(resp, current_url), location)
                    continue
                _maybe_raise_for_status(resp, raise_for_status=raise_for_status)
                return HTTPFetchResult(
                    body=await _read_limited_response(resp, max_bytes),
                    url=_response_url(resp, current_url),
                    content_type=_response_content_type(resp),
                    status=status,
                )
    raise UnsafeFetchURL("too many redirects")


async def fetch_text(
    url: str,
    *,
    encoding: str | None = None,
    **kwargs: Any,
) -> HTTPTextResult:
    """Fetch URL and decode the response body as text."""
    result = await fetch_bytes(url, **kwargs)
    return HTTPTextResult(
        text=_decode_text(result.body, result.content_type, encoding),
        url=result.url,
        content_type=result.content_type,
        status=result.status,
    )


async def fetch_json(url: str, **kwargs: Any) -> HTTPJsonResult:
    """Fetch URL and decode the response body as JSON."""
    result = await fetch_text(url, **kwargs)
    return HTTPJsonResult(
        data=json.loads(result.text or "null"),
        url=result.url,
        content_type=result.content_type,
        status=result.status,
    )
