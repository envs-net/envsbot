import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import types

import plugins.pin as pin
from utils import formatting
from utils.message_cache import MessageCache


@pytest.fixture
def room_jid():
    return 'room@conference.example.com'


@pytest.fixture
def make_msg(room_jid):
    def _make(body="", is_room=True, resource="alice", msg_type="groupchat"):
        class DummyFrom:
            def __init__(self, bare, resource=None):
                self.bare = bare
                self.resource = resource
        msg = {
            "body": body,
            "from": DummyFrom(room_jid if is_room else "alice@example.com",
                              resource),
            "type": msg_type if is_room else "chat",
            "mucnick": resource if is_room else None,
        }
        return msg
    return _make


class DummyBot:
    def __init__(self):
        self.reply = Mock()
        self.db = types.SimpleNamespace(users=Mock())
        self.presence = types.SimpleNamespace()
        self.presence.joined_rooms = {}
        self.message_cache = MessageCache(max_messages=20)


@pytest.fixture
def bot():
    b = DummyBot()
    return b


@pytest.fixture(autouse=True)
def clean_caches():
    yield


@pytest.mark.asyncio
async def test_pin_command_non_room_add(bot, make_msg, monkeypatch):
    # Should warn to use add as reply/last if not in a room or muc pm
    msg = make_msg(is_room=False)
    await pin.pin_command(bot, "alice@example.com", "Alice", ["add", "last"],
                          msg, False)
    bot.reply.assert_called()
    out = str(bot.reply.call_args[0][1])
    # The actual reply here checks for the string below (per logic)
    assert "only works in rooms" in out


@pytest.mark.asyncio
async def test_pin_command_add_as_reply(monkeypatch, bot, make_msg, room_jid):
    msg = make_msg(body=">quoted\npin add", resource="alice")
    msg["type"] = "groupchat"
    bot.presence.joined_rooms[room_jid] = "alice"
    msg["from"].resource = "alice"
    monkeypatch.setattr(pin, "_is_enabled_for_room",
                        AsyncMock(return_value=True))
    monkeypatch.setattr(pin, "_sender_can_manage_pins_in_room",
                        AsyncMock(return_value=True))
    # Make sure body and quote logic triggers
    monkeypatch.setattr(pin, "extract_reply_quote",
                        lambda body: "hello world" if ">" in body else None)
    monkeypatch.setattr(pin, "_body_without_quote", lambda body: "pin add")
    monkeypatch.setattr(pin, "get_reply_target", lambda msg: "replyid123")
    bot.message_cache.get_by_id = Mock(
        return_value={"body": "Cached body", "nick": "bob", "stanza_id": "replyid123"}
    )
    monkeypatch.setattr(pin, "_create_pin_entry", AsyncMock(return_value=True))
    # ---- CRITICALLY PATCH _is_pin_add_command_body to return True ----
    monkeypatch.setattr(pin, "_is_pin_add_command_body", lambda body: True)
    # and ensure sender present for nick logic
    pin.JOINED_ROOMS[room_jid] = {"nicks": {"alice": {}}}
    handled = await pin._handle_reply_pin_add(bot, msg)
    assert handled is True  # Should call _create_pin_entry


@pytest.mark.asyncio
async def test_pin_command_list_no_pins(bot, make_msg, monkeypatch, room_jid):
    # Pin list when none
    msg = make_msg(is_room=True, body="", resource="alice")
    bot.presence.joined_rooms[room_jid] = "alice"
    monkeypatch.setattr(pin, "_is_enabled_for_room",
                        AsyncMock(return_value=True))
    # Load pin data returns empty
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value={}))
    await pin.pin_command(bot, "alice@example.com", "Alice", ["list"],
                          msg, True)
    bot.reply.assert_called()
    args = bot.reply.call_args[0][1]
    assert "No pinned messages" in str(args)


@pytest.mark.asyncio
async def test_pin_command_list_with_pins(bot, make_msg,
                                          monkeypatch, room_jid):
    msg = make_msg(is_room=True)
    bot.presence.joined_rooms[room_jid] = "alice"
    monkeypatch.setattr(pin, "_is_enabled_for_room",
                        AsyncMock(return_value=True))
    pin_obj = {
        "id": 1,
        "actor_nick": "alice",
        "created_at": 1234567890,
        "target_nick": "bob",
        "preview": "something cool",
    }
    state = {room_jid: {"pins": [pin_obj]}}
    # Simulate _load_pin_data returning pins in the test room
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value=state))
    await pin.pin_command(bot, "alice@example.com", "Alice", ["list"],
                          msg, True)
    args = "\n".join(bot.reply.call_args[0][1]) if isinstance(
        bot.reply.call_args[0][1], list) else str(bot.reply.call_args[0][1])
    # Accept both Pin # and #1 since the output has "• #1 by alice at ..."
    assert ("#1" in args or "Pin #" in args) and "alice" in args


@pytest.mark.asyncio
async def test_pin_command_show_and_delete(bot, make_msg,
                                           monkeypatch, room_jid):
    msg = make_msg(is_room=True)
    bot.presence.joined_rooms[room_jid] = "alice"
    monkeypatch.setattr(pin, "_is_enabled_for_room",
                        AsyncMock(return_value=True))
    pin_obj = {
        "id": 2,
        "actor_nick": "alice",
        "created_at": 1234567890,
        "target_nick": "bob",
        "preview": "hello",
    }
    bucket = {"pins": [pin_obj]}
    state = {room_jid: bucket}
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value=state))
    monkeypatch.setattr(pin, "_room_bucket", lambda s, r: s[r])
    # Show
    with patch.object(pin, "_find_pin", return_value=pin_obj):
        await pin.pin_command(bot, "alice@example.com", "Alice",
                              ["show", "2"], msg, True)
        if isinstance(bot.reply.call_args[0][1], list):
            out = "\n".join(bot.reply.call_args[0][1])
        else:
            out = str(bot.reply.call_args[0][1])
        assert "Pin #2" in out
    # Delete, with permission
    monkeypatch.setattr(pin, "_sender_can_manage_pins_in_room",
                        AsyncMock(return_value=True))
    with patch.object(pin, "_find_pin", return_value=pin_obj):
        with patch.object(pin, "_delete_pin", return_value=True):
            # no-op _save_pin_data
            monkeypatch.setattr(pin, "_save_pin_data", AsyncMock())
            await pin.pin_command(bot, "alice@example.com", "Alice",
                                  ["delete", "2"], msg, True)
            args = bot.reply.call_args[0][1]
            assert "Deleted pin" in str(args)


@pytest.mark.asyncio
async def test_pin_command_add_manual_last(bot, make_msg,
                                           monkeypatch, room_jid):
    msg = make_msg(is_room=True)
    bot.presence.joined_rooms[room_jid] = "alice"
    monkeypatch.setattr(pin, "_is_enabled_for_room",
                        AsyncMock(return_value=True))
    monkeypatch.setattr(pin, "_sender_can_manage_pins_in_room",
                        AsyncMock(return_value=True))
    # patch _get_recent_target
    pin_obj = {"body": "saved", "nick": "bob", "stanza_id": "stan"}
    monkeypatch.setattr(
        pin,
        "_get_recent_target",
        lambda bot_arg, room, offset=1: pin_obj,
    )
    monkeypatch.setattr(pin, "_create_pin_entry", AsyncMock())
    await pin.pin_command(bot, "alice@example.com", "Alice",
                          ["add", "last"], msg, True)
    bot.reply.assert_not_called()  # Should not reply if create succeeded


def test_trim_and_trim_preview():
    # Simple coverage for _trim and _trim_preview
    assert pin._trim("abc", 10) == "abc"
    assert pin._trim("a" * 10, 5).endswith("…")
    # The _trim_preview code collapses lines and clips at max_chars,
    # so e.g. "hello\nthere\nbye" with 2 lines, 6 chars only shows "hello…"
    assert pin._trim_preview(
        "hello\nthere\nbye", max_lines=2, max_chars=6) == "hello…"


def test_format_pin_line_and_find_delete():
    entry = {
        "id": 1,
        "actor_nick": "alice",
        "created_at": 1234567890,
        "target_nick": "bob",
        "preview": "x" * 12,
    }
    line = pin._format_pin_line(entry)
    assert "alice" in line and "bob" in line
    bucket = {"pins": [entry]}
    assert pin._find_pin(bucket, 1) == entry
    assert pin._delete_pin(bucket, 1)
    assert not pin._find_pin(bucket, 1)


def test_next_free_pin_id_and_generated_text():
    bucket = {"pins": [{"id": 1}, {"id": 2}]}
    assert pin._next_free_pin_id(bucket) == 3
    assert pin._is_pin_generated_text("📌 Pinned message as #1")
    assert not pin._is_pin_generated_text("something else")


def test_format_timestamp_str():
    assert pin._format_timestamp(1234567890).startswith("2009")


def test_room_bucket_new_and_existing():
    state = {}
    room = "abc"
    bucket = pin._room_bucket(state, room)
    assert "pins" in bucket
    bucket["pins"].append({"id": 1})
    bucket2 = pin._room_bucket(state, room)
    assert bucket2 is bucket


def test_is_pin_command_variants():
    pre = pin._prefix()
    assert pin._is_pin_command_message(f"{pre}pin")
    assert pin._is_pin_command_message(f"{pre}pin add")
    assert not pin._is_pin_command_message("notpin")


def test_body_without_quote():
    assert pin._body_without_quote(">hello\nhi\nthere") == "hi\nthere"
    assert pin._body_without_quote(">quoted") == ""


def test__trim_handles_none():
    assert pin._trim(None, 5) == ""


@pytest.mark.asyncio
async def test_create_pin_entry_rejects_missing_and_generated_text(bot, make_msg, monkeypatch, room_jid):
    msg = make_msg(body=",pin add", resource="alice")
    save = AsyncMock()
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value={}))
    monkeypatch.setattr(pin, "_save_pin_data", save)

    assert await pin._create_pin_entry(
        bot, msg, room_jid, "alice@example.org", "Alice", "", "bob",
        None, None, None, ",pin add", "quote"
    ) is True
    assert "Could not resolve" in bot.reply.call_args[0][1]
    save.assert_not_called()

    bot.reply.reset_mock()
    assert await pin._create_pin_entry(
        bot, msg, room_jid, "alice@example.org", "Alice",
        "📌 Pinned message as #1", "bot", None, None, None,
        ",pin add", "quote"
    ) is True
    assert "cannot be pinned" in bot.reply.call_args[0][1]
    save.assert_not_called()


@pytest.mark.asyncio
async def test_create_pin_entry_persists_full_entry(bot, make_msg, monkeypatch, room_jid):
    msg = make_msg(body=",pin add last", resource="alice")
    state = {}
    saved = AsyncMock()
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value=state))
    monkeypatch.setattr(pin, "_save_pin_data", saved)
    monkeypatch.setattr(pin.time, "time", lambda: 1234567890)

    assert await pin._create_pin_entry(
        bot=bot,
        msg=msg,
        room=room_jid,
        sender_jid="alice@example.org/resource",
        nick="Alice",
        target_text="hello&nbsp;world\nsecond line",
        target_nick="Bob",
        target_stanza_id="stanza-1",
        reply_id="reply-1",
        quote_text="hello world",
        cmd_body=",pin add last",
        source="last-1",
    ) is True

    saved.assert_awaited_once_with(bot, state)
    entry = state[room_jid][pin.PINS_FIELD][0]
    assert entry["id"] == 1
    assert entry["room"] == room_jid
    assert entry["created_at"] == 1234567890
    assert entry["actor_nick"] == "alice"
    assert entry["actor_jid"] == room_jid
    assert entry["reply_id"] == "reply-1"
    assert entry["target_stanza_id"] == "stanza-1"
    assert entry["target_nick"] == "Bob"
    assert entry["source"] == "last-1"
    assert entry["client_quote_available"] is True
    reply_lines = bot.reply.call_args[0][1]
    assert "📌 Pinned message as #1." in reply_lines
    assert "Preview: hello\xa0world" in reply_lines[-1]


@pytest.mark.asyncio
async def test_on_groupchat_message_only_handles_reply_fallback(bot, make_msg, monkeypatch):
    handler = AsyncMock(return_value=False)
    monkeypatch.setattr(pin, "_handle_reply_pin_add", handler)
    msg = make_msg(body="hello", resource="alice")

    await pin._on_groupchat_message(bot, msg)

    handler.assert_awaited_once_with(bot, msg)
    assert bot.message_cache.get_messages(str(msg["from"].bare)) == []


@pytest.mark.asyncio
async def test_on_groupchat_message_accepts_handled_reply_pin(bot, make_msg, monkeypatch):
    handler = AsyncMock(return_value=True)
    monkeypatch.setattr(pin, "_handle_reply_pin_add", handler)
    msg = make_msg(body=">old\n,pin add")

    await pin._on_groupchat_message(bot, msg)

    handler.assert_awaited_once_with(bot, msg)


@pytest.mark.asyncio
async def test_pin_on_load_registers_groupchat_handler(bot):
    registered = []
    bot.bot_plugins = types.SimpleNamespace(
        register_event=lambda *args, **kwargs: registered.append((args, kwargs))
    )

    await pin.on_load(bot)

    assert registered
    args, kwargs = registered[0]
    assert args[0] == "pin"
    assert args[1] == "groupchat_message"
    assert callable(args[2])
    assert kwargs == {}


def test_pin_store_and_recent_target_helpers(monkeypatch):
    assert pin._normalize_pin_data(None) == {}
    assert pin._normalize_pin_data({"room": {"pins": "bad"}, 123: []}) == {
        "room": {"pins": []},
        "123": {"pins": []},
    }

    assert pin._is_pin_add_command_body(" ,pin add ")
    assert not pin._is_pin_add_command_body(",pin add last")

    entries = [
        {"body": "   ", "nick": "blank"},
        {"body": ",pin add", "nick": "cmd"},
        {"body": "📌 Pinned message as #1", "nick": "bot"},
        {"body": "first", "nick": "alice"},
        {"body": "second", "nick": "bob"},
    ]
    monkeypatch.setattr(pin, "_recent_cache_entries", lambda bot, room: list(entries))

    fake_bot = object()
    assert pin._get_recent_target(fake_bot, "room", offset=0) is None
    assert pin._get_recent_target(fake_bot, "room", offset=1)["body"] == "second"
    assert pin._get_recent_target(fake_bot, "room", offset=2)["body"] == "first"
    assert pin._get_recent_target(fake_bot, "room", offset=3) is None

    monkeypatch.setattr(pin, "_recent_cache_entries", lambda bot, room: [])
    assert pin._get_recent_target(fake_bot, "room") is None


def test_pin_load_save_helpers(monkeypatch):
    class Store:
        def __init__(self):
            self.data = {"room": {"pins": [{"id": 1}]}}
            self.saved = None

        async def get_global(self, key, default=None):
            assert key == pin.PIN_DATA_KEY
            return self.data

        async def set_global(self, key, value):
            assert key == pin.PIN_DATA_KEY
            self.saved = value

    store = Store()
    bot = MagicMock()
    bot.db.users.plugin.return_value = store

    async def run():
        assert await pin._load_pin_data(bot) == store.data
        await pin._save_pin_data(bot, {"room": {"pins": []}})
        assert store.saved == {"room": {"pins": []}}

    import asyncio
    asyncio.run(run())

@pytest.mark.asyncio
async def test_pin_permission_and_recent_cache_direct_helpers(monkeypatch, make_msg, room_jid):
    checks = []

    async def fake_is_mod(bot_arg, room_arg, nick_arg):
        checks.append((room_arg, nick_arg))
        return nick_arg == "alice"

    monkeypatch.setattr(pin, "is_room_moderator_or_admin", fake_is_mod)
    bot = MagicMock()
    assert await pin._sender_can_manage_pins_in_room(bot, make_msg(resource="alice"), room_jid) is True
    assert await pin._sender_can_manage_pins_in_room(bot, make_msg(resource="bob"), room_jid) is False
    assert checks == [(room_jid, "alice"), (room_jid, "bob")]

    entries = [{"body": "hello"}]
    bot.message_cache = MagicMock()
    bot.message_cache.get_messages.return_value = entries
    assert pin._recent_cache_entries(bot, room_jid) == entries
    bot.message_cache.get_messages.assert_called_once_with(room_jid)

@pytest.mark.asyncio
async def test_pin_management_allows_plugin_grant_fallback(monkeypatch, bot, make_msg, room_jid):
    msg = make_msg(resource="alice")
    monkeypatch.setattr(pin, "is_room_moderator_or_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(
        pin,
        "get_real_jid",
        AsyncMock(return_value=("alice@example.org", False, True)),
    )
    monkeypatch.setattr(
        pin,
        "user_has_room_plugin_grant",
        AsyncMock(return_value=True),
    )

    assert await pin._sender_can_manage_pins_in_room(bot, msg, room_jid) is True
    pin.user_has_room_plugin_grant.assert_awaited_once_with(
        bot,
        "alice@example.org",
        "pin",
        room_jid,
    )


@pytest.mark.asyncio
async def test_cleanup_room_state_removes_pin_room_data(bot):
    store = {
        pin.PIN_DATA_KEY: {
            "Room@Conference.Example.Com": {"pins": [{"id": 1}]},
            "other@conference.example.com": {"pins": [{"id": 2}]},
        }
    }

    class Store:
        async def get_global(self, key, default=None):
            return store.get(key, default)

        async def set_global(self, key, value):
            store[key] = value

    bot.db.users.plugin.return_value = Store()

    assert await pin.cleanup_room_state(
        bot,
        "room@conference.example.com/nick",
    ) == {"rooms": 1}
    assert store[pin.PIN_DATA_KEY] == {
        "other@conference.example.com": {"pins": [{"id": 2}]},
    }
    assert await pin.cleanup_room_state(
        bot,
        "missing@conference.example.com",
    ) == {"rooms": 0}

@pytest.mark.asyncio
async def test_pin_runtime_state_global_and_room(monkeypatch):
    state = {
        "Room@Conf": {pin.PINS_FIELD: [{"id": "1"}, {"id": "2"}]},
        "other@conf": {pin.PINS_FIELD: [{"id": "3"}]},
    }
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value=state))

    bot = MagicMock()

    assert await pin.get_runtime_state(bot, "room@conf/nick") == {"rooms": 1, "pins": 2}
    assert await pin.get_runtime_state(bot, "missing@conf") == {"rooms": 0, "pins": 0}
    assert await pin.get_runtime_state(bot) == {"rooms": 2, "pins": 3}



def _reply_text(reply_mock):
    value = reply_mock.call_args[0][1]
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def test_pin_search_helpers_parse_and_match_expected_fields():
    entry = {
        "id": 12,
        "actor_nick": "Creme",
        "created_at": 1234567890,
        "target_nick": "Bob",
        "preview": "Mail setup overview",
        "target_text": "Use IMAP on mail.envs.net with your shell password.",
        "source": "reply-cache",
    }

    assert pin._parse_pin_search_args(["search"]) is None
    assert pin._parse_pin_search_args(["search", "123"]) == ("123", formatting.PageRequest(all=True))
    assert pin._parse_pin_search_args(["search", "mail", "2"]) == ("mail", formatting.PageRequest(page=2))
    assert pin._parse_pin_search_args(["find", "ssh", "key"]) == ("ssh key", formatting.PageRequest(all=True))

    assert pin._pin_matches_query(entry, "MAIL imap")
    assert pin._pin_matches_query(entry, "creme")
    assert pin._pin_matches_query(entry, "bob")
    assert pin._pin_matches_query(entry, "reply-cache")
    assert pin._pin_matches_query(entry, "#12")
    assert pin._pin_matches_query(entry, "2009")
    assert not pin._pin_matches_query(entry, "postgres")
    assert not pin._pin_matches_query(entry, "")
    assert pin._is_pin_generated_text("📌 Pin search for room: \"mail\"")


@pytest.mark.asyncio
async def test_pin_command_search_matches_all_terms_and_paginates(bot, make_msg, monkeypatch, room_jid):
    msg = make_msg(is_room=True)
    entries = [
        {
            "id": 1,
            "actor_nick": "alice",
            "created_at": 1234567890,
            "target_nick": "bob",
            "preview": "Mail setup",
            "target_text": "Configure IMAP and SMTP.",
            "source": "quote",
        },
        {
            "id": 2,
            "actor_nick": "carol",
            "created_at": 1234567891,
            "target_nick": "dave",
            "preview": "SSH key upload",
            "target_text": "Put your public key into the web panel.",
            "source": "last-1",
        },
        {
            "id": 3,
            "actor_nick": "erin",
            "created_at": 1234567892,
            "target_nick": "frank",
            "preview": "Mail alias",
            "target_text": "Mail aliases are managed via users.envs.net.",
            "source": "reply-cache",
        },
    ]
    state = {room_jid: {pin.PINS_FIELD: entries}}
    monkeypatch.setattr(pin, "_is_enabled_for_room", AsyncMock(return_value=True))
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value=state))
    monkeypatch.setattr(pin, "PAGE_SIZE", 1)

    await pin.pin_command(bot, "alice@example.com", "Alice", ["search", "mail"], msg, True)
    out = _reply_text(bot.reply)
    assert "Pin search" in out
    assert "\"mail\" (2 matches) - all" in out
    assert "#3" in out
    assert "#1" in out
    assert "next page" not in out

    bot.reply.reset_mock()
    await pin.pin_command(bot, "alice@example.com", "Alice", ["search", "mail", "2"], msg, True)
    out = _reply_text(bot.reply)
    assert "Page 2/2" in out
    assert "#1" in out
    assert "#3" not in out

    bot.reply.reset_mock()
    await pin.pin_command(bot, "alice@example.com", "Alice", ["find", "mail", "alias"], msg, True)
    out = _reply_text(bot.reply)
    assert "\"mail alias\" (1 matches)" in out
    assert "#3" in out
    assert "#1" not in out


@pytest.mark.asyncio
async def test_pin_command_search_usage_no_matches_and_disabled(bot, make_msg, monkeypatch, room_jid):
    msg = make_msg(is_room=True)
    state = {room_jid: {pin.PINS_FIELD: [{"id": 1, "preview": "Mail setup"}]}}
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value=state))
    enabled = AsyncMock(return_value=True)
    monkeypatch.setattr(pin, "_is_enabled_for_room", enabled)

    await pin.pin_command(bot, "alice@example.com", "Alice", ["search"], msg, True)
    assert "Usage: ,pin search <query> [page]" in _reply_text(bot.reply)

    bot.reply.reset_mock()
    await pin.pin_command(bot, "alice@example.com", "Alice", ["search", "postgres"], msg, True)
    assert 'No pins matching "postgres"' in _reply_text(bot.reply)

    bot.reply.reset_mock()
    enabled.return_value = False
    await pin.pin_command(bot, "alice@example.com", "Alice", ["search", "mail"], msg, True)
    assert "disabled in this room" in _reply_text(bot.reply)


def test_pin_tags_normalize_format_and_search():
    assert pin._normalize_pin_tags(["#Mail", "mail", "support,ssh", "bad!"]) == [
        "mail",
        "support",
        "ssh",
        "bad",
    ]
    assert pin._format_pin_tags(["Mail", "support"]) == "#mail #support"
    entry = {"id": 4, "preview": "Room setup", "tags": ["mail", "support"]}
    assert pin._pin_matches_query(entry, "#mail")
    assert pin._pin_matches_query(entry, "support")


@pytest.mark.asyncio
async def test_pin_command_edit_and_tags(bot, make_msg, monkeypatch, room_jid):
    msg = make_msg(is_room=True)
    state = {
        room_jid: {
            pin.PINS_FIELD: [
                {"id": 7, "preview": "old", "target_text": "old", "tags": []}
            ]
        }
    }
    saved = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(pin, "_is_enabled_for_room", AsyncMock(return_value=True))
    monkeypatch.setattr(pin, "_sender_can_manage_pins_in_room", AsyncMock(return_value=True))
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value=state))
    monkeypatch.setattr(pin, "_save_pin_data", saved)
    monkeypatch.setattr(pin, "audit_event", audit)
    monkeypatch.setattr(pin.time, "time", lambda: 123)

    await pin.pin_command(
        bot,
        "alice@example.com",
        "Alice",
        ["edit", "7", "new", "knowledge", "base"],
        msg,
        True,
    )

    entry = state[room_jid][pin.PINS_FIELD][0]
    assert entry["target_text"] == "new knowledge base"
    assert entry["preview"] == "new knowledge base"
    assert entry["updated_at"] == 123
    saved.assert_awaited_with(bot, state)
    audit.assert_awaited()
    assert "Updated pin #7" in _reply_text(bot.reply)

    bot.reply.reset_mock()
    saved.reset_mock()
    audit.reset_mock()
    await pin.pin_command(
        bot,
        "alice@example.com",
        "Alice",
        ["tags", "7", "#mail", "Support", "mail"],
        msg,
        True,
    )

    assert entry["tags"] == ["mail", "support"]
    saved.assert_awaited_with(bot, state)
    audit.assert_awaited_once()
    assert "#mail #support" in _reply_text(bot.reply)

    bot.reply.reset_mock()
    await pin.pin_command(
        bot,
        "alice@example.com",
        "Alice",
        ["tags", "7"],
        msg,
        True,
    )
    assert "Pin #7 tags: #mail #support" in _reply_text(bot.reply)


@pytest.mark.asyncio
async def test_pin_important_marks_lists_and_unstars(bot, make_msg, monkeypatch, room_jid):
    state = {
        room_jid: {
            "pins": [
                {"id": 1, "actor_nick": "alice", "target_nick": "bob", "preview": "normal"},
                {"id": 2, "actor_nick": "alice", "target_nick": "bob", "preview": "important"},
            ]
        }
    }
    saved = AsyncMock()
    monkeypatch.setattr(pin, "_is_enabled_for_room", AsyncMock(return_value=True))
    monkeypatch.setattr(pin, "_sender_can_manage_pins_in_room", AsyncMock(return_value=True))
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value=state))
    monkeypatch.setattr(pin, "_save_pin_data", saved)
    monkeypatch.setattr(pin, "audit_event", AsyncMock())
    msg = make_msg(is_room=True, body=",pin important 1 on", resource="alice")

    await pin._pin_command_important(bot, msg, room_jid, ["important", "1", "on"])
    assert state[room_jid]["pins"][0]["important"] is True
    assert "marked as important" in bot.reply.call_args[0][1]
    saved.assert_awaited()

    bot.reply.reset_mock()
    await pin._pin_command_important(bot, msg, room_jid, ["important", "list"])
    reply_lines = bot.reply.call_args[0][1]
    assert reply_lines[0].startswith("⭐ Important pins")
    assert any("#1" in line for line in reply_lines)

    bot.reply.reset_mock()
    await pin._pin_command_important(bot, msg, room_jid, ["unstar", "1"])
    assert state[room_jid]["pins"][0]["important"] is False
    assert "marked as normal" in bot.reply.call_args[0][1]


@pytest.mark.asyncio
async def test_pin_important_usage_permission_and_not_found(bot, make_msg, monkeypatch, room_jid):
    state = {room_jid: {"pins": [{"id": 1, "preview": "x"}]}}
    monkeypatch.setattr(pin, "_is_enabled_for_room", AsyncMock(return_value=True))
    monkeypatch.setattr(pin, "_load_pin_data", AsyncMock(return_value=state))
    msg = make_msg(is_room=True, resource="alice")

    await pin._pin_command_important(bot, msg, room_jid, ["important", "list", "bad"])
    assert "Usage" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    monkeypatch.setattr(pin, "_sender_can_manage_pins_in_room", AsyncMock(return_value=False))
    await pin._pin_command_important(bot, msg, room_jid, ["important", "1", "on"])
    assert "Only room moderators" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    monkeypatch.setattr(pin, "_sender_can_manage_pins_in_room", AsyncMock(return_value=True))
    await pin._pin_command_important(bot, msg, room_jid, ["important", "2", "on"])
    assert "not found" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    await pin._pin_command_important(bot, msg, room_jid, ["important", "not-int", "on"])
    assert "Usage" in bot.reply.call_args[0][1]

    bot.reply.reset_mock()
    await pin._pin_command_important(bot, msg, room_jid, ["important", "1", "maybe"])
    assert "Usage" in bot.reply.call_args[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("subcommand", ["delete", "del", "remove", "rm"])
async def test_pin_delete_subcommand_aliases_dispatch_identically(
    bot, make_msg, monkeypatch, room_jid, subcommand
):
    msg = make_msg(is_room=True, resource="alice")
    monkeypatch.setattr(
        pin, "handle_room_toggle_command", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(pin, "_room_key_from_msg", lambda *_args: room_jid)
    delete_handler = AsyncMock()
    monkeypatch.setattr(pin, "_pin_command_delete", delete_handler)

    await pin.pin_command(
        bot,
        "alice@example.com",
        "Alice",
        [subcommand, "7"],
        msg,
        True,
    )

    delete_handler.assert_awaited_once_with(
        bot, msg, room_jid, [subcommand, "7"]
    )
