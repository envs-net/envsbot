import pytest
from unittest.mock import AsyncMock, MagicMock

import plugins.tools as tools


@pytest.fixture
def bot():
    b = MagicMock()
    b.reply = MagicMock()
    b.db.users.plugin = AsyncMock(return_value=MagicMock())
    b.presence.emoji = MagicMock(return_value="😀")
    b.presence.status = {"show": "online", "status": "all good"}
    b.version = "1.2.3"
    b.prefix = ","
    # Only xep_0045 was referenced in your actual source
    b.plugin = {'xep_0045': MagicMock()}
    b.presence.joined_rooms = {}
    return b


@pytest.fixture
def simple_msg():
    return {
        "from": MagicMock(bare="room@conf.org", resource="TestUser"),
        "mucnick": "TestUser",
        "body": "",
        "type": "groupchat"
    }


@pytest.fixture
def joined_rooms():
    return {
        "room@conf.org": {
            "nicks": {
                "TestUser": {"jid": "testuser@example.org"},
                "OtherGuy": {"jid": "otherguy@example.org"},
            }
        }
    }


@pytest.fixture
def enabled_rooms():
    return {"room@conf.org": True}


@pytest.mark.asyncio
async def test_ping_command_enabled_room(bot, simple_msg, enabled_rooms,
                                         monkeypatch):
    monkeypatch.setattr(tools, "JOINED_ROOMS", {})
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    await tools.ping_command(bot, "jid", "nick", [], simple_msg, True)
    bot.reply.assert_called_with(simple_msg, "🏓 Pong!", ephemeral=False)


@pytest.mark.asyncio
async def test_ping_command_disabled_room(bot, simple_msg, monkeypatch):
    monkeypatch.setattr(tools, "JOINED_ROOMS", {})
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value={}))
    await tools.ping_command(bot, "jid", "nick", [], simple_msg, True)
    bot.reply.assert_called()
    assert "disabled" in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_echo_command_success(bot, simple_msg, enabled_rooms,
                                    monkeypatch):
    monkeypatch.setattr(tools, "JOINED_ROOMS", {})
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    args = ["hello", "world!"]
    await tools.echo_command(bot, "jid", "nick", args, simple_msg, True)
    bot.reply.assert_called_with(simple_msg, "🔊 hello world!",
                                 ephemeral=False)


@pytest.mark.asyncio
async def test_echo_command_usage(bot, simple_msg, enabled_rooms, monkeypatch):
    monkeypatch.setattr(tools, "JOINED_ROOMS", {})
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    await tools.echo_command(bot, "jid", "nick", [], simple_msg, True)
    bot.reply.assert_called()
    assert "usage" in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_certificate_command_uses_shared_xmpp_probe(
    bot,
    simple_msg,
    enabled_rooms,
    monkeypatch,
):
    diagnose = AsyncMock(return_value=tools.VALID_CERTIFICATE_MESSAGE)
    monkeypatch.setattr(
        tools,
        "_get_enabled_rooms",
        AsyncMock(return_value=enabled_rooms),
    )
    monkeypatch.setattr(
        tools,
        "source_domain_from_jid",
        lambda _jid: "bot.example.org",
    )
    monkeypatch.setattr(tools, "diagnose_xmpp_server_certificate", diagnose)

    await tools.certificate_command(
        bot,
        "jid",
        "nick",
        ["admin@example.org/resource"],
        simple_msg,
        True,
    )

    diagnose.assert_awaited_once_with(
        "example.org",
        source_domain="bot.example.org",
        timeout_seconds=tools.CERTIFICATE_PROBE_TIMEOUT_SECONDS,
    )
    assert "Using 'example.org'" in bot.reply.call_args_list[0].args[1]
    assert bot.reply.call_args_list[1].args[1] == [
        "🔐 S2S TLS certificate check for example.org",
        "✅ S2S TLS certificate is valid.",
    ]


@pytest.mark.asyncio
async def test_certificate_command_handles_disabled_missing_and_invalid(
    bot,
    simple_msg,
    monkeypatch,
):
    enabled = AsyncMock(return_value={})
    diagnose = AsyncMock()
    monkeypatch.setattr(tools, "_get_enabled_rooms", enabled)
    monkeypatch.setattr(tools, "diagnose_xmpp_server_certificate", diagnose)

    await tools.certificate_command(
        bot,
        "jid",
        "nick",
        ["example.org"],
        simple_msg,
        True,
    )
    assert "disabled" in bot.reply.call_args.args[1]
    diagnose.assert_not_awaited()

    enabled.return_value = {"room@conf.org": True}
    bot.reply.reset_mock()
    await tools.certificate_command(bot, "jid", "nick", [], simple_msg, True)
    assert "Missing domain" in bot.reply.call_args.args[1]

    bot.reply.reset_mock()
    await tools.certificate_command(
        bot,
        "jid",
        "nick",
        ["localhost"],
        simple_msg,
        True,
    )
    assert "Invalid domain" in bot.reply.call_args.args[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("is_room,prefix,expected", [
    (True, ",", "⏰ Time for TestUser:"),
    (False, ",", "⏰ Time for testjid:"),
])
async def test_time_command_basic(bot, simple_msg, enabled_rooms, joined_rooms,
                                  monkeypatch, is_room, prefix, expected):
    monkeypatch.setattr(tools, "JOINED_ROOMS", joined_rooms)
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    monkeypatch.setattr(tools, "_get_user_timezone",
                        AsyncMock(return_value="UTC"))
    msg = dict(simple_msg)
    if not is_room:
        msg['from'] = MagicMock(bare="testjid", resource="")
    await tools.time_command(bot, "jid", "TestUser", [], msg, is_room)
    bot.reply.assert_called()
    assert expected.lower() in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_time_command_invalid_nick(bot, simple_msg, enabled_rooms,
                                         joined_rooms, monkeypatch):
    monkeypatch.setattr(tools, "JOINED_ROOMS", joined_rooms)
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    msg = dict(simple_msg)
    await tools.time_command(bot, "jid", "FakeNick", ["missingnick"],
                             msg, True)
    bot.reply.assert_called()
    assert "not found" in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_time_command_bad_timezone(bot, simple_msg, enabled_rooms,
                                         joined_rooms, monkeypatch):
    monkeypatch.setattr(tools, "JOINED_ROOMS", joined_rooms)
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    monkeypatch.setattr(tools, "_get_user_timezone",
                        AsyncMock(return_value="Fake/Zone"))
    msg = dict(simple_msg)
    await tools.time_command(bot, "jid", "TestUser", [], msg, True)
    bot.reply.assert_called()
    assert "utc" in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("is_room", [True, False])
async def test_date_command_basic(bot, simple_msg, enabled_rooms, joined_rooms,
                                  monkeypatch, is_room):
    monkeypatch.setattr(tools, "JOINED_ROOMS", joined_rooms)
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    monkeypatch.setattr(tools, "_get_user_timezone",
                        AsyncMock(return_value="UTC"))
    msg = dict(simple_msg)
    if not is_room:
        msg['from'] = MagicMock(bare="testjid", resource="")
    await tools.date_command(bot, "jid", "TestUser", [], msg, is_room)
    bot.reply.assert_called()
    assert "📅 date for" in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_utc_command(bot, simple_msg, enabled_rooms, monkeypatch):
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    await tools.utc_command(bot, "jid", "nick", [], simple_msg, True)
    bot.reply.assert_called()
    assert "utc time" in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_ts_command_valid(bot, simple_msg, enabled_rooms, monkeypatch):
    monkeypatch.setattr(tools, "JOINED_ROOMS", {
                        "room@conf.org": {"nicks":
                                          {"TestUser":
                                           {"jid": "testuser@example.org"}}}})
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    monkeypatch.setattr(tools, "_get_user_timezone",
                        AsyncMock(return_value="UTC"))
    await tools.timestamp_command(bot, "jid", "TestUser", ["1704067200"],
                                  simple_msg, True)
    bot.reply.assert_called()
    assert "⏰ timestamp 1704067200" in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_ts_command_invalid(bot, simple_msg, enabled_rooms,
                                  monkeypatch):
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    await tools.timestamp_command(bot, "jid", "TestUser", ["notanint"],
                                  simple_msg, True)
    bot.reply.assert_called()
    assert "invalid timestamp" in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_ts_command_out_of_range(bot, simple_msg, enabled_rooms,
                                       monkeypatch):
    monkeypatch.setattr(tools, "JOINED_ROOMS", {
                        "room@conf.org": {"nicks":
                                          {"TestUser":
                                           {"jid": "testuser@example.org"}}}})
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    monkeypatch.setattr(tools, "_get_user_timezone",
                        AsyncMock(return_value="UTC"))
    await tools.timestamp_command(bot, "jid", "TestUser",
                                  ["-999999999999999"], simple_msg, True)
    bot.reply.assert_called()
    assert "invalid timestamp" in bot.reply.call_args[0][1].lower(
    ) or "out of range" in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_seen_command_found(bot, simple_msg, enabled_rooms,
                                  joined_rooms, monkeypatch):
    async def _ret_list(bot, nick):
        return ["testuser@example.org"]
    async_mock = AsyncMock(side_effect=_ret_list)
    monkeypatch.setattr(tools, "get_jids_from_nick_index", async_mock)
    monkeypatch.setattr("core_plugins._core.get_jids_from_nick_index", async_mock)
    monkeypatch.setattr("plugins.tools.get_jids_from_nick_index", async_mock)
    monkeypatch.setattr(tools, "JOINED_ROOMS", joined_rooms)
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    bot.plugin["xep_0045"].get_roster.return_value = ["TestUser"]
    bot.plugin["xep_0045"].get_jid_property.return_value = "online"
    mock_user = {"last_seen": "2023-01-01T10:11:12+00:00"}
    bot.db.users.get = AsyncMock(return_value=mock_user)
    bot.presence.emoji = MagicMock(return_value="😀")
    await tools.seen_command(bot, "jid", "TestUser", [], simple_msg, True)
    bot.reply.assert_called()
    out = bot.reply.call_args[0][1]
    if isinstance(out, list):
        out = "\n".join(out)
    if "unexpected error" in out.lower():
        pytest.fail(f"Unexpected error in seen_command: {out}")
    assert "nickname" in out.lower()
    assert "last seen" in out.lower()
    await async_mock(bot, "TestUser")


@pytest.mark.asyncio
async def test_seen_command_not_found(bot, simple_msg, enabled_rooms,
                                      joined_rooms, monkeypatch):
    async def _ret_list(bot, nick):
        return []
    async_mock = AsyncMock(side_effect=_ret_list)
    monkeypatch.setattr(tools, "get_jids_from_nick_index", async_mock)
    monkeypatch.setattr("core_plugins._core.get_jids_from_nick_index", async_mock)
    monkeypatch.setattr("plugins.tools.get_jids_from_nick_index", async_mock)
    monkeypatch.setattr(tools, "JOINED_ROOMS", joined_rooms)
    monkeypatch.setattr(tools, "_get_enabled_rooms",
                        AsyncMock(return_value=enabled_rooms))
    bot.db.users.get = AsyncMock(return_value=None)
    await tools.seen_command(bot, "jid", "UnknownNick", ["UnknownNick"],
                             simple_msg, True)
    bot.reply.assert_called()
    out = bot.reply.call_args[0][1].lower()
    assert "no data found" in out or "not found" in out
    await async_mock(bot, "UnknownNick")


class SeenFrom:
    def __init__(self, bare, resource=""):
        self.bare = bare
        self.resource = resource

    def __str__(self):
        return f"{self.bare}/{self.resource}" if self.resource else self.bare


@pytest.mark.asyncio
async def test_seen_resolve_room_context_uses_live_room_and_presence(bot, monkeypatch):
    joined = {
        "room@conf.org": {
            "nicks": {
                "Alice": {"jid": "alice@example.org"},
                "Bob": {"jid": "bob@example.org"},
            }
        },
        "other@conf.org": {
            "nicks": {
                "Bob": {"jid": "bob@example.org"},
            }
        },
    }
    monkeypatch.setattr(tools, "JOINED_ROOMS", joined)
    nick_lookup = AsyncMock(return_value=[])
    monkeypatch.setattr(tools, "get_jids_from_nick_index", nick_lookup)
    bot.plugin["xep_0045"].get_roster.return_value = ["Bob"]
    bot.plugin["xep_0045"].get_jid_property.side_effect = ["away", "busy"]
    bot.presence.emoji.return_value = "🟡"
    msg = {"from": SeenFrom("room@conf.org", "Alice")}

    context = await tools._seen_resolve_room_context(
        bot, "room@conf.org/Alice", "Alice", ["Bob"], msg
    )

    assert context == {
        "room_jid": "room@conf.org",
        "display_nick": "Bob",
        "target_jid": "bob@example.org",
        "caller_jid": "alice@example.org",
        "present_in_room": True,
        "rooms_with_nick": ["room@conf.org", "other@conf.org"],
        "target_show": "away",
        "target_status": "busy",
        "target_emoji": "🟡",
    }
    nick_lookup.assert_not_called()


@pytest.mark.asyncio
async def test_seen_resolve_room_context_falls_back_to_nick_index(bot, monkeypatch):
    monkeypatch.setattr(tools, "JOINED_ROOMS", {
        "room@conf.org": {"nicks": {}}
    })
    nick_lookup = AsyncMock(side_effect=[
        ["target@example.org"],
        ["caller@example.org"],
    ])
    monkeypatch.setattr(tools, "get_jids_from_nick_index", nick_lookup)
    msg = {"from": SeenFrom("room@conf.org", "Alice")}

    context = await tools._seen_resolve_room_context(
        bot, "room@conf.org/Alice", "Alice", ["Missing"], msg
    )

    assert context["target_jid"] == "target@example.org"
    assert context["caller_jid"] == "caller@example.org"
    assert context["present_in_room"] is False
    assert context["target_show"] == "unknown"
    assert nick_lookup.await_count == 2


@pytest.mark.asyncio
async def test_seen_resolve_dm_context_allows_self_and_denies_others(bot, monkeypatch):
    monkeypatch.setattr(tools, "get_jids_from_nick_index", AsyncMock(return_value=[
        "alice@example.org"
    ]))
    msg = {"from": SeenFrom("alice@example.org", "desktop")}

    context = await tools._seen_resolve_dm_context(
        bot, "alice@example.org/desktop", "Alice", [], msg
    )
    assert context["display_nick"] == "Alice"
    assert context["target_jid"] == "alice@example.org"
    assert context["caller_jid"] == "alice@example.org"
    assert context["present_in_room"] is False
    assert context["target_show"] == "online"
    assert context["target_emoji"] == "😀"

    assert await tools._seen_resolve_dm_context(
        bot, "alice@example.org/desktop", "Alice", ["Bob"], msg
    ) is None
    assert "only look up yourself" in bot.reply.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_seen_timezone_and_formatting_helpers(monkeypatch, bot):
    monkeypatch.setattr(tools, "get_user_tzinfo", AsyncMock(return_value=tools.pytz.timezone("Europe/Berlin")))
    tzinfo = await tools._seen_get_timezone(bot, "alice@example.org")
    assert str(tzinfo) == "Europe/Berlin"

    good = await tools._seen_format_last_seen(
        "2024-01-01T10:00:00+00:00",
        tools.pytz.timezone("Europe/Berlin"),
        "Alice",
    )
    assert "2024-01-01" in good
    assert "CET" in good

    assert await tools._seen_format_last_seen(None, None, "Alice") == "never"
    assert await tools._seen_format_last_seen("not-a-date", None, "Alice") == "not-a-date"

@pytest.mark.asyncio
async def test_tools_store_getter_uses_plugin_store():
    marker = object()
    bot = MagicMock()
    bot.db.users.plugin.return_value = marker
    assert await tools.get_tools_store(bot) is marker
    bot.db.users.plugin.assert_called_once_with("tools")
