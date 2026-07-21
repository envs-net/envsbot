"""Shared async HTTP fetch helper with timeout, redirect and SSRF guardrails."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urljoin

import aiohttp

from utils.config import config
from utils.url_safety import (
    FetchURLTooLarge,
    UnsafeFetchURL,
    ValidatedFetchTarget,
    resolve_fetch_target_async,
    validate_fetch_url_async,
)

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class HTTPFetchResult:
    """Small immutable HTTP response payload."""

    body: bytes
    url: str
    content_type: str
    status: int


@dataclass(frozen=True)
class HTTPPreviewResult:
    """Partial HTTP response payload for metadata previews.

    ``truncated`` is true when the read stopped due to the configured byte
    limit before the response body ended. Callers should treat the body as a
    preview and never assume it contains a complete document.
    """

    body: bytes
    url: str
    content_type: str
    status: int
    content_length: int | None
    truncated: bool


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


class _PinnedResolver(aiohttp.abc.AbstractResolver):
    """Resolve one validated hostname only to its pre-approved addresses."""

    def __init__(self, target: ValidatedFetchTarget):
        self.target = target

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        if host.rstrip(".").lower() != self.target.hostname:
            raise OSError("resolver host differs from validated target")
        results = []
        for address in self.target.addresses:
            address_family = socket.AF_INET6 if ":" in address else socket.AF_INET
            if family not in {socket.AF_UNSPEC, address_family}:
                continue
            results.append({
                "hostname": host,
                "host": address,
                "port": port or self.target.port,
                "family": address_family,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            })
        if not results:
            raise OSError("validated target has no address for requested family")
        return results

    async def close(self) -> None:
        return None


def _pinned_connector(target: ValidatedFetchTarget) -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(
        resolver=_PinnedResolver(target),
        use_dns_cache=False,
        force_close=True,
    )


def _session_from_factory(
    session_factory: Callable[..., aiohttp.ClientSession],
    *,
    timeout: aiohttp.ClientTimeout,
    headers: dict[str, str],
    connector: aiohttp.BaseConnector | None = None,
):
    """Create a ClientSession while keeping tests with tiny fakes simple."""
    try:
        return session_factory(timeout=timeout, headers=headers, connector=connector)
    except TypeError:
        try:
            return session_factory(timeout=timeout)
        except TypeError:
            return session_factory()


def _session_get(session: aiohttp.ClientSession, url: str, timeout: aiohttp.ClientTimeout):
    """Call session.get with fallbacks for small test doubles."""
    try:
        return session.get(url, timeout=timeout, allow_redirects=False)
    except TypeError:
        return session.get(url, allow_redirects=False)


def _response_url(resp: aiohttp.ClientResponse, fallback_url: str) -> str:
    return str(getattr(resp, "url", fallback_url) or fallback_url)


def _response_headers(resp: aiohttp.ClientResponse) -> Mapping[str, str]:
    headers = getattr(resp, "headers", None)
    return headers if isinstance(headers, Mapping) else {}


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


def _content_length(resp: aiohttp.ClientResponse) -> int | None:
    value = _response_headers(resp).get("Content-Length")
    if value is None:
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


async def _read_preview_response(
    resp: aiohttp.ClientResponse,
    *,
    max_bytes: int,
    stop_when: Callable[[bytes], bool] | None = None,
) -> tuple[bytes, bool]:
    chunks = bytearray()
    content = getattr(resp, "content", None)
    if content is not None and hasattr(content, "iter_chunked"):
        async for chunk in content.iter_chunked(8192):
            chunks.extend(chunk)
            if len(chunks) >= max_bytes:
                clipped = bytes(chunks[:max_bytes])
                return clipped, not (stop_when and stop_when(clipped))
            if stop_when and stop_when(bytes(chunks)):
                return bytes(chunks), False
        return bytes(chunks), False

    text_reader = getattr(resp, "text", None)
    if callable(text_reader):
        data = (await text_reader()).encode("utf-8", errors="replace")
        truncated = len(data) > max_bytes
        return data[:max_bytes], truncated

    json_reader = getattr(resp, "json", None)
    if callable(json_reader):
        data = json.dumps(await json_reader()).encode("utf-8")
        truncated = len(data) > max_bytes
        return data[:max_bytes], truncated

    return b"", False


def _decode_text(body: bytes, content_type: str, encoding: str | None = None) -> str:
    selected = encoding or "utf-8"
    if encoding is None and "charset=" in content_type.lower():
        try:
            selected = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        except Exception:
            selected = "utf-8"
    return body.decode(selected, errors="replace")


async def _validated_hop(
    url: str,
    *,
    validator: Callable[..., object],
    allow_private: bool,
    session_factory: Callable[..., aiohttp.ClientSession],
) -> tuple[str, aiohttp.BaseConnector | None]:
    """Validate one redirect hop and optionally pin its DNS answers."""
    if validator is validate_fetch_url_async and not allow_private:
        target = await resolve_fetch_target_async(url, allow_private=False)
        connector = (
            _pinned_connector(target)
            if session_factory is aiohttp.ClientSession
            else None
        )
        return target.url, connector
    validated = await validator(url, allow_private=allow_private)
    return str(validated), None


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
    for _ in range(max_redirects + 1):
        current_url, connector = await _validated_hop(
            current_url,
            validator=validator,
            allow_private=allow_private,
            session_factory=session_factory,
        )
        async with _session_from_factory(
            session_factory,
            timeout=timeout,
            headers=effective_headers,
            connector=connector,
        ) as session:
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


async def fetch_preview(
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
    stop_when: Callable[[bytes], bool] | None = None,
) -> HTTPPreviewResult:
    """Fetch a small response preview without requiring the full body.

    This is intended for URL metadata/title extraction, where the interesting
    information is usually in the first part of a potentially large HTML page.
    The same redirect and SSRF rules as :func:`fetch_bytes` are applied.
    """
    timeout_seconds = float(timeout_seconds or config.get("http_timeout_seconds", 8) or 8)
    max_redirects = int(max_redirects if max_redirects is not None else config.get("http_max_redirects", 5) or 5)
    max_bytes = int(max_bytes if max_bytes is not None else config.get("http_max_read_bytes", 1048576) or 1048576)
    allow_private = bool(config.get("allow_private_fetch_urls", False) if allow_private is None else allow_private)
    effective_headers = {"User-Agent": default_user_agent(), **(headers or {})}
    validator = validator or validate_fetch_url_async
    session_factory = session_factory or aiohttp.ClientSession

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    current_url = str(url)
    for _ in range(max_redirects + 1):
        current_url, connector = await _validated_hop(
            current_url,
            validator=validator,
            allow_private=allow_private,
            session_factory=session_factory,
        )
        async with _session_from_factory(
            session_factory,
            timeout=timeout,
            headers=effective_headers,
            connector=connector,
        ) as session:
            async with _session_get(session, current_url, timeout) as resp:
                status = int(getattr(resp, "status", 0) or 0)
                if status in REDIRECT_STATUSES:
                    location = _response_location(resp)
                    if not location:
                        raise UnsafeFetchURL("redirect response without Location header")
                    current_url = urljoin(_response_url(resp, current_url), location)
                    continue
                _maybe_raise_for_status(resp, raise_for_status=raise_for_status)
                body, truncated = await _read_preview_response(
                    resp,
                    max_bytes=max_bytes,
                    stop_when=stop_when,
                )
                return HTTPPreviewResult(
                    body=body,
                    url=_response_url(resp, current_url),
                    content_type=_response_content_type(resp),
                    status=status,
                    content_length=_content_length(resp),
                    truncated=truncated,
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
        data=json.loads(result.text),
        url=result.url,
        content_type=result.content_type,
        status=result.status,
    )
