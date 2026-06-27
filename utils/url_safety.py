"""Helpers for safe outbound HTTP(S) fetches.

The bot fetches URLs that can be supplied by room users, for example RSS feeds
or URL titles.  Keep the shared safety checks here so plugins enforce the same
SSRF guardrails before opening network connections and again after redirects.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlparse


ALLOWED_FETCH_SCHEMES = frozenset({"http", "https"})
LOCALHOST_NAMES = frozenset({"localhost", "localhost.localdomain"})


class UnsafeFetchURL(ValueError):
    """Raised when a URL is not allowed for bot-managed HTTP fetching."""


class FetchURLTooLarge(ValueError):
    """Raised when an HTTP response exceeds the configured read limit."""


def _hostname(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme.lower() not in ALLOWED_FETCH_SCHEMES:
        raise UnsafeFetchURL("only http and https URLs are allowed")
    if not parsed.netloc or not parsed.hostname:
        raise UnsafeFetchURL("URL must include a hostname")
    return parsed.hostname.lower().rstrip(".")


def _ip_from_literal(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        return None


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True only for globally routable addresses."""
    is_global = getattr(ip, "is_global", None)
    if is_global is not None:
        return bool(is_global)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolved_ips(hostname: str, resolver=None) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    if resolver is None:
        try:
            infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise UnsafeFetchURL("hostname could not be resolved safely") from exc
        values: Iterable[str] = (info[4][0] for info in infos)
    else:
        values = resolver(hostname)

    ips = set()
    for value in values or ():
        try:
            ips.add(ipaddress.ip_address(str(value).strip("[]")))
        except ValueError:
            continue
    return ips


def validate_fetch_url(url: str, *, allow_private: bool = False, resolver=None) -> str:
    """Validate a user-supplied fetch URL and return the normalized string.

    When ``allow_private`` is false, loopback, private, link-local, multicast,
    unspecified and otherwise non-global addresses are rejected.  Hostnames are
    resolved before fetches so DNS names pointing to private networks are blocked
    too.  Tests can inject ``resolver`` to avoid real DNS.
    """
    url = str(url or "").strip()
    hostname = _hostname(url)

    if allow_private:
        return url

    if hostname in LOCALHOST_NAMES or hostname.endswith(".localhost"):
        raise UnsafeFetchURL("private or local network URLs are not allowed")

    literal_ip = _ip_from_literal(hostname)
    if literal_ip is not None:
        if not _is_public_ip(literal_ip):
            raise UnsafeFetchURL("private or local network URLs are not allowed")
        return url

    ips = _resolved_ips(hostname, resolver=resolver)
    if not ips:
        raise UnsafeFetchURL("hostname could not be resolved safely")

    if any(not _is_public_ip(ip) for ip in ips):
        raise UnsafeFetchURL("private or local network URLs are not allowed")

    return url


async def validate_fetch_url_async(
    url: str,
    *,
    allow_private: bool = False,
    resolver=None,
) -> str:
    """Async wrapper for :func:`validate_fetch_url`.

    The synchronous validation is run in a worker thread so command handlers do
    not block the event loop. If the default resolver path is used, DNS lookup
    also happens in that worker thread.
    """
    return await asyncio.to_thread(
        validate_fetch_url,
        url,
        allow_private=allow_private,
        resolver=resolver,
    )
