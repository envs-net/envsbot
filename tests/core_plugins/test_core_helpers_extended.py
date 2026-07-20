from __future__ import annotations

from types import SimpleNamespace

import pytest

from core_plugins import _core as xmpp_identity

room_toggles = xmpp_identity


class FakeJid:
    def __init__(self, bare: str, resource: str | None = None):
        self.bare = bare
        self.resource = resource


class FakeMsg(dict):
    def __init__(self, from_bare: str, resource: str | None = None, type_: str = "chat"):
        super().__init__()
        self["from"] = FakeJid(from_bare, resource)
        self["type"] = type_


@pytest.mark.asyncio
async def test_get_jids_from_nick_index_preserves_multi_jid_shapes():
    bot = SimpleNamespace(
        db=SimpleNamespace(
            users=SimpleNamespace(
                _nick_index={
                    "setnick": {"jid-a@example.test", "jid-b@example.test"},
                    "listnick": ["jid-c@example.test", "jid-d@example.test"],
                    "tuplenick": ("jid-e@example.test", "jid-f@example.test"),
                    "singlenick": "jid-g@example.test",
                    "emptynick": [],
                }
            )
        )
    )

    assert await xmpp_identity.get_jids_from_nick_index(bot, "setnick") in {
        "jid-a@example.test",
        "jid-b@example.test",
    }
    assert await xmpp_identity.get_jids_from_nick_index(bot, "listnick") == [
        "jid-c@example.test",
        "jid-d@example.test",
    ]
    assert await xmpp_identity.get_jids_from_nick_index(bot, "tuplenick") == (
        "jid-e@example.test",
        "jid-f@example.test",
    )
    assert await xmpp_identity.get_jids_from_nick_index(bot, "singlenick") == "jid-g@example.test"
    assert await xmpp_identity.get_jids_from_nick_index(bot, "emptynick") == []
    assert await xmpp_identity.get_jids_from_nick_index(bot, "missing") is None


def test_room_toggle_disabled_message_confirms_the_change():
    assert room_toggles._format_disabled("Feature") == "✅ Feature disabled in this room."


@pytest.mark.asyncio
async def test_muc_pm_manage_room_rejects_unknown_room_context(monkeypatch):
    monkeypatch.setattr(xmpp_identity, "JOINED_ROOMS", {})
    monkeypatch.setattr(xmpp_identity, "_is_muc_pm", lambda _msg: True)

    allowed, room_jid, reason = await xmpp_identity.muc_pm_sender_can_manage_room(
        SimpleNamespace(),
        FakeMsg("room@example.test", "Alice"),
        is_room=False,
    )

    assert allowed is False
    assert room_jid == "room@example.test"
    assert reason == "ℹ️ This command can only be used in a MUC DM."

class FakeStore:
    def __init__(self, state=None):
        self.state = state
        self.set_calls = []

    async def get_global(self, key, default=None):
        return self.state if self.state is not None else default

    async def set_global(self, key, value):
        self.set_calls.append((key, dict(value)))
        self.state = dict(value)


class ReplyBot(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.replies = []

    def reply(self, msg, text):
        self.replies.append(text)


async def _store_getter(store):
    async def getter(_bot):
        return store

    return getter


def test_basic_xmpp_identity_predicates(monkeypatch):
    monkeypatch.setattr(xmpp_identity, "JOINED_ROOMS", {"room@example.test": {}})
    muc_pm = FakeMsg("room@example.test", "Alice", "chat")
    assert xmpp_identity._is_muc_pm(muc_pm) is True
    assert xmpp_identity._is_public_muc(FakeMsg("room@example.test", "Alice", "groupchat"), True) is True
    assert xmpp_identity._is_public_muc(FakeMsg("room@example.test", "Alice", "chat"), False) is False
    assert xmpp_identity._normalize_bare_jid("user@example.test/resource") == "user@example.test"
    assert xmpp_identity._normalize_bare_jid(None) is None


@pytest.mark.asyncio
async def test_get_real_jid_groupchat_muc_pm_and_direct(monkeypatch):
    monkeypatch.setattr(
        xmpp_identity,
        "JOINED_ROOMS",
        {"room@example.test": {"nicks": {"Alice": {"jid": "alice@example.test/res"}}}},
    )
    bot = SimpleNamespace(
        plugin={"xep_0045": object()},
        boundjid=SimpleNamespace(bare="bot@example.test"),
        db=SimpleNamespace(users=SimpleNamespace(_nick_index={"Bob": "bob@example.test/res"})),
    )

    direct = FakeMsg("carol@example.test", None, "chat")
    direct["to"] = SimpleNamespace(bare="bot@example.test")
    assert await xmpp_identity.get_real_jid(bot, direct) == ("carol@example.test", False, False)

    group = FakeMsg("room@example.test", "Alice", "groupchat")
    group["to"] = SimpleNamespace(bare="room@example.test")
    assert await xmpp_identity.get_real_jid(bot, group) == ("alice@example.test", False, True)

    pm = FakeMsg("room@example.test", "Bob", "chat")
    pm["to"] = SimpleNamespace(bare="bot@example.test")
    assert await xmpp_identity.get_real_jid(bot, pm) == ("bob@example.test", True, False)


@pytest.mark.asyncio
async def test_user_timezone_helpers_and_fallbacks(caplog):
    class Store:
        def __init__(self, value=None, fail=False):
            self.value = value
            self.fail = fail

        async def get(self, jid, key):
            if self.fail:
                raise RuntimeError("db unavailable")
            return self.value

    class Users:
        def __init__(self, store):
            self.store = store

        def plugin(self, name):
            assert name == "vcard"
            return self.store

    bot = SimpleNamespace(db=SimpleNamespace(users=Users(Store("Europe/Berlin"))))
    assert await xmpp_identity._get_user_timezone(bot, "user@example.test") == "Europe/Berlin"
    assert str(await xmpp_identity.get_user_tzinfo(bot, "user@example.test")) == "Europe/Berlin"

    bot.db.users = Users(Store("Invalid/Zone"))
    assert await xmpp_identity._get_user_timezone(bot, "user@example.test") == "UTC"

    bot.db.users = Users(Store(fail=True))
    assert await xmpp_identity._get_user_timezone(bot, "user@example.test") == "UTC"
    assert await xmpp_identity._get_user_timezone(bot, None) == "UTC"


@pytest.mark.asyncio
async def test_enabled_room_and_plugin_store_helpers():
    store = FakeStore({"room@example.test": True})
    bot = SimpleNamespace(db=SimpleNamespace(users=SimpleNamespace(plugin=lambda name: store)))

    assert await xmpp_identity.get_plugin_store(bot, "example") is store
    assert await xmpp_identity._get_enabled_rooms(bot, "rooms", "example") == {"room@example.test": True}
    assert await xmpp_identity._is_enabled_for_room(bot, "rooms", "example", "room@example.test") is True
    assert await xmpp_identity.is_plugin_enabled_for_room(bot, await _store_getter(store), "rooms", "room@example.test") is True

    store.state = []
    assert await xmpp_identity._get_enabled_rooms(bot, "rooms", "example") == {}
    assert await xmpp_identity.is_plugin_enabled_for_room(bot, await _store_getter(store), "rooms", "room@example.test") is False


@pytest.mark.asyncio
async def test_ensure_user_exists_and_check_user_exists():
    class Users:
        def __init__(self):
            self.rows = {}
            self.created = []

        async def get(self, jid):
            return self.rows.get(jid)

        async def create(self, jid, nickname=None):
            self.rows[jid] = {"nickname": nickname}
            self.created.append((jid, nickname))

    users = Users()
    bot = ReplyBot(db=SimpleNamespace(users=users))
    await xmpp_identity._ensure_user_exists(bot, "user@example.test", "Alice")
    assert users.created == [("user@example.test", "Alice")]
    await xmpp_identity._ensure_user_exists(bot, "user@example.test", "Alice")
    assert users.created == [("user@example.test", "Alice")]

    assert await xmpp_identity._check_user_exists(bot, "user@example.test", FakeMsg("room", "Nick")) is True
    assert await xmpp_identity._check_user_exists(bot, "missing@example.test", FakeMsg("room", "Nick")) is False
    assert bot.replies[-1] == "🔴  You are not a registered user."


@pytest.mark.asyncio
async def test_ensure_user_exists_reraises_if_create_does_not_persist():
    class Users:
        async def get(self, jid):
            return None

        async def create(self, jid, nickname=None):
            raise RuntimeError("create failed")

    bot = SimpleNamespace(db=SimpleNamespace(users=Users()))
    with pytest.raises(RuntimeError):
        await xmpp_identity._ensure_user_exists(bot, "user@example.test")


@pytest.mark.asyncio
async def test_occupant_and_nick_lookup_helpers(monkeypatch):
    monkeypatch.setattr(
        xmpp_identity,
        "JOINED_ROOMS",
        {"room@example.test": {"nicks": {"Alice": {"jid": "alice@example.test", "affiliation": "member"}}}},
    )
    bot = SimpleNamespace(db=SimpleNamespace(users=SimpleNamespace(_nick_index={"Alice": "alice@example.test", "Al": ["alice@example.test"]})))
    msg = FakeMsg("room@example.test", "Alice", "groupchat")

    assert await xmpp_identity.get_real_jid_from_occupant(bot, msg) == "alice@example.test"
    assert await xmpp_identity.get_real_jid_from_occupant(bot, msg, "Alice") == "alice@example.test"
    assert await xmpp_identity.get_nicks_from_jid(bot, "alice@example.test") == ["Alice", "Al"]


@pytest.mark.asyncio
async def test_room_moderator_and_muc_pm_manage_room_paths(monkeypatch):
    async def get_user_role(jid, room=None):
        return xmpp_identity.Role.MODERATOR if jid == "mod@example.test" else xmpp_identity.Role.USER

    bot = SimpleNamespace(get_user_role=get_user_role)
    monkeypatch.setattr(
        xmpp_identity,
        "JOINED_ROOMS",
        {
            "room@example.test": {
                "nicks": {
                    "Owner": {"jid": "owner@example.test", "affiliation": "owner"},
                    "Mod": {"jid": "mod@example.test", "affiliation": "member"},
                    "User": {"jid": "user@example.test", "affiliation": "member"},
                }
            }
        },
    )

    assert await xmpp_identity.is_room_moderator_or_admin(bot, "room@example.test", "Owner") is True
    assert await xmpp_identity.is_room_moderator_or_admin(bot, "room@example.test", "Mod") is True
    assert await xmpp_identity.is_room_moderator_or_admin(bot, "room@example.test", "User") is False
    assert await xmpp_identity.is_room_moderator_or_admin(bot, "room@example.test", "Missing") is False

    assert await xmpp_identity.muc_pm_sender_can_manage_room(bot, FakeMsg("room@example.test", "Owner"), False) == (
        True,
        "room@example.test",
        None,
    )
    assert await xmpp_identity.muc_pm_sender_can_manage_room(bot, FakeMsg("room@example.test", "Mod"), False) == (
        True,
        "room@example.test",
        None,
    )
    allowed, room_jid, reason = await xmpp_identity.muc_pm_sender_can_manage_room(bot, FakeMsg("room@example.test", "User"), False)
    assert allowed is False
    assert room_jid == "room@example.test"
    assert reason == "⛔ Only room admins/owners can use on/off/status here."
    assert await xmpp_identity.muc_pm_sender_can_manage_room(bot, FakeMsg("room@example.test", "Owner"), True) == (
        False,
        "",
        "ℹ️ This command can only be used in a MUC DM.",
    )


@pytest.mark.asyncio
async def test_handle_room_toggle_command_full_lifecycle(monkeypatch):
    async def allowed(_bot, _msg, _is_room):
        return True, "room@example.test", None

    monkeypatch.setattr(room_toggles, "muc_pm_sender_can_manage_room", allowed)
    store = FakeStore({})
    bot = ReplyBot()
    msg = FakeMsg("room@example.test", "Owner")
    getter = await _store_getter(store)

    assert await room_toggles.handle_room_toggle_command(bot, msg, False, [], store_getter=getter, key="rooms", label="Feature") is False
    assert await room_toggles.handle_room_toggle_command(bot, msg, False, ["bogus"], store_getter=getter, key="rooms", label="Feature") is False

    assert await room_toggles.handle_room_toggle_command(bot, msg, False, ["status"], store_getter=getter, key="rooms", label="Feature") is True
    assert bot.replies[-1] == "ℹ️ Feature is **disabled** in this room."

    assert await room_toggles.handle_room_toggle_command(bot, msg, False, ["on"], store_getter=getter, key="rooms", label="Feature") is True
    assert store.state == {"room@example.test": True}
    assert bot.replies[-1] == "✅ Feature enabled in this room."

    assert await room_toggles.handle_room_toggle_command(bot, msg, False, ["on"], store_getter=getter, key="rooms", label="Feature") is True
    assert bot.replies[-1] == "ℹ️ Feature already enabled."

    assert await room_toggles.handle_room_toggle_command(bot, msg, False, ["off"], store_getter=getter, key="rooms", label="Feature") is True
    assert store.state == {}
    assert bot.replies[-1] == "✅ Feature disabled in this room."

    assert await room_toggles.handle_room_toggle_command(bot, msg, False, ["off"], store_getter=getter, key="rooms", label="Feature") is True
    assert bot.replies[-1] == "ℹ️ Feature already disabled."


@pytest.mark.asyncio
async def test_handle_room_toggle_command_denied_non_dict_and_bad_storage(monkeypatch):
    async def denied(_bot, _msg, _is_room):
        return False, "room@example.test", "nope"

    monkeypatch.setattr(room_toggles, "muc_pm_sender_can_manage_room", denied)
    bot = ReplyBot()
    getter = await _store_getter(FakeStore({}))
    assert await room_toggles.handle_room_toggle_command(bot, FakeMsg("room", "nick"), False, ["on"], store_getter=getter, key="rooms", label="Feature") is True
    assert bot.replies == ["nope"]

    async def allowed(_bot, _msg, _is_room):
        return True, "room@example.test", None

    monkeypatch.setattr(room_toggles, "muc_pm_sender_can_manage_room", allowed)
    store = FakeStore([])
    getter = await _store_getter(store)
    assert await room_toggles.handle_room_toggle_command(bot, FakeMsg("room", "nick"), False, ["on"], store_getter=getter, key="rooms", label="Feature") is True
    assert store.state == {"room@example.test": True}

    with pytest.raises(ValueError):
        await room_toggles.handle_room_toggle_command(bot, FakeMsg("room", "nick"), False, ["on"], store_getter=getter, key="rooms", label="Feature", storage="list")
