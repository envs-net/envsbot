"""Safe, bounded TLS certificate diagnostics for HTTPS and XMPP S2S."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from contextlib import suppress
from urllib.parse import urlsplit
from xml.sax.saxutils import quoteattr


VALID_HTTPS_CERTIFICATE_MESSAGE = "TLS certificate is valid."
VALID_XMPP_CERTIFICATE_MESSAGE = "S2S TLS certificate is valid."


def parse_https_certificate_target(value: object) -> tuple[str, int]:
    """Return a normalized HTTPS hostname and the supported port 443."""
    target = str(value or "").strip()
    if not target:
        raise ValueError("Website cannot be empty")

    parsed = urlsplit(target if "://" in target else f"//{target}")
    if parsed.scheme and parsed.scheme.lower() != "https":
        raise ValueError("only HTTPS websites are supported")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("website URLs with credentials are not allowed")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("website must include a hostname")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError("website contains an invalid port") from exc
    if port != 443:
        raise ValueError("only HTTPS port 443 is supported")

    try:
        normalized = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("website hostname is invalid") from exc
    valid, error = validate_dns_hostname(normalized)
    if not valid:
        raise ValueError(error)
    return normalized, port


def domain_from_xmpp_target(value: object) -> str:
    """Extract and normalize the domain from a domain, JID or full JID."""
    target = str(value or "").strip()
    if "@" in target:
        target = target.split("@", 1)[1]
    return target.split("/", 1)[0].strip().lower()


def validate_dns_hostname(domain: str) -> tuple[bool, str]:
    """Validate a DNS hostname and return ``(is_valid, error_message)``."""
    if not domain or not domain.strip():
        return False, "Domain cannot be empty"

    domain = domain.strip().lower()
    if "." not in domain:
        return False, (
            f"'{domain}' is not a valid domain (must have at least one dot, "
            "e.g., example.com)"
        )

    labels = domain.split(".")
    for label in labels:
        if not label:
            return False, f"'{domain}' has empty labels (e.g., 'example..com')"
        if len(label) > 63:
            return False, (
                f"Label '{label}' in '{domain}' is too long (max 63 characters)"
            )
        if not all(character.isalnum() or character == "-" for character in label):
            return False, f"Label '{label}' contains invalid characters"
        if label.startswith("-") or label.endswith("-"):
            return False, f"Label '{label}' cannot start or end with hyphen"

    if len(labels[-1]) < 2:
        return False, f"'{domain}' has invalid TLD (must be at least 2 characters)"
    return True, ""


def validate_xmpp_domain(domain: str) -> tuple[bool, str]:
    """Validate an XMPP domain using the shared DNS hostname rules."""
    return validate_dns_hostname(domain)


def source_domain_from_jid(value: object) -> str:
    """Return a valid local XMPP domain or a safe syntactic fallback."""
    candidate = domain_from_xmpp_target(value)
    valid, _error = validate_xmpp_domain(candidate)
    return candidate if valid else "envsbot.invalid"


def make_srv_resolver(dns_resolver, timeout_seconds: float):
    """Create a DNS resolver with bounded per-query and total timeouts."""
    resolver = dns_resolver.Resolver()
    resolver.lifetime = timeout_seconds
    resolver.timeout = timeout_seconds
    return resolver


def _xmpp_server_endpoints(
    domain: str,
    timeout_seconds: float,
) -> list[tuple[str, int]]:
    """Return S2S SRV endpoints, falling back to the domain on port 5269."""
    try:
        import dns.exception
        import dns.resolver
    except ImportError:
        return [(domain, 5269)]

    try:
        resolver = make_srv_resolver(dns.resolver, timeout_seconds)
        answers = resolver.resolve(
            f"_xmpp-server._tcp.{domain}",
            "SRV",
            raise_on_no_answer=False,
        )
        records = sorted(
            (
                (
                    int(record.priority),
                    -int(record.weight),
                    str(record.target).rstrip("."),
                    int(record.port),
                )
                for record in (answers or [])
                if str(record.target).rstrip(".")
                and str(record.target).rstrip(".") != "."
            ),
            key=lambda record: (record[0], record[1]),
        )
        if records:
            return [(host, port) for _, _, host, port in records]
    except (dns.exception.DNSException, OSError, TypeError, ValueError):
        return [(domain, 5269)]
    return [(domain, 5269)]


def _public_endpoint_addresses(host: str, port: int) -> list[tuple[int, str]]:
    """Resolve an endpoint and retain only public unicast IP addresses."""
    addresses: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for family, socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
        host,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    ):
        if socktype != socket.SOCK_STREAM or family not in (
            socket.AF_INET,
            socket.AF_INET6,
        ):
            continue
        address = str(sockaddr[0])
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if not parsed.is_global:
            continue
        item = (family, address)
        if item not in seen:
            seen.add(item)
            addresses.append(item)
    return addresses[:4]


async def _read_xmpp_stream_part(
    reader,
    marker: bytes,
    *,
    limit: int = 65536,
) -> bytes:
    """Read a bounded portion of an XMPP stream up to a protocol marker."""
    data = bytearray()
    while marker not in data and len(data) < limit:
        chunk = await reader.read(min(4096, limit - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def _xmpp_probe_stream_header(domain: str, source_domain: str) -> str:
    """Build a pre-TLS S2S stream header suitable for certificate probes.

    RFC 6120 permits the initiating entity to omit ``from`` before TLS.  Do
    so for self-domain checks because servers commonly reject a stream whose
    pre-TLS source and target identities are identical before advertising
    STARTTLS.  Other probes retain their normal source identity.
    """
    source = domain_from_xmpp_target(source_domain)
    target = domain_from_xmpp_target(domain)
    from_attribute = "" if source == target else f" from={quoteattr(source)}"
    return (
        "<?xml version='1.0'?>"
        "<stream:stream xmlns='jabber:server' "
        "xmlns:stream='http://etherx.jabber.org/streams'"
        f"{from_attribute} "
        f"to={quoteattr(target)} version='1.0'>"
    )


def _certificate_verification_message(
    exc: ssl.SSLCertVerificationError,
    *,
    label: str,
    mismatch_target: str,
) -> str:
    """Return a concise operator-facing certificate verification result."""
    message = str(getattr(exc, "verify_message", "") or exc).strip()
    lowered = message.lower()
    if getattr(exc, "verify_code", None) == 10 or "expired" in lowered:
        return f"{label} has expired."
    if getattr(exc, "verify_code", None) == 9 or "not yet valid" in lowered:
        return f"{label} is not valid yet."
    if "hostname mismatch" in lowered or "not valid for" in lowered:
        return f"{label} does not match the {mismatch_target}."
    safe_message = " ".join(message.split())[:160].rstrip(".")
    if safe_message:
        return f"{label} validation failed: {safe_message}."
    return f"{label} validation failed."


async def _probe_https_certificate(
    address: str,
    family: int,
    hostname: str,
    port: int,
    timeout_seconds: float,
) -> str | None:
    """Open a verified direct TLS connection to one HTTPS endpoint."""
    writer = None
    try:
        context = ssl.create_default_context()
        _reader, writer = await asyncio.open_connection(
            host=address,
            port=port,
            family=family,
            ssl=context,
            server_hostname=hostname,
            ssl_handshake_timeout=timeout_seconds,
        )
        return VALID_HTTPS_CERTIFICATE_MESSAGE
    except ssl.SSLCertVerificationError as exc:
        return _certificate_verification_message(
            exc,
            label="TLS certificate",
            mismatch_target="requested domain",
        )
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        return None
    finally:
        if writer is not None:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()


async def diagnose_https_certificate(
    hostname: str,
    *,
    port: int = 443,
    timeout_seconds: float = 5.0,
) -> str | None:
    """Check one public HTTPS endpoint with normal CA and hostname validation."""
    hostname, parsed_port = parse_https_certificate_target(hostname)
    if port != parsed_port:
        raise ValueError("only HTTPS port 443 is supported")
    timeout_seconds = max(1.0, min(30.0, float(timeout_seconds)))
    try:
        async with asyncio.timeout(timeout_seconds):
            addresses = await asyncio.to_thread(
                _public_endpoint_addresses,
                hostname,
                port,
            )
            for family, address in addresses:
                result = await _probe_https_certificate(
                    address,
                    family,
                    hostname,
                    port,
                    timeout_seconds,
                )
                if result:
                    return result
    except (OSError, asyncio.TimeoutError, TypeError, ValueError):
        return None
    return None


async def _probe_xmpp_server_certificate(
    address: str,
    family: int,
    port: int,
    domain: str,
    source_domain: str,
    timeout_seconds: float,
) -> str | None:
    """Negotiate XMPP S2S STARTTLS and return a conclusive TLS result."""
    writer = None
    try:
        reader, writer = await asyncio.open_connection(
            host=address,
            port=port,
            family=family,
        )
        stream = _xmpp_probe_stream_header(domain, source_domain)
        writer.write(stream.encode("utf-8"))
        await writer.drain()
        features = await _read_xmpp_stream_part(reader, b"</stream:features>")
        lowered_features = features.lower()
        if b"<starttls" not in lowered_features or b"xmpp-tls" not in lowered_features:
            return None

        writer.write(b"<starttls xmlns='urn:ietf:params:xml:ns:xmpp-tls'/>")
        await writer.drain()
        response = await _read_xmpp_stream_part(reader, b">", limit=8192)
        if b"<proceed" not in response.lower():
            return None

        context = ssl.create_default_context()
        try:
            await writer.start_tls(
                context,
                server_hostname=domain,
                ssl_handshake_timeout=timeout_seconds,
            )
        except ssl.SSLCertVerificationError as exc:
            return _certificate_verification_message(
                exc,
                label="S2S TLS certificate",
                mismatch_target="XMPP domain",
            )
        return VALID_XMPP_CERTIFICATE_MESSAGE
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        return None
    finally:
        if writer is not None:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()


async def diagnose_xmpp_server_certificate(
    domain: str,
    *,
    source_domain: str,
    timeout_seconds: float = 5.0,
) -> str | None:
    """Run one bounded, public-network-only S2S certificate diagnosis."""
    domain = domain_from_xmpp_target(domain)
    valid, _error = validate_xmpp_domain(domain)
    if not valid:
        return None

    source_domain = source_domain_from_jid(source_domain)

    timeout_seconds = max(1.0, min(30.0, float(timeout_seconds)))
    try:
        async with asyncio.timeout(timeout_seconds):
            endpoints = await asyncio.to_thread(
                _xmpp_server_endpoints,
                domain,
                timeout_seconds,
            )
            for host, port in endpoints[:4]:
                if not 1 <= port <= 65535:
                    continue
                addresses = await asyncio.to_thread(
                    _public_endpoint_addresses,
                    host,
                    port,
                )
                for family, address in addresses:
                    result = await _probe_xmpp_server_certificate(
                        address,
                        family,
                        port,
                        domain,
                        source_domain,
                        timeout_seconds,
                    )
                    if result:
                        return result
    except (OSError, asyncio.TimeoutError, TypeError, ValueError):
        return None
    return None
