from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils import xmpp_certificate as certificate


def test_domain_extraction_and_validation():
    assert certificate.domain_from_xmpp_target(
        "Admin@Example.ORG/resource"
    ) == "example.org"
    assert certificate.validate_xmpp_domain("example.org") == (True, "")
    valid, message = certificate.validate_xmpp_domain("localhost")
    assert valid is False
    assert "at least one dot" in message
    assert certificate.source_domain_from_jid("bot@chat.example.org/resource") == (
        "chat.example.org"
    )
    assert certificate.source_domain_from_jid("") == "envsbot.invalid"


def test_certificate_verification_message_classifies_common_failures():
    assert certificate._certificate_verification_message(
        SimpleNamespace(verify_code=10, verify_message="certificate has expired")
    ) == "S2S TLS certificate has expired."
    assert certificate._certificate_verification_message(
        SimpleNamespace(verify_code=62, verify_message="Hostname mismatch")
    ) == "S2S TLS certificate does not match the XMPP domain."


def test_public_endpoint_addresses_filters_non_public_networks(monkeypatch):
    monkeypatch.setattr(
        certificate.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                certificate.socket.AF_INET,
                certificate.socket.SOCK_STREAM,
                6,
                "",
                ("8.8.8.8", 5269),
            ),
            (
                certificate.socket.AF_INET,
                certificate.socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1", 5269),
            ),
            (
                certificate.socket.AF_INET6,
                certificate.socket.SOCK_STREAM,
                6,
                "",
                ("::1", 5269, 0, 0),
            ),
        ],
    )

    assert certificate._public_endpoint_addresses("example.org", 5269) == [
        (certificate.socket.AF_INET, "8.8.8.8")
    ]


@pytest.mark.asyncio
async def test_certificate_probe_negotiates_xmpp_starttls(monkeypatch):
    class FakeReader:
        def __init__(self):
            self.responses = iter([
                b"".join((
                    b"<stream:features><starttls ",
                    b"xmlns='urn:ietf:params:xml:ns:xmpp-tls'/></stream:features>",
                )),
                b"<proceed xmlns='urn:ietf:params:xml:ns:xmpp-tls'/>",
            ])

        async def read(self, _size):
            return next(self.responses, b"")

    class FakeWriter:
        def __init__(self):
            self.writes = []
            self.tls_kwargs = None
            self.closed = False

        def write(self, data):
            self.writes.append(data)

        async def drain(self):
            return None

        async def start_tls(self, _context, **kwargs):
            self.tls_kwargs = kwargs

        def close(self):
            self.closed = True

        async def wait_closed(self):
            return None

    writer = FakeWriter()
    monkeypatch.setattr(
        certificate.asyncio,
        "open_connection",
        AsyncMock(return_value=(FakeReader(), writer)),
    )

    result = await certificate._probe_xmpp_server_certificate(
        "8.8.8.8",
        certificate.socket.AF_INET,
        5269,
        "example.org",
        "bot.example.org",
        5.0,
    )

    assert result == certificate.VALID_CERTIFICATE_MESSAGE
    assert b"<stream:stream" in writer.writes[0]
    assert b"from=\"bot.example.org\"" in writer.writes[0]
    assert b"<starttls" in writer.writes[1]
    assert writer.tls_kwargs["server_hostname"] == "example.org"
    assert writer.closed is True


@pytest.mark.asyncio
async def test_certificate_diagnosis_uses_resolved_public_endpoint(monkeypatch):
    async def immediate_to_thread(func, *args):
        return func(*args)

    monkeypatch.setattr(certificate.asyncio, "to_thread", immediate_to_thread)
    monkeypatch.setattr(
        certificate,
        "_xmpp_server_endpoints",
        lambda _domain, _timeout: [("s2s.example.org", 5269)],
    )
    monkeypatch.setattr(
        certificate,
        "_public_endpoint_addresses",
        lambda _host, _port: [
            (certificate.socket.AF_INET6, "2001:4860:4860::8888")
        ],
    )
    probe = AsyncMock(return_value="S2S TLS certificate has expired.")
    monkeypatch.setattr(certificate, "_probe_xmpp_server_certificate", probe)

    result = await certificate.diagnose_xmpp_server_certificate(
        "example.org",
        source_domain="bot.example.org",
        timeout_seconds=5.0,
    )

    assert result == "S2S TLS certificate has expired."
    probe.assert_awaited_once_with(
        "2001:4860:4860::8888",
        certificate.socket.AF_INET6,
        5269,
        "example.org",
        "bot.example.org",
        5.0,
    )
