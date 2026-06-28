"""Helpers for safe outbound HTTP(S) fetches.

The bot fetches URLs that can be supplied by room users, for example RSS feeds
or URL titles.  Keep the shared safety checks here so plugins enforce the same
SSRF guardrails before opening network connections and again after redirects.
"""

from __future__ import annotations

import asyncio
import functools
import ipaddress
import logging
import socket
from collections.abc import Callable, Iterable
from urllib.parse import ParseResult, urlparse


ALLOWED_FETCH_SCHEMES = frozenset({"http", "https"})
LOCALHOST_NAMES = frozenset({"localhost", "localhost.localdomain"})
Resolver = Callable[[str], Iterable[str]]
logger = logging.getLogger(__name__)


class UnsafeFetchURL(ValueError):
    """Raised when a URL is not allowed for bot-managed HTTP fetching."""


class FetchURLTooLarge(ValueError):
    """Raised when an HTTP response exceeds the configured read limit."""


def _parse_fetch_url(value: str) -> ParseResult:
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in ALLOWED_FETCH_SCHEMES:
        raise UnsafeFetchURL("only http and https URLs are allowed")
    if not parsed.netloc or not parsed.hostname:
        raise UnsafeFetchURL("URL must include a hostname")
    return parsed


def _ip_from_literal(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        return None


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True only for globally routable addresses.

    Args:
        ip: ``ipaddress.IPv4Address`` or ``ipaddress.IPv6Address`` instance
            to evaluate for public routability.

    Prefer ``ip.is_global`` when available. The guard keeps this helper
    compatible with runtimes or non-standard ``ipaddress``-like objects that do
    not expose that attribute. The fallback stays conservative by rejecting
    every range that must not be fetched by public bot commands.
    """
    if hasattr(ip, "is_global"):
        return ip.is_global

    # Compatibility fallback for address objects without ``is_global``.
    # Treat only clearly public addresses as fetchable and keep special-use
    # ranges blocked.  Use getattr for ``is_reserved`` so older/non-standard
    # address-like objects remain conservatively supported.
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or getattr(ip, "is_reserved", False)
    )


def _hosts_from_addrinfo(
    addrinfos: Iterable[tuple[object, object, object, object, tuple[object, ...]]],
) -> tuple[object, ...]:
    hosts = []
    for _family, _socktype, _proto, _canonname, sockaddr in addrinfos:
        if sockaddr:
            hosts.append(sockaddr[0])
    return tuple(hosts)


def _resolved_ips(
    hostname: str,
    resolver: Resolver | None = None,
) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    if resolver is None:
        try:
            # socket.getaddrinfo() names this parameter ``type``; use
            # positional arguments here to avoid shadowing/confusion warnings.
            infos = socket.getaddrinfo(
                hostname,
                None,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise UnsafeFetchURL("DNS resolution failed for hostname") from exc
        values = _hosts_from_addrinfo(infos)
        if not values:
            raise UnsafeFetchURL("hostname could not be resolved safely")
    else:
        values = tuple(resolver(hostname) or ())
        if not values:
            raise UnsafeFetchURL("hostname resolver returned no results")

    ips = set()
    for value in values:
        try:
            ips.add(ipaddress.ip_address(str(value).strip("[]")))
        except ValueError:
            logger.warning(
                "resolver returned invalid IP address value for hostname %r: %r",
                hostname,
                value,
            )
            continue

    if not ips:
        raise UnsafeFetchURL("all resolved IP addresses were invalid")

    return ips


def validate_fetch_url(
    url: str | None,
    *,
    allow_private: bool = False,
    resolver: Resolver | None = None,
) -> str:
    """Validate a user-supplied fetch URL and return the normalized string.

    When ``allow_private`` is false, loopback, private, link-local, multicast,
    unspecified and otherwise non-global addresses are rejected.  Hostnames are
    resolved before fetches so DNS names pointing to private networks are blocked
    too.  This is a pre-flight validation step, not a guarantee about the
    eventual connection target: DNS answers can change between validation and
    connect.  Callers must validate immediately before each outbound request and
    before following every redirect target.  Tests can inject ``resolver`` to
    avoid real DNS.
    """
    if url is None:
        url = ""
    else:
        url = str(url).strip()

    parsed = _parse_fetch_url(url)
    parsed_hostname = parsed.hostname
    if parsed_hostname is None:
        raise UnsafeFetchURL("URL must include a hostname")
    hostname = parsed_hostname.lower().rstrip(".")

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

    if any(not _is_public_ip(ip) for ip in ips):
        raise UnsafeFetchURL("private or local network URLs are not allowed")

    return url


def validate_fetch_redirect_chain(
    urls: Iterable[str],
    *,
    allow_private: bool = False,
    resolver: Resolver | None = None,
) -> list[str]:
    """Validate each URL hop in a fetch or redirect chain.

    This helper enforces per-hop validation so callers can safely validate the
    initial request URL and each redirect target before following it.
    """
    return [
        validate_fetch_url(url, allow_private=allow_private, resolver=resolver)
        for url in urls
    ]


async def validate_fetch_url_async(
    url: str | None,
    *,
    allow_private: bool = False,
    resolver: Resolver | None = None,
) -> str:
    """Async wrapper for :func:`validate_fetch_url`.

    The synchronous validation is run in a worker thread so command handlers do
    not block the event loop. If the default resolver path is used, DNS lookup
    also happens in that worker thread.
    """
    func = functools.partial(
        validate_fetch_url,
        url,
        allow_private=allow_private,
        resolver=resolver,
    )
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func)
