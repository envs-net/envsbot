import pytest
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from unittest.mock import AsyncMock
from plugins import vcard
from plugins.vcard import fetch as vcard_fetch
from plugins.vcard import commands as vcard_commands


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
    monkeypatch.setattr(vcard_fetch, "get_vcard", get_vcard)
    monkeypatch.setattr(vcard_commands, "get_vcard", get_vcard)
    return DummyVcard


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


__all__ = [
    "pytest",
    "SimpleNamespace",
    "ET",
    "AsyncMock",
    "vcard",
    "ORIGINAL_GET_VCARD",
    "fake_bot",
    "msg",
    "patch_get_vcard",
    "RichDummyVcard",
]
