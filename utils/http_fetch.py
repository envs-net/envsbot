"""Shared async HTTP fetch helper with timeout, redirect and SSRF guardrails."""

from __future__ import annotations

import aiohttp
from dataclasses import dataclass
from urllib.parse import urljoin
from collections.abc import Callable

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


def default_user_agent() -> str:
    return str(
        config.get("http_user_agent")
        or "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)"
    )


async def _read_limited_response(resp: aiohttp.ClientResponse, max_bytes: int) -> bytes:
    chunks = bytearray()
    async for chunk in resp.content.iter_chunked(8192):
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise FetchURLTooLarge(f"response exceeds {max_bytes} bytes")
    return bytes(chunks)


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
    async with session_factory(timeout=timeout, headers=effective_headers) as session:
        for _ in range(max_redirects + 1):
            current_url = await validator(current_url, allow_private=allow_private)
            async with session.get(current_url, allow_redirects=False) as resp:
                if resp.status in REDIRECT_STATUSES:
                    location = resp.headers.get("Location")
                    if not location:
                        raise UnsafeFetchURL("redirect response without Location header")
                    current_url = urljoin(str(resp.url), location)
                    continue
                resp.raise_for_status()
                return HTTPFetchResult(
                    body=await _read_limited_response(resp, max_bytes),
                    url=str(resp.url),
                    content_type=resp.headers.get("Content-Type", ""),
                    status=resp.status,
                )
    raise UnsafeFetchURL("too many redirects")
