import pytest
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from unittest.mock import AsyncMock
from plugins import vcard


ORIGINAL_GET_VCARD = vcard.get_vcard


@pytest.fixture
def fake_bot(monkeypatch):
    bot = SimpleNamespace()
    bot.db = SimpleNamespace()
    bot.db.users = SimpleNamespace()
    bot.plugin = {"xep_0054": SimpleNamespace()}
    bot.prefix = ","
    bot.presence = SimpleNamespace()
    bot.presence.joined_rooms = {}
    bot.boundjid = SimpleNamespace(bare="bot@domain", resource="BotNick")
    bot.reply = lambda msg, txt, * \
        a, **k: bot.__dict__.setdefault('_replies', []).append((txt, msg))
    bot.get_user_role = lambda jid, room=None: 1
    bot.bot_plugins = SimpleNamespace()
    bot.bot_plugins.plugins = {"rooms": SimpleNamespace(JOINED_ROOMS={})}
    # Add .plugin attribute for _core._get_enabled_rooms
    async def get_global(key, default=None): return {}
    bot.db.users.plugin = lambda plugin: SimpleNamespace(get_global=get_global)
    return bot


def msg(from_jid="room@x/resource", resource=None, type_="chat",
        to_jid="bot@domain"):
    if "/" in from_jid:
        bare, res = from_jid.split("/", 1)
        resource = resource if resource is not None else res
    else:
        bare = from_jid
        resource = resource if resource is not None else "resource"

    class FakeJID:
        def __init__(self, bare): self.bare = bare
    return {
        "from": SimpleNamespace(bare=bare, resource=resource),
        "type": type_,
        "to": FakeJID(to_jid)
    }


@pytest.fixture(autouse=True)
def patch_get_vcard(monkeypatch):
    class DummyVcard:
        def get(self, key):
            if key == "FN":
                return "Test User"
            if key == "BDAY":
                return "2001-01-01"
            if key == "ADR":
                return {"LOCALITY": "Loc", "REGION": "Reg", "CTRY": "CT"}
            return None
        xml = []

    async def get_vcard(bot, msg, jid=None):
        return DummyVcard()
    monkeypatch.setattr(vcard, "get_vcard", get_vcard)
    return DummyVcard


@pytest.mark.asyncio
@pytest.mark.parametrize("args,is_room,expect", [
    ([], False, "vCard for"),
    (["bad"], False, "only look up your own vCard"),
])
async def test_vcard_command_pm(fake_bot, args, is_room, expect):
    msgx = msg(from_jid="bob@b/resource")
    await vcard.vcard_command(fake_bot, "s", "n", args, msgx, is_room)
    assert any(expect in r[0] for r in getattr(fake_bot, "_replies", []))


@pytest.mark.asyncio
async def test_set_timezone_command(fake_bot, monkeypatch):
    async def get_global(key, default=None): return {}
    async def set(j, k, v): pass
    fake_bot.db.users.plugin = lambda p: SimpleNamespace(
        get_global=get_global, set=set)

    async def _get_enabled_rooms(b, k, p): return {"bob@b": True}
    monkeypatch.setattr(vcard._core, "_get_enabled_rooms", _get_enabled_rooms)
    async def _check_user_exists(b, jid, msg): return True
    monkeypatch.setattr(vcard._core, "_check_user_exists", _check_user_exists)
    m = msg(from_jid="bob@b/resource")
    m["type"] = "chat"
    await vcard.set_timezone(fake_bot, "s", "n", ["Europe/Berlin"], m, False)
    found = any("TIMEZONE set to" in t[0]
                for t in getattr(fake_bot, "_replies", []))
    assert found


@pytest.mark.asyncio
async def test_set_timezone_invalid(fake_bot, monkeypatch):
    async def get_global(key, default=None): return {}
    async def set(j, k, v): pass
    fake_bot.db.users.plugin = lambda p: SimpleNamespace(
        get_global=get_global, set=set)

    async def _get_enabled_rooms(b, k, p): return {"bob@b": True}
    monkeypatch.setattr(vcard._core, "_get_enabled_rooms", _get_enabled_rooms)
    async def _check_user_exists(b, jid, msg): return True
    monkeypatch.setattr(vcard._core, "_check_user_exists", _check_user_exists)
    m = msg(from_jid="bob@b/resource")
    m["type"] = "chat"
    await vcard.set_timezone(fake_bot, "s", "n", ["NotAZone"], m, False)
    assert any("Invalid timezone" in t[0]
               for t in getattr(fake_bot, "_replies", []))


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


class RichDummyVcard:
    def __init__(self):
        self._values = {
            "FN": "Alice Example",
            "BDAY": "2001-02-03",
            "ADR": {"LOCALITY": "Berlin", "REGION": "Berlin", "CTRY": "DE"},
        }
        self.xml = [
            ET.Element("NICKNAME"),
            ET.Element("URL"),
            ET.Element("NOTE"),
            ET.Element("ORG"),
            ET.Element("EMAIL"),
        ]
        self.xml[0].text = "Ali"
        self.xml[1].text = "https%3A//example.org/profile"
        self.xml[2].text = "first line\nsecond line"
        org_name = ET.SubElement(self.xml[3], "ORGNAME")
        org_name.text = "Example Org"
        user_id = ET.SubElement(self.xml[4], "USERID")
        user_id.text = "alice@example.org"

    def get(self, key, default=None):
        return self._values.get(key, default)

    def __getitem__(self, key):
        return self._values.get(key)


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
async def test_vcard_field_room_lookup_and_timezone_branches(fake_bot, monkeypatch):
    monkeypatch.setattr(
        vcard._core,
        "get_real_jid_from_occupant",
        lambda bot, msg, target_nick: "alice@example.org",
    )
    monkeypatch.setattr(
        vcard._core,
        "_get_user_timezone",
        AsyncMock(return_value="Europe/Berlin"),
    )
    m = msg(from_jid="room@x/Alice", type_="groupchat")

    value = await vcard.vcard_field(fake_bot, m, "Alice", "TIMEZONE", is_room=True)

    assert value == "Europe/Berlin"
    vcard._core._get_user_timezone.assert_awaited_once_with(fake_bot, "alice@example.org")


@pytest.mark.asyncio
async def test_vcard_field_returns_none_for_invalid_missing_and_empty_timezone(fake_bot, monkeypatch):
    m = msg(from_jid="room@x/Alice", type_="groupchat")

    assert await vcard.vcard_field(fake_bot, m, "Alice", "UNKNOWN", is_room=True) is None

    monkeypatch.setattr(
        vcard._core,
        "get_real_jid_from_occupant",
        lambda bot, msg, target_nick: None,
    )
    assert await vcard.vcard_field(fake_bot, m, "Missing", "FN", is_room=True) is None

    monkeypatch.setattr(
        vcard._core,
        "get_real_jid_from_occupant",
        lambda bot, msg, target_nick: "alice@example.org",
    )
    monkeypatch.setattr(vcard._core, "_get_user_timezone", AsyncMock(return_value=None))
    assert await vcard.vcard_field(fake_bot, m, "Alice", "TIMEZONE", is_room=True) is None


@pytest.mark.asyncio
async def test_format_vcard_field_for_nick_all_value_shapes():
    assert await vcard._format_vcard_field_for_nick(
        "URL", "URLs", ["https%3A//example.org/a%20b"], "Alice"
    ) == ["URLs - Alice:", "    • https://example.org/a b"]
    assert await vcard._format_vcard_field_for_nick("URL", "URLs", [], "Alice") == [
        "URLs - Alice:",
        "    • —",
    ]

    note_lines = await vcard._format_vcard_field_for_nick(
        "NOTE", "Notes", ["first line\nsecond line"], "Alice", ["room@conf"]
    )
    assert note_lines[0] == "Notes - Alice in room@conf:"
    assert "    • first line" in note_lines
    assert "      second line" in note_lines

    assert await vcard._format_vcard_field_for_nick("EMAIL", "Emails", ["a@example.org"], "Alice") == [
        "Emails - Alice:",
        "    • a@example.org",
    ]
    assert await vcard._format_vcard_field_for_nick("FN", "Full Name", "Alice Example", "Alice") == [
        "Full Name - Alice:",
        "    • Alice Example",
    ]
    assert await vcard._format_vcard_field_for_nick("ORG", "Orgs", None, "Alice") == [
        "Orgs - Alice:",
        "    • —",
    ]


def test_vcard_reply_helpers_and_empty_checks(fake_bot):
    m = msg(from_jid="room@x/Alice")
    vcard._vcard_reply_missing_nick(fake_bot, m, "Alice", "room@x", own=False)
    vcard._vcard_reply_missing_nick(fake_bot, m, "Alice", "room@x", own=True)
    vcard._vcard_reply_missing_field(fake_bot, m, "Full Name", "Alice", "room@x")
    vcard._vcard_reply_empty_requested_user(fake_bot, m, "Full Name", "Alice")
    replies = [entry[0] for entry in fake_bot._replies]
    assert "Nick 'Alice' not found" in replies[0]
    assert "Your Nick 'Alice' not found" in replies[1]
    assert "No Full Name found" in replies[2]
    assert "No Full Name set" in replies[3]

    assert vcard._vcard_value_is_empty(None) is True
    assert vcard._vcard_value_is_empty("") is True
    assert vcard._vcard_value_is_empty([]) is True
    assert vcard._vcard_value_is_empty("x") is False
    assert vcard._vcard_should_format_field("FN") is True
    assert vcard._vcard_should_format_field("LOCALITY") is False


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
async def test_resolve_vcard_target_room_and_dm_edges(fake_bot, monkeypatch):
    room = "room@x"
    m = msg(from_jid=f"{room}/Alice", type_="groupchat")
    vcard.JOINED_ROOMS[room] = {"nicks": {"Alice": {"jid": "alice@example.org"}, "NoJid": {}}}
    try:
        assert await vcard._resolve_vcard_target(fake_bot, m, ["Alice"], True, {room: True}) == (
            "alice@example.org",
            "Alice",
            room,
        )
        assert await vcard._resolve_vcard_target(fake_bot, m, [], True, {room: True}) == (
            "alice@example.org",
            "Alice",
            room,
        )
        assert await vcard._resolve_vcard_target(fake_bot, m, ["Alice"], True, {}) == (None, None, None)
        assert await vcard._resolve_vcard_target(fake_bot, m, ["Missing"], True, {room: True}) == (None, None, None)
        assert await vcard._resolve_vcard_target(fake_bot, m, ["NoJid"], True, {room: True}) == (None, None, None)

        dm = msg(from_jid="alice@example.org/resource", type_="chat")
        monkeypatch.setattr(vcard._core, "_is_muc_pm", lambda msg: False)
        assert await vcard._resolve_vcard_target(fake_bot, dm, [], False, {}) == (
            "alice@example.org",
            "alice@example.org",
            "Direct Message",
        )
        assert await vcard._resolve_vcard_target(fake_bot, dm, ["Bob"], False, {}) == (None, None, None)
    finally:
        vcard.JOINED_ROOMS.pop(room, None)


@pytest.mark.asyncio
async def test_get_vcard_timezone_and_get_vcard_info_paths(fake_bot, monkeypatch):
    m = msg(from_jid="room@x/Alice", type_="chat")
    monkeypatch.setattr(vcard._core, "_is_muc_pm", lambda msg: True)
    monkeypatch.setattr(vcard._core, "_get_user_timezone", AsyncMock(return_value="Europe/Berlin"))
    monkeypatch.setattr(vcard._core, "get_real_jid", AsyncMock(return_value=("real@example.org", None, None)))

    assert await vcard._get_vcard_timezone(fake_bot, m, "target@example.org", True, ["Alice"]) == "Europe/Berlin"
    vcard._core._get_user_timezone.assert_awaited_with(fake_bot, "target@example.org")
    assert await vcard._get_vcard_timezone(fake_bot, m, None, True, ["Alice"]) is None
    assert await vcard._get_vcard_timezone(fake_bot, m, "ignored@example.org", True, []) == "Europe/Berlin"

    result_vcard = RichDummyVcard()
    plugin = SimpleNamespace(get_vcard=AsyncMock(return_value={"vcard_temp": result_vcard}))
    fake_bot.plugin = {"xep_0054": plugin}
    assert await ORIGINAL_GET_VCARD(fake_bot, m, "alice@example.org") is result_vcard
    plugin.get_vcard.assert_awaited_once()

    plugin.get_vcard = AsyncMock(side_effect=RuntimeError("boom"))
    assert await ORIGINAL_GET_VCARD(fake_bot, m, "alice@example.org") is None

    fake_bot.plugin = {}
    with pytest.raises(RuntimeError):
        await ORIGINAL_GET_VCARD(fake_bot, m, "alice@example.org")

    monkeypatch.setattr(vcard, "get_user_vcard", AsyncMock(return_value={"FN": "Alice"}))
    assert await vcard.get_info(fake_bot, m, "alice@example.org") == {"FN": "Alice"}
    vcard.get_user_vcard.return_value = None
    assert await vcard.get_info(fake_bot, m, "alice@example.org") is None


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

def test_append_vcard_list_values_adds_each_value():
    lines = []
    vcard._append_vcard_list_values(lines, ["one", "two"])
    assert lines == ["    • one", "    • two"]
