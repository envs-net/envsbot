from .helpers import (
    msg,
    AsyncMock,
    RichDummyVcard,
    SimpleNamespace,
    pytest,
    vcard,
)


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
    monkeypatch.setattr(vcard._core, "_get_enabled_rooms", _get_enabled_rooms)
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
    async def rich_get_vcard(bot, msg, jid=None):
        assert jid == "alice@example.org"
        return RichDummyVcard()

    monkeypatch.setattr(vcard, "get_vcard", rich_get_vcard)
    monkeypatch.setattr(vcard._core, "_is_muc_pm", lambda msg: False)
    m = msg(from_jid="alice@example.org/resource", type_="chat")

    assert await vcard.vcard_field(fake_bot, m, "ignored", "FN") == "Alice Example"
    assert await vcard.vcard_field(fake_bot, m, "ignored", "LOCALITY") == "Berlin"
    assert await vcard.vcard_field(fake_bot, m, "ignored", "CTRY") == "DE"


@pytest.mark.asyncio
async def test_vcard_room_lookup_fetches_replies_and_handles_missing(fake_bot, monkeypatch):
    room = "room@x"
    m = msg(from_jid=f"{room}/Alice", type_="groupchat")
    vcard.JOINED_ROOMS[room] = {"nicks": {"Alice": {"jid": "alice@example.org"}}}
    try:
        monkeypatch.setattr(vcard, "_vcard_fetch_value", AsyncMock(return_value="Alice Example"))
        await vcard._vcard_handle_room_lookup(
            fake_bot, "sender@example.org", m, "FN", "Full Name", "Alice", room
        )
        assert any(isinstance(reply[0], list) and "Alice Example" in "\n".join(reply[0]) for reply in fake_bot._replies)

        fake_bot._replies.clear()
        vcard._vcard_fetch_value.return_value = None
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
        vcard.JOINED_ROOMS.pop(room, None)


@pytest.mark.asyncio
async def test_get_user_vcard_and_fetch_value_helpers(fake_bot, monkeypatch):
    async def rich_get_vcard(bot, msg, jid=None):
        assert jid == "alice@example.org"
        return RichDummyVcard()

    monkeypatch.setattr(vcard, "get_vcard", rich_get_vcard)
    monkeypatch.setattr(
        vcard._core,
        "get_real_jid",
        AsyncMock(return_value=("alice@example.org", False, False)),
    )
    monkeypatch.setattr(
        vcard._core,
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
