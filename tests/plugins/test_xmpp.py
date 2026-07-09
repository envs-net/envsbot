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
    async def fake_fetch_text(url, **kwargs):
        return SimpleNamespace(status=200, text="<html></html>")

    class FakeSoup:
        def find(self, *a, **kw):
            class Score:
                def get_text(self, **_): return "110/120"
            return Score()

    with patch.object(xmpp, "fetch_text", fake_fetch_text), \
            patch("bs4.BeautifulSoup", return_value=FakeSoup()):
        await xmpp.cmd_xmpp_compliance(bot, "jid", "nick",
                                       ["conversations.im"], m, True)
        bot.reply.assert_called()
        assert "Compliance score" in "".join(
            str(a) for a in bot.reply.call_args[0])


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
