"""Safe, bounded TLS certificate diagnostics for HTTPS and XMPP S2S."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import ssl
import tempfile
import time
from contextlib import suppress
from urllib.parse import urlsplit
from xml.sax.saxutils import quoteattr


VALID_HTTPS_CERTIFICATE_MESSAGE = "TLS certificate is valid."
VALID_XMPP_CERTIFICATE_MESSAGE = "S2S TLS certificate is valid."
MAX_CERTIFICATE_ENDPOINT_ADDRESSES = 4


def _format_certificate_duration(seconds: float) -> str:
    """Return a compact two-unit duration for certificate validity output."""
    remaining = max(0, int(seconds))
    parts: list[str] = []
    for size, suffix in ((86400, "d"), (3600, "h"), (60, "m"), (1, "s")):
        value, remaining = divmod(remaining, size)
        if value or (suffix == "s" and not parts):
            parts.append(f"{value}{suffix}")
        if len(parts) == 2:
            break
    return " ".join(parts)


def _format_certificate_timestamp(timestamp: float) -> str:
    """Format a certificate timestamp consistently in UTC."""
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(timestamp))


def _certificate_validity_details(
    certificate: dict | None,
    *,
    now: float | None = None,
) -> str:
    """Describe how long a peer certificate is valid, expired or pending."""
    if not certificate:
        return ""

    try:
        not_after = ssl.cert_time_to_seconds(str(certificate["notAfter"]))
    except (KeyError, TypeError, ValueError, ssl.SSLError):
        return ""

    current = time.time() if now is None else float(now)
    not_before = None
    try:
        raw_not_before = certificate.get("notBefore")
        if raw_not_before:
            not_before = ssl.cert_time_to_seconds(str(raw_not_before))
    except (TypeError, ValueError, ssl.SSLError):
        not_before = None

    if not_before is not None and current < not_before:
        duration = _format_certificate_duration(not_before - current)
        starts = _format_certificate_timestamp(not_before)
        return f"Valid in {duration} (from {starts})."

    if current <= not_after:
        duration = _format_certificate_duration(not_after - current)
        expires = _format_certificate_timestamp(not_after)
        return f"Valid for another {duration} (until {expires})."

    duration = _format_certificate_duration(current - not_after)
    expired = _format_certificate_timestamp(not_after)
    return f"Expired {duration} ago (on {expired})."


def _append_certificate_validity(
    message: str,
    certificate: dict | None,
) -> str:
    """Append peer-certificate lifetime details when they are available."""
    details = _certificate_validity_details(certificate)
    return f"{message} {details}" if details else message


def _decode_der_certificate(certificate_der: bytes) -> dict | None:
    """Decode a DER certificate with Python's bundled certificate parser."""
    decoder = getattr(getattr(ssl, "_ssl", None), "_test_decode_cert", None)
    if not callable(decoder) or not certificate_der:
        return None

    path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="ascii",
            suffix=".pem",
            delete=False,
        ) as certificate_file:
            path = certificate_file.name
            certificate_file.write(ssl.DER_cert_to_PEM_cert(certificate_der))
        decoded = decoder(path)
        return decoded if isinstance(decoded, dict) else None
    except (OSError, ValueError, ssl.SSLError):
        return None
    finally:
        if path:
            with suppress(OSError):
                os.unlink(path)


def _peer_certificate_from_writer(writer) -> dict | None:
    """Return the parsed peer certificate from an asyncio TLS writer."""
    get_extra_info = getattr(writer, "get_extra_info", None)
    if not callable(get_extra_info):
        return None
    ssl_object = get_extra_info("ssl_object")
    if ssl_object is None:
        return None

    try:
        certificate = ssl_object.getpeercert()
    except (AttributeError, OSError, ValueError, ssl.SSLError):
        certificate = None
    if isinstance(certificate, dict) and certificate:
        return certificate

    try:
        certificate_der = ssl_object.getpeercert(binary_form=True)
    except (AttributeError, OSError, ValueError, ssl.SSLError):
        return None
    return _decode_der_certificate(certificate_der)


async def _close_writer(writer) -> None:
    """Close an asyncio stream writer without masking probe results."""
    if writer is None:
        return
    writer.close()
    with suppress(Exception):
        await writer.wait_closed()


def _unverified_tls_context() -> ssl.SSLContext:
    """Create a client TLS context used only to inspect a rejected peer cert."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def parse_https_certificate_target(value: object) -> tuple[str, int]:
    """Return a normalized HTTPS hostname and TCP port.

    Bare domains default to port 443. Explicit HTTPS ports are accepted as
    long as they are valid TCP ports.
    """
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
    authority = parsed.netloc.rsplit("@", 1)[-1]
    if authority.endswith(":"):
        raise ValueError("website contains an invalid port")
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError("website contains an invalid port") from exc
    port = 443 if parsed_port is None else parsed_port
    if not 1 <= port <= 65535:
        raise ValueError("website port must be between 1 and 65535")

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


def _public_address_from_addrinfo(entry: tuple) -> tuple[int, str] | None:
    """Normalize one ``getaddrinfo`` entry to a public stream endpoint."""
    try:
        family = entry[0]
        socktype = entry[1]
        sockaddr = entry[4]
        address = str(sockaddr[0])
    except (IndexError, TypeError, ValueError):
        return None
    if socktype != socket.SOCK_STREAM or family not in (
        socket.AF_INET,
        socket.AF_INET6,
    ):
        return None
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return None
    if not parsed.is_global:
        return None
    return family, address


def _public_endpoint_addresses(host: str, port: int) -> list[tuple[int, str]]:
    """Resolve an endpoint and retain only public unicast IP addresses."""
    addresses: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    entries = socket.getaddrinfo(
        host,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    for entry in entries:
        item = _public_address_from_addrinfo(entry)
        if item is None or item in seen:
            continue
        seen.add(item)
        addresses.append(item)
        if len(addresses) == MAX_CERTIFICATE_ENDPOINT_ADDRESSES:
            break
    return addresses


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
    verify_message = getattr(exc, "verify_message", None)
    message = (str(exc) if verify_message is None else str(verify_message)).strip()
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
        return _append_certificate_validity(
            VALID_HTTPS_CERTIFICATE_MESSAGE,
            _peer_certificate_from_writer(writer),
        )
    except ssl.SSLCertVerificationError as exc:
        message = _certificate_verification_message(
            exc,
            label="TLS certificate",
            mismatch_target="requested domain",
        )
        certificate = await _probe_unverified_https_certificate(
            address,
            family,
            hostname,
            port,
            timeout_seconds,
        )
        return _append_certificate_validity(message, certificate)
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        return None
    finally:
        await _close_writer(writer)


async def _probe_unverified_https_certificate(
    address: str,
    family: int,
    hostname: str,
    port: int,
    timeout_seconds: float,
) -> dict | None:
    """Reconnect without verification to inspect a rejected HTTPS cert."""
    writer = None
    try:
        _reader, writer = await asyncio.open_connection(
            host=address,
            port=port,
            family=family,
            ssl=_unverified_tls_context(),
            server_hostname=hostname,
            ssl_handshake_timeout=timeout_seconds,
        )
        return _peer_certificate_from_writer(writer)
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        return None
    finally:
        await _close_writer(writer)


async def diagnose_https_certificate(
    hostname: str,
    *,
    port: int | None = None,
    timeout_seconds: float = 5.0,
) -> str | None:
    """Check one public HTTPS endpoint with normal CA and hostname validation."""
    raw_target = str(hostname or "").strip()
    parsed_target = urlsplit(
        raw_target if "://" in raw_target else f"//{raw_target}"
    )
    try:
        target_has_explicit_port = parsed_target.port is not None
    except ValueError as exc:
        raise ValueError("website contains an invalid port") from exc

    hostname, parsed_port = parse_https_certificate_target(raw_target)
    if port is None:
        port = parsed_port
    else:
        if not isinstance(port, int) or isinstance(port, bool):
            raise ValueError("website port must be between 1 and 65535")
        if not 1 <= port <= 65535:
            raise ValueError("website port must be between 1 and 65535")
        if target_has_explicit_port and port != parsed_port:
            raise ValueError("website target and port argument disagree")

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


async def _open_xmpp_starttls_writer(
    address: str,
    family: int,
    port: int,
    domain: str,
    source_domain: str,
    timeout_seconds: float,
    context: ssl.SSLContext,
):
    """Negotiate XMPP S2S STARTTLS and return the upgraded writer."""
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
            await _close_writer(writer)
            return None

        writer.write(b"<starttls xmlns='urn:ietf:params:xml:ns:xmpp-tls'/>")
        await writer.drain()
        response = await _read_xmpp_stream_part(reader, b">", limit=8192)
        if b"<proceed" not in response.lower():
            await _close_writer(writer)
            return None

        await writer.start_tls(
            context,
            server_hostname=domain,
            ssl_handshake_timeout=timeout_seconds,
        )
        return writer
    except Exception:
        await _close_writer(writer)
        raise


async def _probe_unverified_xmpp_server_certificate(
    address: str,
    family: int,
    port: int,
    domain: str,
    source_domain: str,
    timeout_seconds: float,
) -> dict | None:
    """Reconnect with STARTTLS without verification to inspect a rejected cert."""
    writer = None
    try:
        writer = await _open_xmpp_starttls_writer(
            address,
            family,
            port,
            domain,
            source_domain,
            timeout_seconds,
            _unverified_tls_context(),
        )
        return _peer_certificate_from_writer(writer) if writer is not None else None
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        return None
    finally:
        await _close_writer(writer)


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
        try:
            writer = await _open_xmpp_starttls_writer(
                address,
                family,
                port,
                domain,
                source_domain,
                timeout_seconds,
                ssl.create_default_context(),
            )
        except ssl.SSLCertVerificationError as exc:
            message = _certificate_verification_message(
                exc,
                label="S2S TLS certificate",
                mismatch_target="XMPP domain",
            )
            certificate = await _probe_unverified_xmpp_server_certificate(
                address,
                family,
                port,
                domain,
                source_domain,
                timeout_seconds,
            )
            return _append_certificate_validity(message, certificate)

        if writer is None:
            return None
        return _append_certificate_validity(
            VALID_XMPP_CERTIFICATE_MESSAGE,
            _peer_certificate_from_writer(writer),
        )
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        return None
    finally:
        await _close_writer(writer)


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
