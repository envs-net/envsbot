import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import plugins.xmpp as xmpp


@pytest.fixture
def bot():
    """Mocked bot with plugin submodules and DB mock."""
    bot = MagicMock()
    bot.plugin = {
        "xep_0092": AsyncMock(),
        "xep_0012": AsyncMock(),
        "xep_0030": AsyncMock(),
        "xep_0199": AsyncMock(),
    }
    bot.db = MagicMock()
    bot.db.users.plugin.return_value.get_global = AsyncMock(return_value={})
    bot.reply = MagicMock()
    return bot


@pytest.fixture
def msg():
    """Factory fixture: build mocked message with minimal room/PM attributes."""

    def _make_msg(is_room=False):
        m = MagicMock()
        from_jid = MagicMock()
        from_jid.bare = "room@muc.example"
        from_jid.resource = "Nick"
        from_jid.__str__ = lambda *a: "room@muc.example/Nick"
        values = {
            "from": from_jid,
            "type": "groupchat" if is_room else "chat",
        }
        m.__getitem__.side_effect = lambda k: values[k]
        m.get.side_effect = lambda k, default=None: values.get(k, default)
        m.body = ""
        return m

    return _make_msg


@pytest.mark.asyncio
async def test_cmd_xmpp_toggle_on_off_status(bot, msg):
    # on/off/status delegated to handle_room_toggle_command
    with patch("plugins.xmpp.handle_room_toggle_command",
               new=AsyncMock(return_value=True)):
        for args in (["on"], ["off"], ["status"]):
            m = msg()
            await xmpp.cmd_xmpp(bot, "you@server", "nick", args, m, False)
            bot.reply.assert_not_called()
    # Unhandled returns usage
    with patch("plugins.xmpp.handle_room_toggle_command",
               new=AsyncMock(return_value=False)):
        m = msg()
        await xmpp.cmd_xmpp(bot, "you@server", "nick", [], m, False)
        bot.reply.assert_called_once()
        assert "Usage" in bot.reply.call_args[0][1]


@pytest.mark.asyncio
async def test_cmd_xmpp_help_allowed(bot, msg):
    m = msg()
    bot.db.users.plugin.return_value.get_global = AsyncMock(
        return_value={"room@muc.example": True})
    await xmpp.cmd_xmpp_help(bot, "jid", "nick", [], m, True)
    bot.reply.assert_called()
    assert "XMPP Utility Commands" in bot.reply.call_args[0][1]


@pytest.mark.asyncio
async def test_cmd_xmpp_help_denied(bot, msg):
    m = msg()
    bot.db.users.plugin.return_value.get_global = AsyncMock(return_value={})
    await xmpp.cmd_xmpp_help(bot, "jid", "nick", [], m, True)
    bot.reply.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_xmpp_version_success(bot, msg):
    m = msg()
    bot.db.users.plugin.return_value.get_global = AsyncMock(
        return_value={"room@muc.example": True})
    bot.plugin["xep_0092"].get_version.return_value.xml = [
        MagicMock(tag="{jabber:iq:version}query", __iter__=lambda self: iter([
            MagicMock(tag="{jabber:iq:version}name", text="Prosody"),
            MagicMock(tag="{jabber:iq:version}version", text="0.11.x"),
            MagicMock(tag="{jabber:iq:version}os", text="Debian Linux"),
        ]))
    ]
    await xmpp.cmd_xmpp_version(bot, "jid", "nick", ["example.org"], m, True)
    bot.reply.assert_called_with(
        m, "ℹ️ Version for example.org: **Prosody** v0.11.x"
        " on Debian Linux")


@pytest.mark.asyncio
async def test_cmd_xmpp_version_error(bot, msg):
    m = msg()
    # Invalid domain, missing domain, IqTimeout, IqError, Exception
    bot.db.users.plugin.return_value.get_global = AsyncMock(
        return_value={"room@muc.example": True})
    await xmpp.cmd_xmpp_version(bot, "jid", "nick", [], m, True)
    bot.reply.assert_called_with(m, "❌ Missing domain")
    bot.reply.reset_mock()
    await xmpp.cmd_xmpp_version(bot, "jid", "nick", ["foo"], m, True)
    # 'foo' is not valid domain; error returned
    assert any("not a valid domain" in c[0][1]
               for c in bot.reply.call_args_list)
    bot.reply.reset_mock()
    # Simulate timeout
    bot.plugin["xep_0092"].get_version.side_effect = asyncio.TimeoutError()
    await xmpp.cmd_xmpp_version(bot, "jid", "nick", ["example.com"], m, True)
    bot.reply.assert_called()
    # Simulate IqError
    from slixmpp.exceptions import IqError
    error_dict = {
        'error': {'condition': 'service-unavailable', 'text': '', 'type': ''}}
    bot.plugin["xep_0092"].get_version.side_effect = IqError(error_dict)
    await xmpp.cmd_xmpp_version(bot, "jid", "nick", ["example.com"], m, True)
    # Simulate Exception
    bot.plugin["xep_0092"].get_version.side_effect = Exception("fail")
    await xmpp.cmd_xmpp_version(bot, "jid", "nick", ["example.com"], m, True)
    bot.reply.assert_called()


@pytest.mark.asyncio
async def test_cmd_xmpp_version_diagnoses_expired_s2s_certificate(
    monkeypatch,
    bot,
    msg,
):
    class FakeIqError(Exception):
        def __init__(self):
            self.iq = {"error": {"condition": "remote-server-timeout"}}

    m = msg()
    bot.db.users.plugin.return_value.get_global = AsyncMock(
        return_value={"room@muc.example": True}
    )
    bot.plugin["xep_0092"].get_version = AsyncMock(side_effect=FakeIqError())
    diagnose = AsyncMock(return_value="S2S TLS certificate has expired.")
    monkeypatch.setattr(xmpp.slixmpp.exceptions, "IqError", FakeIqError)
    monkeypatch.setattr(xmpp, "_diagnose_xmpp_server_certificate", diagnose)

    await xmpp.cmd_xmpp_version(
        bot,
        "jid",
        "nick",
        ["example.org"],
        m,
        True,
    )

    diagnose.assert_awaited_once_with("example.org")
    bot.reply.assert_called_once_with(
        m,
        "🔴 Version request failed: remote-server-timeout\n"
        "🔐 S2S TLS certificate has expired.",
    )


@pytest.mark.asyncio
async def test_cmd_xmpp_uptime_success(bot, msg):
    m = msg()
    bot.db.users.plugin.return_value.get_global = AsyncMock(
        return_value={"room@muc.example": True})
    bot.plugin["xep_0012"].get_last_activity.return_value = {
        'last_activity': {'seconds': 3661}}
    await xmpp.cmd_xmpp_uptime(bot, "jid", "nick", ["example.org"], m, True)
    bot.reply.assert_called()
    assert "Uptime for example.org" in bot.reply.call_args[0][1]


@pytest.mark.asyncio
async def test_cmd_xmpp_items_and_info(bot, msg):
    m = msg()
    bot.db.users.plugin.return_value.get_global = AsyncMock(
        return_value={"room@muc.example": True})
    bot.plugin["xep_0030"].get_items.return_value = {
        'disco_items': {'items': [("room@conf", "A room")]}}
    await xmpp.cmd_xmpp_items(bot, "jid", "nick", ["xmpp.org"], m, True)
    bot.reply.assert_called()
    assert "Items for" in bot.reply.call_args[0][1]
    # Info with identities/features
    bot.plugin["xep_0030"].get_info.return_value = {
        'disco_info': {
            'identities': [('server', 'im', 'XMPPServer')],
            'features': ['urn:xmpp:ping', 'urn:xmpp:mam'],
        }
    }
    await xmpp.cmd_xmpp_info(bot, "jid", "nick", ["xmpp.org"], m, True)
    bot.reply.assert_called()
    assert "Identities" in bot.reply.call_args[0][1]


@pytest.mark.asyncio
async def test_cmd_xmpp_contact(bot, msg):
    m = msg()
    bot.db.users.plugin.return_value.get_global = AsyncMock(
        return_value={"room@muc.example": True})
    # XEP-0030 info with form and contact
    bot.plugin["xep_0030"].get_info.return_value = {
        'disco_info': {
            'form': [
                {'var': 'admin-address', 'value': ['admin@host']},
                {'var': 'abuse-address', 'value': ['abuse@host']}
            ]
        }
    }
    await xmpp.cmd_xmpp_contact(bot, "jid", "nick", ["xmpp.org"], m, True)
    bot.reply.assert_called()
    assert "Contact info" in bot.reply.call_args[0][1]


@pytest.mark.asyncio
async def test_cmd_xmpp_ping(bot, msg):
    m = msg()
    bot.db.users.plugin.return_value.get_global = AsyncMock(
        return_value={"room@muc.example": True})
    bot.plugin["xep_0199"].ping = AsyncMock(return_value=None)
    await xmpp.cmd_xmpp_ping(bot, "jid", "nick", ["xmpp.org"], m, True)
    bot.reply.assert_called()
    assert "Pong" in bot.reply.call_args[0][1]


@pytest.mark.asyncio
async def test_cmd_xmpp_srv(monkeypatch, bot, msg):
    m = msg()
    bot.db.users.plugin.return_value.get_global = AsyncMock(
        return_value={"room@muc.example": True})

    class FakeTarget:
        def __str__(self):
            return "xmpp.example.org."

    class FakeRecord:
        target = FakeTarget()
        port = 5222
        priority = 5
        weight = 10

    class FakeResolver:
        def __init__(self):
            self.calls = []

        def resolve(self, name, rdtype, raise_on_no_answer=False):
            self.calls.append((name, rdtype, raise_on_no_answer))
            if name == "_xmpp-client._tcp.example.org":
                return [FakeRecord()]
            return []

    fake_resolver = FakeResolver()
    to_thread_calls = []

    def fake_make_srv_resolver(_dns_resolver, timeout_seconds):
        assert timeout_seconds == xmpp.XMPP_QUERY_TIMEOUT_SECONDS
        return fake_resolver

    async def fake_to_thread(fn, *args, **kwargs):
        to_thread_calls.append((fn, args, kwargs))
        return fn(*args, **kwargs)

    monkeypatch.setattr(xmpp, "_make_srv_resolver", fake_make_srv_resolver)
    monkeypatch.setattr(xmpp.asyncio, "to_thread", fake_to_thread)

    await xmpp.cmd_xmpp_srv(bot, "jid", "nick", ["example.org"], m, True)

    bot.reply.assert_called()
    reply_text = bot.reply.call_args[0][1]
    reply_lines = {line.strip() for line in reply_text.splitlines()}
    assert "xmpp.example.org:5222 (priority=5, weight=10)" in reply_lines
    assert [call[0] for call in fake_resolver.calls] == [
        "_xmpp-client._tcp.example.org",
        "_xmpp-server._tcp.example.org",
        "_xmpps-client._tcp.example.org",
        "_xmpps-server._tcp.example.org",
    ]
    assert to_thread_calls


def test_make_srv_resolver_sets_timeouts():
    class FakeDNSResolver:
        class Resolver:
            def __init__(self):
                self.lifetime = None
                self.timeout = None

    resolver = xmpp._make_srv_resolver(FakeDNSResolver, 3.5)

    assert isinstance(resolver, FakeDNSResolver.Resolver)
    assert resolver.lifetime == 3.5
    assert resolver.timeout == 3.5


@pytest.mark.asyncio
async def test_cmd_xmpp_compliance(bot, msg):
    m = msg()
    bot.db.users.plugin.return_value.get_global = AsyncMock(
        return_value={"room@muc.example": True})
    fetch_kwargs = {}

    async def fake_fetch_preview(url, **kwargs):
        fetch_kwargs.update(kwargs)
        body = b'<html><span class="stat_result">110/120</span></html>'
        return SimpleNamespace(status=200, body=body)

    class FakeSoup:
        def find(self, *a, **kw):
            class Score:
                def get_text(self, **_): return "110/120"
            return Score()

    with patch.object(xmpp, "fetch_preview", fake_fetch_preview), \
            patch("bs4.BeautifulSoup", return_value=FakeSoup()):
        await xmpp.cmd_xmpp_compliance(bot, "jid", "nick",
                                       ["conversations.im"], m, True)
        bot.reply.assert_called()
        assert "Compliance score" in "".join(
            str(a) for a in bot.reply.call_args[0])
        assert fetch_kwargs["max_bytes"] == xmpp.XMPP_COMPLIANCE_MAX_READ_BYTES
        assert fetch_kwargs["stop_when"] is xmpp._compliance_preview_complete


def test_compliance_preview_stops_on_score_marker_or_end():
    assert xmpp._compliance_preview_complete(b'<div class="stat_result">')
    assert xmpp._compliance_preview_complete(b"<html></html>")
    assert not xmpp._compliance_preview_complete(b"<html><body>")


@pytest.mark.asyncio
async def test_permission_denied(bot, msg):
    m = msg()
    # If room/plugin not enabled, should not reply
    bot.db.users.plugin.return_value.get_global = AsyncMock(return_value={})
    funcs = [
        xmpp.cmd_xmpp_help, xmpp.cmd_xmpp_version, xmpp.cmd_xmpp_uptime,
        xmpp.cmd_xmpp_items, xmpp.cmd_xmpp_contact, xmpp.cmd_xmpp_info,
        xmpp.cmd_xmpp_ping, xmpp.cmd_xmpp_srv, xmpp.cmd_xmpp_compliance
    ]
    for func in funcs:
        bot.reply.reset_mock()
        await func(bot, "jid", "nick", ["example.com"], m, True)
        bot.reply.assert_not_called()


def test_xmpp_direct_error_reply_helpers(monkeypatch, bot, msg):
    m = msg()

    class FakeTimeout(Exception):
        pass

    class FakeIqError(Exception):
        def __init__(self, condition="unknown"):
            super().__init__(condition)
            self.iq = {"error": {"condition": condition}}

    monkeypatch.setattr(
        xmpp.slixmpp.exceptions, "IqTimeout", FakeTimeout, raising=False
    )
    monkeypatch.setattr(
        xmpp.slixmpp.exceptions, "IqError", FakeIqError, raising=False
    )

    xmpp._reply_xmpp_info_error(bot, m, "example.org", FakeTimeout())
    assert "timed out" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    xmpp._reply_xmpp_info_error(
        bot, m, "example.org", FakeIqError("service-unavailable")
    )
    assert "does not support" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    xmpp._reply_xmpp_info_error(bot, m, "example.org", FakeIqError("gone"))
    assert "gone" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    xmpp._reply_xmpp_info_error(bot, m, "example.org", RuntimeError("boom"))
    assert "boom" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    xmpp._reply_xmpp_contact_iq_error(
        bot, m, "example.org", FakeIqError("service-unavailable")
    )
    assert "does not support" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    xmpp._reply_xmpp_contact_iq_error(
        bot, m, "example.org", FakeIqError("gone")
    )
    assert "gone" in bot.reply.call_args[0][1]


def test_xmpp_srv_reply_helpers(bot, msg):
    m = msg()

    xmpp._reply_xmpp_srv_missing_domain(bot, m)
    assert "Missing domain" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    xmpp._reply_xmpp_srv_invalid_domain(bot, m, "bad label")
    assert "bad label" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    xmpp._reply_xmpp_srv_jid_notice(bot, m, "example.org", "user@example.org")
    assert "Using 'example.org'" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    xmpp._reply_xmpp_srv_dns_missing(bot, m)
    assert "DNS library not installed" in bot.reply.call_args[0][1]


def test_xmpp_feature_summary_known_features():
    assert xmpp._xmpp_feature_summary([
        "urn:xmpp:ping",
        "http://jabber.org/protocol/muc",
        "urn:xmpp:http:upload:0",
        "urn:xmpp:unknown",
    ]) == ["ping", "muc", "http-upload"]
    assert xmpp._xmpp_feature_summary(None) == []


@pytest.mark.asyncio
async def test_xmpp_check_ping_success_timeout_iqerror_and_exception(monkeypatch, bot):
    class FakeTimeout(Exception):
        pass

    class FakeIqError(Exception):
        def __init__(self, condition="gone"):
            super().__init__(condition)
            self.iq = {"error": {"condition": condition}}

    monkeypatch.setattr(xmpp.slixmpp.exceptions, "IqTimeout", FakeTimeout, raising=False)
    monkeypatch.setattr(xmpp.slixmpp.exceptions, "IqError", FakeIqError, raising=False)

    bot.plugin["xep_0199"].ping = AsyncMock(return_value=None)
    status, line = await xmpp._xmpp_check_ping(bot, "example.org")
    assert status == "✅"
    assert line.startswith("ping ok")

    bot.plugin["xep_0199"].ping = AsyncMock(side_effect=FakeTimeout())
    assert await xmpp._xmpp_check_ping(bot, "example.org") == ("🔴", "ping timed out")

    bot.plugin["xep_0199"].ping = AsyncMock(side_effect=FakeIqError("forbidden"))
    assert await xmpp._xmpp_check_ping(bot, "example.org") == ("⚠️", "ping error: forbidden")

    bot.plugin["xep_0199"].ping = AsyncMock(side_effect=RuntimeError("boom"))
    assert await xmpp._xmpp_check_ping(bot, "example.org") == ("🔴", "ping failed: boom")


@pytest.mark.asyncio
async def test_xmpp_check_version_success_unsupported_and_errors(monkeypatch, bot):
    class FakeTimeout(Exception):
        pass

    class FakeIqError(Exception):
        def __init__(self, condition="gone"):
            super().__init__(condition)
            self.iq = {"error": {"condition": condition}}

    monkeypatch.setattr(xmpp.slixmpp.exceptions, "IqTimeout", FakeTimeout, raising=False)
    monkeypatch.setattr(xmpp.slixmpp.exceptions, "IqError", FakeIqError, raising=False)

    fake_version = SimpleNamespace(xml=[
        MagicMock(tag="{jabber:iq:version}query", __iter__=lambda self: iter([
            MagicMock(tag="{jabber:iq:version}name", text="Prosody"),
            MagicMock(tag="{jabber:iq:version}version", text="13.0"),
            MagicMock(tag="{jabber:iq:version}os", text="Debian"),
        ]))
    ])
    bot.plugin["xep_0092"].get_version = AsyncMock(return_value=fake_version)
    status, line = await xmpp._xmpp_check_version(bot, "example.org")
    assert status == "✅"
    assert "Prosody" in line

    bot.plugin["xep_0092"].get_version = AsyncMock(return_value=SimpleNamespace(xml=[]))
    assert await xmpp._xmpp_check_version(bot, "example.org") == ("ℹ️", "version: not advertised")

    bot.plugin["xep_0092"].get_version = AsyncMock(side_effect=FakeIqError("service-unavailable"))
    assert await xmpp._xmpp_check_version(bot, "example.org") == ("ℹ️", "version: unsupported")

    diagnose = AsyncMock(return_value="S2S TLS certificate has expired.")
    monkeypatch.setattr(xmpp, "_diagnose_xmpp_server_certificate", diagnose)
    bot.plugin["xep_0092"].get_version = AsyncMock(
        side_effect=FakeIqError("remote-server-timeout")
    )
    assert await xmpp._xmpp_check_version(bot, "example.org") == (
        "⚠️",
        "version: remote-server-timeout; S2S TLS certificate has expired.",
    )
    diagnose.assert_awaited_once_with("example.org")

    bot.plugin["xep_0092"].get_version = AsyncMock(side_effect=FakeTimeout())
    assert await xmpp._xmpp_check_version(bot, "example.org") == ("⚠️", "version: timed out")

    bot.plugin["xep_0092"].get_version = AsyncMock(side_effect=RuntimeError("boom"))
    assert await xmpp._xmpp_check_version(bot, "example.org") == ("⚠️", "version: boom")


def test_certificate_verification_message_classifies_common_failures():
    assert xmpp._certificate_verification_message(
        SimpleNamespace(verify_code=10, verify_message="certificate has expired")
    ) == "S2S TLS certificate has expired."
    assert xmpp._certificate_verification_message(
        SimpleNamespace(verify_code=62, verify_message="Hostname mismatch")
    ) == "S2S TLS certificate does not match the XMPP domain."


def test_public_endpoint_addresses_filters_non_public_networks(monkeypatch):
    monkeypatch.setattr(
        xmpp.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (xmpp.socket.AF_INET, xmpp.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 5269)),
            (xmpp.socket.AF_INET, xmpp.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 5269)),
            (xmpp.socket.AF_INET6, xmpp.socket.SOCK_STREAM, 6, "", ("::1", 5269, 0, 0)),
        ],
    )

    assert xmpp._public_endpoint_addresses("example.org", 5269) == [
        (xmpp.socket.AF_INET, "8.8.8.8")
    ]


@pytest.mark.asyncio
async def test_certificate_probe_negotiates_xmpp_starttls(monkeypatch):
    class FakeReader:
        def __init__(self):
            self.responses = iter([
                b"<stream:features><starttls "
                b"xmlns='urn:ietf:params:xml:ns:xmpp-tls'/></stream:features>",
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
        xmpp.asyncio,
        "open_connection",
        AsyncMock(return_value=(FakeReader(), writer)),
    )

    result = await xmpp._probe_xmpp_server_certificate(
        "8.8.8.8",
        xmpp.socket.AF_INET,
        5269,
        "example.org",
    )

    assert result == (
        "S2S TLS certificate is valid; the timeout occurs later in federation."
    )
    assert b"<stream:stream" in writer.writes[0]
    assert b"<starttls" in writer.writes[1]
    assert writer.tls_kwargs["server_hostname"] == "example.org"
    assert writer.closed is True


@pytest.mark.asyncio
async def test_certificate_diagnosis_uses_resolved_public_endpoint(monkeypatch):
    async def immediate_to_thread(func, *args):
        return func(*args)

    monkeypatch.setattr(xmpp.asyncio, "to_thread", immediate_to_thread)
    monkeypatch.setattr(
        xmpp,
        "_xmpp_server_endpoints",
        lambda _domain: [("s2s.example.org", 5269)],
    )
    monkeypatch.setattr(
        xmpp,
        "_public_endpoint_addresses",
        lambda _host, _port: [(xmpp.socket.AF_INET6, "2001:4860:4860::8888")],
    )
    probe = AsyncMock(return_value="S2S TLS certificate has expired.")
    monkeypatch.setattr(xmpp, "_probe_xmpp_server_certificate", probe)

    result = await xmpp._diagnose_xmpp_server_certificate("example.org")

    assert result == "S2S TLS certificate has expired."
    probe.assert_awaited_once_with(
        "2001:4860:4860::8888",
        xmpp.socket.AF_INET6,
        5269,
        "example.org",
    )


@pytest.mark.asyncio
async def test_xmpp_check_disco_success_and_errors(monkeypatch, bot):
    class FakeTimeout(Exception):
        pass

    class FakeIqError(Exception):
        def __init__(self, condition="gone"):
            super().__init__(condition)
            self.iq = {"error": {"condition": condition}}

    monkeypatch.setattr(xmpp.slixmpp.exceptions, "IqTimeout", FakeTimeout, raising=False)
    monkeypatch.setattr(xmpp.slixmpp.exceptions, "IqError", FakeIqError, raising=False)

    bot.plugin["xep_0030"].get_info = AsyncMock(return_value={
        "disco_info": {
            "identities": [("server", "im", "Example")],
            "features": ["urn:xmpp:ping", "urn:xmpp:mam:2"],
        }
    })
    status, line = await xmpp._xmpp_check_disco(bot, "example.org")
    assert status == "✅"
    assert "1 identities, 2 features" in line
    assert "ping" in line and "message-archive" in line

    bot.plugin["xep_0030"].get_info = AsyncMock(side_effect=FakeIqError("forbidden"))
    assert await xmpp._xmpp_check_disco(bot, "example.org") == ("⚠️", "disco error: forbidden")

    bot.plugin["xep_0030"].get_info = AsyncMock(side_effect=FakeTimeout())
    assert await xmpp._xmpp_check_disco(bot, "example.org") == ("🔴", "disco timed out")

    bot.plugin["xep_0030"].get_info = AsyncMock(side_effect=RuntimeError("boom"))
    assert await xmpp._xmpp_check_disco(bot, "example.org") == ("🔴", "disco failed: boom")


def test_xmpp_check_srv_success_none_and_failure(monkeypatch):
    monkeypatch.setattr(xmpp, "_make_srv_resolver", lambda *_args: object())
    monkeypatch.setattr(
        xmpp,
        "_collect_all_srv_records",
        lambda *_args: {
            "_xmpp-client._tcp": "xmpp.example.org:5222",
            "_xmpp-server._tcp": "Not found",
        },
    )
    status, line = xmpp._xmpp_check_srv("example.org")
    assert status == "✅"
    assert "_xmpp-client._tcp" in line

    monkeypatch.setattr(
        xmpp,
        "_collect_all_srv_records",
        lambda *_args: {"_xmpp-client._tcp": "Not found"},
    )
    assert xmpp._xmpp_check_srv("example.org") == ("⚠️", "SRV records: none found")

    monkeypatch.setattr(
        xmpp,
        "_collect_all_srv_records",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("dns boom")),
    )
    assert xmpp._xmpp_check_srv("example.org") == ("⚠️", "SRV lookup failed: dns boom")


@pytest.mark.asyncio
async def test_cmd_xmpp_check_replies_with_combined_diagnostics(monkeypatch, bot, msg):
    m = msg()
    monkeypatch.setattr(xmpp, "_xmpp_check_ping", AsyncMock(return_value=("✅", "ping ok")))
    monkeypatch.setattr(xmpp, "_xmpp_check_disco", AsyncMock(return_value=("✅", "disco ok")))
    monkeypatch.setattr(xmpp, "_xmpp_check_version", AsyncMock(return_value=("ℹ️", "version unsupported")))

    async def fake_to_thread(fn, *args, **kwargs):
        assert fn is xmpp._xmpp_check_srv
        assert args == ("example.org",)
        return ("✅", "SRV records: _xmpp-client._tcp")

    monkeypatch.setattr(xmpp.asyncio, "to_thread", fake_to_thread)
    await xmpp.cmd_xmpp_check(bot, "jid", "nick", ["example.org"], m, False)

    lines = bot.reply.call_args[0][1]
    assert lines == [
        "🩺 XMPP check for example.org",
        "✅ ping ok",
        "✅ disco ok",
        "ℹ️ version unsupported",
        "✅ SRV records: _xmpp-client._tcp",
    ]


@pytest.mark.asyncio
async def test_cmd_xmpp_check_denied_missing_and_invalid(bot, msg):
    m = msg(is_room=True)
    bot.db.users.plugin.return_value.get_global = AsyncMock(return_value={})
    await xmpp.cmd_xmpp_check(bot, "jid", "nick", ["example.org"], m, True)
    bot.reply.assert_not_called()

    m = msg()
    await xmpp.cmd_xmpp_check(bot, "jid", "nick", [], m, False)
    assert "Missing target" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    await xmpp.cmd_xmpp_check(bot, "jid", "nick", ["not-a-domain"], m, False)
    assert "Invalid target" in bot.reply.call_args[0][1]
