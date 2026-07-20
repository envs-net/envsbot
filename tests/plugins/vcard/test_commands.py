from .helpers import (
    msg,
    pytest,
    vcard,
)
from plugins.vcard import commands as vcard_commands
from utils.command import Role


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
async def test_resolve_vcard_target_room_and_dm_edges(fake_bot, monkeypatch):
    room = "room@x"
    m = msg(from_jid=f"{room}/Alice", type_="groupchat")
    vcard_commands.JOINED_ROOMS[room] = {"nicks": {"Alice": {"jid": "alice@example.org"}, "NoJid": {}}}
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
        monkeypatch.setattr(vcard_commands._core, "_is_muc_pm", lambda msg: False)
        assert await vcard._resolve_vcard_target(fake_bot, dm, [], False, {}) == (
            "alice@example.org",
            "alice@example.org",
            "Direct Message",
        )
        assert await vcard._resolve_vcard_target(fake_bot, dm, ["Bob"], False, {}) == (None, None, None)
    finally:
        vcard_commands.JOINED_ROOMS.pop(room, None)


def test_vcard_split_commands_preserve_command_metadata():
    expected = {
        vcard.vcard_command: ("vcard", ["v"]),
        vcard.get_fullname: ("fullname", ["f"]),
        vcard.get_nicknames: ("nicknames", ["nicks"]),
        vcard.get_timezone: ("timezone", ["tz"]),
        vcard.set_timezone: ("timezone set", ["tz set"]),
        vcard.get_organisations: ("organisations", ["orgs"]),
        vcard.get_notes: ("notes", []),
        vcard.get_email: ("emails", ["e"]),
        vcard.get_urls: ("urls", ["u"]),
        vcard.get_birthday: ("birthday", ["b"]),
    }

    for handler, (name, aliases) in expected.items():
        assert getattr(handler, "_command", None) == name
        assert getattr(handler, "_required_role", None) == Role.USER
        assert getattr(handler, "_aliases", []) == aliases
