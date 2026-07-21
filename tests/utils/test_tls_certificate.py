from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils import tls_certificate as certificate


def test_domain_extraction_and_validation():
    assert certificate.domain_from_xmpp_target(
        "Admin@Example.ORG/resource"
    ) == "example.org"
    assert certificate.validate_xmpp_domain("example.org") == (True, "")
    assert certificate.validate_dns_hostname("www.example.org") == (True, "")
    valid, message = certificate.validate_xmpp_domain("localhost")
    assert valid is False
    assert "at least one dot" in message
    assert certificate.source_domain_from_jid("bot@chat.example.org/resource") == (
        "chat.example.org"
    )
    assert certificate.source_domain_from_jid("") == "envsbot.invalid"


def test_parse_https_certificate_target():
    assert certificate.parse_https_certificate_target("Example.ORG/path") == (
        "example.org",
        443,
    )
    assert certificate.parse_https_certificate_target(
        "https://www.example.org/page?q=1"
    ) == ("www.example.org", 443)
    with pytest.raises(ValueError, match="only HTTPS"):
        certificate.parse_https_certificate_target("http://example.org")
    with pytest.raises(ValueError, match="port 443"):
        certificate.parse_https_certificate_target("https://example.org:8443")


def test_certificate_verification_message_classifies_common_failures():
    assert certificate._certificate_verification_message(
        SimpleNamespace(verify_code=10, verify_message="certificate has expired"),
        label="S2S TLS certificate",
        mismatch_target="XMPP domain",
    ) == "S2S TLS certificate has expired."
    assert certificate._certificate_verification_message(
        SimpleNamespace(verify_code=62, verify_message="Hostname mismatch"),
        label="S2S TLS certificate",
        mismatch_target="XMPP domain",
    ) == "S2S TLS certificate does not match the XMPP domain."
    assert certificate._certificate_verification_message(
        SimpleNamespace(verify_code=10, verify_message="certificate has expired"),
        label="TLS certificate",
        mismatch_target="requested domain",
    ) == "TLS certificate has expired."


def test_xmpp_probe_stream_omits_source_only_for_self_domain():
    remote = certificate._xmpp_probe_stream_header(
        "example.org",
        "bot.example.org",
    )
    own_domain = certificate._xmpp_probe_stream_header(
        "Example.ORG",
        "example.org",
    )

    assert 'from="bot.example.org"' in remote
    assert 'to="example.org"' in remote
    assert " from=" not in own_domain
    assert 'to="example.org"' in own_domain


@pytest.mark.asyncio
async def test_https_certificate_probe_uses_verified_direct_tls(monkeypatch):
    class FakeWriter:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

        async def wait_closed(self):
            return None

    writer = FakeWriter()
    connect = AsyncMock(return_value=(object(), writer))
    monkeypatch.setattr(certificate.asyncio, "open_connection", connect)

    result = await certificate._probe_https_certificate(
        "8.8.8.8",
        certificate.socket.AF_INET,
        "example.org",
        443,
        5.0,
    )

    assert result == certificate.VALID_HTTPS_CERTIFICATE_MESSAGE
    assert connect.await_args.kwargs["host"] == "8.8.8.8"
    assert connect.await_args.kwargs["server_hostname"] == "example.org"
    assert connect.await_args.kwargs["ssl"] is not None
    assert writer.closed is True


@pytest.mark.asyncio
async def test_https_certificate_diagnosis_uses_public_endpoint(monkeypatch):
    async def immediate_to_thread(func, *args):
        return func(*args)

    monkeypatch.setattr(certificate.asyncio, "to_thread", immediate_to_thread)
    monkeypatch.setattr(
        certificate,
        "_public_endpoint_addresses",
        lambda _host, _port: [(certificate.socket.AF_INET, "8.8.8.8")],
    )
    probe = AsyncMock(return_value=certificate.VALID_HTTPS_CERTIFICATE_MESSAGE)
    monkeypatch.setattr(certificate, "_probe_https_certificate", probe)

    result = await certificate.diagnose_https_certificate(
        "example.org",
        timeout_seconds=5.0,
    )

    assert result == certificate.VALID_HTTPS_CERTIFICATE_MESSAGE
    probe.assert_awaited_once_with(
        "8.8.8.8",
        certificate.socket.AF_INET,
        "example.org",
        443,
        5.0,
    )


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

    assert result == certificate.VALID_XMPP_CERTIFICATE_MESSAGE
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


@pytest.mark.parametrize(
    ("code", "message", "expected"),
    [
        (9, "certificate is not yet valid", "TLS certificate is not valid yet."),
        (62, "certificate is not valid for example.org", "TLS certificate does not match the requested domain."),
        (20, "unable to get local issuer certificate", "TLS certificate validation failed: unable to get local issuer certificate."),
        (None, "", "TLS certificate validation failed."),
    ],
)
def test_certificate_verification_message_all_branches(code, message, expected):
    assert certificate._certificate_verification_message(
        SimpleNamespace(verify_code=code, verify_message=message),
        label="TLS certificate",
        mismatch_target="requested domain",
    ) == expected


@pytest.mark.asyncio
async def test_xmpp_probe_requires_starttls_and_proceed(monkeypatch):
    class FakeReader:
        def __init__(self, responses):
            self.responses = iter(responses)

        async def read(self, _size):
            return next(self.responses, b"")

    class FakeWriter:
        def __init__(self):
            self.closed = False

        def write(self, _data):
            return None

        async def drain(self):
            return None

        async def start_tls(self, *_args, **_kwargs):
            raise AssertionError("TLS should not start")

        def close(self):
            self.closed = True

        async def wait_closed(self):
            return None

    no_starttls_writer = FakeWriter()
    monkeypatch.setattr(
        certificate.asyncio,
        "open_connection",
        AsyncMock(return_value=(FakeReader([b"<stream:features/>\n"]), no_starttls_writer)),
    )
    assert await certificate._probe_xmpp_server_certificate(
        "8.8.8.8", certificate.socket.AF_INET, 5269, "example.org", "bot.example.org", 5
    ) is None
    assert no_starttls_writer.closed is True

    rejected_writer = FakeWriter()
    monkeypatch.setattr(
        certificate.asyncio,
        "open_connection",
        AsyncMock(return_value=(FakeReader([
            b"<stream:features><starttls xmlns='urn:ietf:params:xml:ns:xmpp-tls'/></stream:features>",
            b"<failure xmlns='urn:ietf:params:xml:ns:xmpp-tls'/>",
        ]), rejected_writer)),
    )
    assert await certificate._probe_xmpp_server_certificate(
        "8.8.8.8", certificate.socket.AF_INET, 5269, "example.org", "bot.example.org", 5
    ) is None
    assert rejected_writer.closed is True


@pytest.mark.asyncio
async def test_xmpp_diagnosis_tries_next_endpoint_and_address(monkeypatch):
    async def immediate_to_thread(func, *args):
        return func(*args)

    monkeypatch.setattr(certificate.asyncio, "to_thread", immediate_to_thread)
    monkeypatch.setattr(
        certificate,
        "_xmpp_server_endpoints",
        lambda _domain, _timeout: [("bad.example.org", 5269), ("good.example.org", 5270)],
    )
    monkeypatch.setattr(
        certificate,
        "_public_endpoint_addresses",
        lambda host, _port: (
            [(certificate.socket.AF_INET, "8.8.8.8")]
            if host == "bad.example.org"
            else [(certificate.socket.AF_INET6, "2001:4860:4860::8888")]
        ),
    )
    probe = AsyncMock(side_effect=[None, certificate.VALID_XMPP_CERTIFICATE_MESSAGE])
    monkeypatch.setattr(certificate, "_probe_xmpp_server_certificate", probe)

    result = await certificate.diagnose_xmpp_server_certificate(
        "example.org", source_domain="bot.example.org", timeout_seconds=5
    )
    assert result == certificate.VALID_XMPP_CERTIFICATE_MESSAGE
    assert probe.await_count == 2
