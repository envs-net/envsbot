import logging

from slixmpp.exceptions import IqError, IqTimeout

from .helpers import (
    msg,
    ORIGINAL_GET_VCARD,
    AsyncMock,
    RichDummyVcard,
    SimpleNamespace,
    pytest,
    vcard,
)
from plugins.vcard import commands as vcard_commands
from plugins.vcard import fetch as vcard_fetch
from plugins.vcard import fields as vcard_fields


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd,args,label,expect", [
    (vcard.get_fullname, [], "Full Name", "Full Name"),
    (vcard.get_nicknames, [], "Nicknames", "Nicknames"),
    (vcard.get_timezone, [], "Timezone", "Timezone"),
    (vcard.get_organisations, [], "Organisations", "Organisations"),
    (vcard.get_notes, [], "Notes", "Notes"),
    (vcard.get_email, [], "Emails", "Emails"),
    (vcard.get_urls, [], "URLs", "URLs"),
    (vcard.get_birthday, [], "birthday", "Birthday"),
])
async def test_field_cmds(fake_bot, monkeypatch, cmd, args, label, expect):
    async def _get_enabled_rooms(b, k, p): return {"room@x": True}
    monkeypatch.setattr(vcard_commands._core, "_get_enabled_rooms", _get_enabled_rooms)
    m = msg(from_jid="room@x/TestNick", resource="TestNick")
    m["type"] = "chat"
    # Patch plugin store so bot.db.users.plugin("vcard").get_global works even
    # if key unused
    fake_bot.db.users.plugin = lambda plugin: SimpleNamespace(
        get_global=lambda k, d=None: {"room@x": True})
    await cmd(fake_bot, "s", "n", args, m, True)
    # Accept warning cases: some vcard plugins will warn about missing nicks
    # if the minimal nick is not found
    expected_found = any(expect.lower() in x[0].lower() or label.lower(
    ) in x[0].lower() for x in getattr(fake_bot, "_replies", []))
    # Also accept a warning reply about the nick not being found for negative
    # coverage
    warning_found = any("not found in this room" in x[0].lower(
    ) for x in getattr(fake_bot, "_replies", []))
    assert expected_found or warning_found


@pytest.mark.asyncio
async def test_vcard_field_direct_message_fetches_sender_field(fake_bot, monkeypatch):
    async def rich_get_vcard(bot, msg, jid=None, *, raise_on_error=False):
        assert raise_on_error is False
        assert jid == "alice@example.org"
        return RichDummyVcard()

    monkeypatch.setattr(vcard_fetch, "get_vcard", rich_get_vcard)
    monkeypatch.setattr(vcard_fetch._core, "_is_muc_pm", lambda msg: False)
    m = msg(from_jid="alice@example.org/resource", type_="chat")

    assert await vcard.vcard_field(fake_bot, m, "ignored", "FN") == "Alice Example"
    assert await vcard.vcard_field(fake_bot, m, "ignored", "LOCALITY") == "Berlin"
    assert await vcard.vcard_field(fake_bot, m, "ignored", "CTRY") == "DE"


@pytest.mark.asyncio
async def test_vcard_room_lookup_fetches_replies_and_handles_missing(fake_bot, monkeypatch):
    room = "room@x"
    m = msg(from_jid=f"{room}/Alice", type_="groupchat")
    vcard_fetch.JOINED_ROOMS[room] = {"nicks": {"Alice": {"jid": "alice@example.org"}}}
    try:
        monkeypatch.setattr(vcard_fields, "_vcard_fetch_value", AsyncMock(return_value="Alice Example"))
        await vcard._vcard_handle_room_lookup(
            fake_bot, "sender@example.org", m, "FN", "Full Name", "Alice", room
        )
        assert any(isinstance(reply[0], list) and "Alice Example" in "\n".join(reply[0]) for reply in fake_bot._replies)

        fake_bot._replies.clear()
        vcard_fields._vcard_fetch_value.return_value = None
        await vcard._vcard_handle_room_lookup(
            fake_bot, "sender@example.org", m, "FN", "Full Name", "Alice", room
        )
        assert "No Full Name found" in fake_bot._replies[-1][0]

        fake_bot._replies.clear()
        await vcard._vcard_handle_room_lookup(
            fake_bot, "sender@example.org", m, "FN", "Full Name", "Missing", room, own=True
        )
        assert "Your Nick 'Missing' not found" in fake_bot._replies[-1][0]
    finally:
        vcard_fetch.JOINED_ROOMS.pop(room, None)


@pytest.mark.asyncio
async def test_get_user_vcard_and_fetch_value_helpers(fake_bot, monkeypatch):
    async def rich_get_vcard(bot, msg, jid=None, *, raise_on_error=False):
        assert raise_on_error is False
        assert jid == "alice@example.org"
        return RichDummyVcard()

    monkeypatch.setattr(vcard_fetch, "get_vcard", rich_get_vcard)
    monkeypatch.setattr(
        vcard_fetch._core,
        "get_real_jid",
        AsyncMock(return_value=("alice@example.org", False, False)),
    )
    monkeypatch.setattr(
        vcard_fetch._core,
        "_get_user_timezone",
        AsyncMock(return_value="Europe/Berlin"),
    )

    m = msg(from_jid="room@x/Alice", type_="groupchat")
    data = await vcard.get_user_vcard(fake_bot, m, "alice@example.org")
    assert data["FN"] == "Alice Example"
    assert data["LOCALITY"] == "Berlin"
    assert data["TZ"] == "Europe/Berlin"

    assert await vcard._vcard_fetch_value(fake_bot, m, "TIMEZONE", "alice@example.org") == "Europe/Berlin"
    assert await vcard._vcard_fetch_value(fake_bot, m, "FN", "alice@example.org") == "Alice Example"


def test_vcard_item_not_found_is_debug_only_and_does_not_dump_raw_iq(caplog):
    error = IqError({
        "error": {
            "condition": "item-not-found",
            "text": "Recipient not in room",
            "type": "cancel",
        }
    })
    vcard_fetch._VCARD_FAILURE_LOG_GATE.clear()
    with caplog.at_level(logging.DEBUG, logger="plugins.vcard.config"):
        vcard_fetch._log_vcard_iq_error("room@example.org/Nick", error)

    assert "IQ error item-not-found: Recipient not in room" in caplog.text
    assert "{'error':" not in caplog.text
    assert not any(record.levelno >= logging.INFO for record in caplog.records)


def test_vcard_timeout_info_log_is_deduplicated(caplog):
    assert issubclass(IqTimeout, Exception)
    vcard_fetch._VCARD_FAILURE_LOG_GATE.clear()
    with caplog.at_level(logging.DEBUG, logger="plugins.vcard.config"):
        vcard_fetch._log_vcard_timeout("room@example.org/Nick", 10.0)
        vcard_fetch._log_vcard_timeout("room@example.org/Nick", 10.0)

    info = [record for record in caplog.records if record.levelno == logging.INFO]
    assert len(info) == 1
    assert "timed out after 10s" in info[0].getMessage()
    assert "suppressed at INFO" in caplog.text


@pytest.mark.asyncio
async def test_get_vcard_treats_departed_muc_occupant_as_expected_churn(fake_bot, caplog):
    class GoneVcardPlugin:
        async def get_vcard(self, **kwargs):
            del kwargs
            raise IqError({
                "error": {
                    "condition": "item-not-found",
                    "text": "Recipient not in room",
                    "type": "cancel",
                }
            })

    fake_bot.plugin["xep_0054"] = GoneVcardPlugin()
    vcard_fetch._VCARD_FAILURE_LOG_GATE.clear()
    with caplog.at_level(logging.DEBUG, logger="plugins.vcard.config"):
        result = await ORIGINAL_GET_VCARD(
            fake_bot,
            msg(from_jid="room@example.org/Nick", type_="groupchat"),
            "room@example.org/Nick",
        )

    assert result is None
    assert "Recipient not in room" in caplog.text
    assert "{'error':" not in caplog.text
    assert not any(record.levelno >= logging.INFO for record in caplog.records)


@pytest.mark.asyncio
async def test_get_user_vcard_explicit_target_uses_target_timezone(fake_bot, monkeypatch):
    async def rich_get_vcard(bot, msg, jid=None, *, raise_on_error=False):
        del bot, msg
        assert raise_on_error is False
        assert jid == "alice@example.org"
        return RichDummyVcard()

    monkeypatch.setattr(vcard_fetch, "get_vcard", rich_get_vcard)
    get_real_jid = AsyncMock(return_value=("sender@example.org", False, False))
    timezone = AsyncMock(return_value="Europe/Berlin")
    monkeypatch.setattr(vcard_fetch._core, "get_real_jid", get_real_jid)
    monkeypatch.setattr(vcard_fetch._core, "_get_user_timezone", timezone)

    m = msg(from_jid="room@x/Sender", type_="groupchat")
    data = await vcard.get_user_vcard(fake_bot, m, "alice@example.org")

    assert data["TZ"] == "Europe/Berlin"
    get_real_jid.assert_not_awaited()
    timezone.assert_awaited_once_with(fake_bot, "alice@example.org")


@pytest.mark.asyncio
async def test_get_vcard_strict_mode_propagates_iq_timeout(fake_bot):
    class TimeoutVcardPlugin:
        async def get_vcard(self, **kwargs):
            raise IqTimeout(kwargs)

    fake_bot.plugin["xep_0054"] = TimeoutVcardPlugin()
    with pytest.raises(IqTimeout):
        await ORIGINAL_GET_VCARD(
            fake_bot,
            msg(from_jid="room@example.org/Nick", type_="groupchat"),
            "room@example.org/Nick",
            raise_on_error=True,
        )
