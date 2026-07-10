# ------------------------------------------------------------
# The following test ALWAYS FAILS when running as STANDALONE
# or only this file:
# async def test_muc_pm_usage(dummy_bot)
# ------------------------------------------------------------

import pytest
import asyncio
import types
import time
from unittest.mock import AsyncMock

from plugins import poll


# --- Dummy infrastructure for bot, rooms, etc. ---

class DummyRoom:
    def __init__(self, bare, resource="alice"):
        self.bare = bare
        self.resource = resource


class DummyMsg(dict):
    def __init__(self, from_bare="room@conf", mucnick="alice",
                 mtype="groupchat", body=None, thread=None, to=None):
        super().__init__()
        self["from"] = DummyRoom(from_bare, mucnick)
        self["type"] = mtype
        self["mucnick"] = mucnick
        self["body"] = body or ""
        self["to"] = to or DummyJID()  # Always set 'to'
        if thread:
            self["thread"] = thread


class DummyJID:
    def __init__(self, bare="bot@server"):
        self.bare = bare

    def __str__(self):
        return self.bare


class DummyStore:
    def __init__(self):
        self._data = {}

    async def get_global(self, key, default=None):
        return self._data.get(key, default)

    async def set_global(self, key, value):
        self._data[key] = value


class DummyPluginDict:
    def __init__(self, extra=None):
        self._plugdict = extra or {}

    def get(self, key, default=None):
        return self._plugdict.get(key, default)

    def __getitem__(self, key):
        return self._plugdict[key]


class DummyBot:
    def __init__(self):
        self._reply_log = []
        self.prefix = ","
        self.version = "1.0"
        self.boundjid = type("J", (),
                             {"bare": "bot@server", "resource": "bot"})()
        self.bot_plugins = types.SimpleNamespace(plugins={})
        self._stores = {"poll": DummyStore()}
        self.db = types.SimpleNamespace(
            users=types.SimpleNamespace(plugin=lambda name:
                                        self._stores.setdefault(name,
                                                                DummyStore())),
        )
        self.plugin = DummyPluginDict()
        # permissions: always role <= USER
        self._user_roles = {}

    async def get_user_role(self, jid, room=None):
        return self._user_roles.get(jid, 80)

    def reply(self, msg, text, mention=None, thread=None, rate_limit=None,
              ephemeral=None):
        if isinstance(text, (list, tuple)):
            value = "\n".join(str(x) for x in text)
        else:
            value = str(text)
        self._reply_log.append((msg, value))

    def make_message(self, mfrom=None, mto=None, mtype="groupchat",
                     mbody="", **kwargs):
        d = {"from": DummyRoom(mfrom or "room@conf"), "to": mto or DummyJID(),
             "type": mtype, "body": mbody}
        return d


def public_room_msg(args, nick="alice", body=None):
    if body is None:
        body = " ".join(str(x) for x in args)
    # Always set 'to'
    return DummyMsg(from_bare="room@conf", mucnick=nick, mtype="groupchat",
                    body=body, to=DummyJID())


def _any_line(log, substr):
    for _, txt in log:
        for line in txt.splitlines():
            if substr in line:
                return True
    return False


@pytest.fixture
def dummy_bot():
    bot = DummyBot()
    return bot


async def reset_poll_data(bot):
    poll_store = bot.db.users.plugin("poll")
    await poll_store.set_global("POLL", {"room@conf": True})
    await poll_store.set_global("POLL_DATA", {})
    poll._core.JOINED_ROOMS["room@conf"] = {"nicks": {"alice": {}}}
    poll.AUTO_CLOSE_TASKS.clear()


# --- Test helpers/private functions ---

def test__parse_create_args():
    # With duration
    d, q, opts, err = poll._parse_create_args("10m | Q? | A | B | C")
    assert d == 600 and q == "Q?" and opts == ["A", "B", "C"] and err is None
    # No duration
    d, q, opts, err = poll._parse_create_args("Q? | A | B")
    assert d is None and q == "Q?" and opts == ["A", "B"] and err is None
    # Not enough fields
    d, q, opts, err = poll._parse_create_args("one | onlyone", "!")
    assert err
    assert "Usage: !poll create" in err
    # Timed but not enough
    d, q, opts, err = poll._parse_create_args("5h | onlyQ | onl")
    assert err
    # Strip/cleanup: this triggers not enough non-empty fields; expect error
    # (not q == "bad" etc.)
    d, q, opts, err = poll._parse_create_args(" | | bad | | again")
    assert err


def test__normalize_poll_roundtrip():
    p = {"id": "5", "question": "Q", "options": ["A"], "votes": {"a": 1},
         "created_by": "x", "status": "open"}
    norm = poll._normalize_poll("r", "5", dict(p))
    assert int(norm["id"]) == 5
    again = poll._normalize_poll("r", "5", dict(norm))
    assert again == norm


def test__poll_vote_totals_and_winner_summary():
    p = {"options": ["A", "B"], "votes": {"user1": 0, "user2": 1, "user3": 0}}
    assert poll._poll_vote_totals(p) == [2, 1]
    assert poll._winner_summary(p).startswith("Winner: A")
    # Tie
    p2 = {"options": ["A", "B"], "votes": {"user1": 0, "user2": 1}}
    assert "Tie:" in poll._winner_summary(p2)
    # No votes
    p3 = {"options": ["A", "B"], "votes": {}}
    assert "Winner: none" in poll._winner_summary(p3)


def test__trim_history_limit():
    # Test MAX_HISTORY_PER_ROOM trimming mechanism
    bucket = {"polls": {}}
    now = poll._now()
    # Add 55 closed polls
    for i in range(55):
        bucket["polls"][str(i+1)] = {
            "id": str(i+1), "status": "closed", "created_at": now-200-i,
            "closed_at": now-100-i
        }
    poll._trim_history(bucket)
    closed = [k for k, p in bucket["polls"].items() if p["status"] == "closed"]
    assert len(closed) == poll.MAX_HISTORY_PER_ROOM


# --- Command coverage (async) ---

@pytest.mark.asyncio
async def test_poll_command_end_to_end(dummy_bot):
    await reset_poll_data(dummy_bot)
    bot = dummy_bot
    poll_store = bot.db.users.plugin("poll")
    await poll_store.set_global("POLL", {"room@conf": True})

    # 1. create poll
    args = ["create", "Choose A or B? | A | B"]
    msg = public_room_msg(args)
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert _any_line(bot._reply_log, "created")

    # 2. list polls
    args = ["list"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert _any_line(bot._reply_log, "Open polls")

    # 3. show poll
    args = ["show", "1"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert _any_line(bot._reply_log, "Poll #1:")

    # 4. show results (no votes yet)
    args = ["result", "1"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert _any_line(bot._reply_log, "Results:")

    # 5. vote (valid)
    args = ["vote", "1", "2"]
    msg = public_room_msg(args, nick="bob")
    bot._reply_log.clear()
    await poll.poll_command(bot, "bob@svr", "bob", args, msg, True)
    assert _any_line(bot._reply_log, "Your vote for poll #1 is now 'B'")

    # 6. repeat results, (should show vote for B)
    args = ["result", "1"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "bob@svr", "bob", args, msg, True)
    assert "B — 1" in "".join(txt for _, txt in bot._reply_log)

    # 7. vote invalid option (too high)
    args = ["vote", "1", "99"]
    msg = public_room_msg(args, nick="carol")
    bot._reply_log.clear()
    await poll.poll_command(bot, "carol@svr", "carol", args, msg, True)
    assert _any_line(bot._reply_log, "Option must be between")

    # 8. vote: non-existent poll
    args = ["vote", "88", "2"]
    msg = public_room_msg(args, nick="carol")
    bot._reply_log.clear()
    await poll.poll_command(bot, "carol@svr", "carol", args, msg, True)
    assert _any_line(bot._reply_log, "not found")

    # 9. history
    args = ["history"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert (_any_line(bot._reply_log, "Poll history")
            or _any_line(bot._reply_log, "No poll history"))

    # 10. close as poll owner
    args = ["close", "1"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert _any_line(bot._reply_log, "closed")

    # 11. try vote again after closed
    args = ["vote", "1", "2"]
    msg = public_room_msg(args, nick="carol")
    bot._reply_log.clear()
    await poll.poll_command(bot, "carol@svr", "carol", args, msg, True)
    assert _any_line(bot._reply_log, "is not open")

    # 12. cancel already closed
    args = ["cancel", "1"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert "already" in "".join(txt for _, txt in bot._reply_log)

    # 13. delete poll (after closed)
    args = ["delete", "1"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert _any_line(bot._reply_log, "deleted")

    # 14. create invalid-long question
    q = "q" * (poll.MAX_QUESTION_LEN+1)
    args = ["create", f"{q} | a | b"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert _any_line(bot._reply_log, "Question must be between")

    # 15. create too many options
    options = " | ".join([f"o{i}" for i in range(poll.MAX_OPTIONS+1)])
    args = ["create", f"Q | {options}"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert _any_line(bot._reply_log, "at most")

    # 16. create option too long
    option = "o" * (poll.MAX_OPTION_LEN+1)
    args = ["create", f"Q | a | {option} | b"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    assert _any_line(bot._reply_log, "at most")

    # 17. unknown subcommand
    args = ["XYZZZZZZZ"]
    msg = public_room_msg(args)
    bot._reply_log.clear()
    await poll.poll_command(bot, "bob@svr", "bob", args, msg, True)
    assert _any_line(bot._reply_log, "Unknown")


@pytest.mark.asyncio
async def test_muc_pm_usage(dummy_bot):
    await reset_poll_data(dummy_bot)
    bot = dummy_bot
    poll_store = bot.db.users.plugin("poll")
    await poll_store.set_global("POLL", {"room@conf": True})
    args = ["on"]
    # Simulate muc pm (not groupchat)
    msg = DummyMsg(from_bare="room@conf", mucnick="alice", mtype="chat",
                   body="poll on", to=DummyJID())
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, False)
    # On/off/status are handled, but voting isn't
    args = ["vote", "1", "1"]
    bot._reply_log.clear()
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, False)
    # Should get usage message for poll in PM as only on/off/status supported
    assert _any_line(bot._reply_log, "Use 'poll on/off/status'")


# --- Schedule/auto-close coverage ---

@pytest.mark.asyncio
async def test_poll_auto_close_and_restore(dummy_bot):
    await reset_poll_data(dummy_bot)
    bot = dummy_bot
    poll_store = bot.db.users.plugin("poll")
    room = "room@conf"
    await poll_store.set_global("POLL", {room: True})

    # Create poll with 1-second auto-close
    args = ["create", "1s | Q | A | B"]
    msg = public_room_msg(args)
    await poll.poll_command(bot, "alice@svr", "alice", args, msg, True)
    # Wait for poll to auto-close
    await asyncio.sleep(1.2)

    # Verify poll is closed
    data = await poll._get_data(bot)
    bucket = poll._room_bucket(data, room)
    poll_obj = poll._get_poll(bucket, "1")
    assert poll_obj and poll_obj["status"] != "open"

    # Test schedule/restore cleans up already closed polls
    await poll._restore_auto_close_tasks(bot)
    # No new scheduled tasks for closed poll
    assert not poll.AUTO_CLOSE_TASKS


# --- _can_manage_poll permissions ---

@pytest.mark.asyncio
async def test_can_manage_poll_owner_and_nonowner(dummy_bot):
    await reset_poll_data(dummy_bot)
    bot = dummy_bot
    room = "room@conf"
    poll_store = bot.db.users.plugin("poll")
    await poll_store.set_global("POLL", {room: True})
    msg = public_room_msg([], nick="alice")
    msg["from"].bare = "alice@svr"
    # Setup dummy poll
    poll_obj = {
        "id": 1, "question": "Q", "options": ["A", "B"], "votes": {},
        "created_by": "alice@svr", "status": "open"
    }
    # Direct poll creator
    can = await poll._can_manage_poll(bot, msg, True, poll_obj)
    assert can
    # Fallback: not creator, not moderator/admin, should be False
    poll_obj["created_by"] = "someone@svr"
    can = await poll._can_manage_poll(bot, msg, True, poll_obj)
    assert not can


@pytest.mark.asyncio
async def test_delete_poll_only_when_closed(dummy_bot):
    await reset_poll_data(dummy_bot)
    bot = dummy_bot
    room = "room@conf"
    poll_store = bot.db.users.plugin("poll")
    await poll_store.set_global("POLL", {room: True})
    state = {
        "rooms": {room: {"next_id": 2, "polls": {
            "1": {
                "id": 1, "question": "Q", "options": ["A"], "votes": {},
                "created_by": "alice@svr", "status": "open"
            }
        }}}
    }
    await poll_store.set_global("POLL_DATA", state)
    # Trying to delete an open poll should fail
    res, txt = await poll._delete_poll(bot, room, "1")
    assert not res and "still open" in txt
    # Now close and try again
    state["rooms"][room]["polls"]["1"]["status"] = "closed"
    await poll_store.set_global("POLL_DATA", state)
    res, txt = await poll._delete_poll(bot, room, "1")
    assert res and "deleted" in txt


# --- Direct test of _close_poll and error handling

@pytest.mark.asyncio
async def test_close_poll_cancel_and_error(dummy_bot):
    await reset_poll_data(dummy_bot)
    bot = dummy_bot
    room = "room@conf"
    # no poll
    res, txt = await poll._close_poll(bot, room, 99)
    assert not res and "not found" in txt
    # add poll and close
    poll_store = bot.db.users.plugin("poll")
    state = {"rooms": {room: {"next_id": 2, "polls": {
        "1": {
            "id": 1, "question": "Q", "options": ["A"], "votes": {},
            "created_by": "alice@svr", "status": "open"
        }
    }}}}
    await poll_store.set_global("POLL_DATA", state)
    # Close poll
    res, txt = await poll._close_poll(bot, room, 1)
    assert res and "closed" in txt
    # Try closing again
    res, txt = await poll._close_poll(bot, room, 1)
    assert not res and "already" in txt
    # Now test cancel path
    # Re-open, cancel poll
    state["rooms"][room]["polls"]["1"]["status"] = "open"
    await poll_store.set_global("POLL_DATA", state)
    res, txt = await poll._close_poll(bot, room, 1, cancelled=True)
    assert res and "cancelled" in txt


# --- plugin load/unload

@pytest.mark.asyncio
async def test_on_load_and_on_unload(dummy_bot):
    await reset_poll_data(dummy_bot)
    bot = dummy_bot
    await poll.on_load(bot)
    await poll.on_unload(bot)
    # Should not crash


# -- Test utils

def test__format_poll_header_and_options_and_results():
    poll_obj = {
        "id": 1, "question": "What?", "options": ["A", "B"],
        "votes": {"a": 0, "b": 1},
        "created_by": "alice", "created_by_nick": "Alice",
        "created_at": int(time.time()), "ends_at": None, "status": "open"
    }
    head = poll._format_poll_header(poll_obj)
    options = poll._format_poll_options(poll_obj)
    results = poll._format_poll_results(poll_obj)
    assert "Poll #1" in head
    assert "1. A" in options
    assert "Results:" in results


def test__format_ts_and_remaining():
    now = int(time.time())
    fut = now + 3662
    assert poll._format_ts(now).startswith(str(time.localtime(now).tm_year))
    assert "1h" in poll._format_remaining(fut)
    assert "no limit" in poll._format_remaining(None)

@pytest.mark.asyncio
async def test_poll_manage_allows_plugin_grant_fallback(monkeypatch, dummy_bot):
    msg = public_room_msg(["close", "1"], nick="alice")
    poll_obj = {
        "id": 1,
        "room_jid": "room@conf",
        "created_by": "other@example.org",
        "status": "open",
        "options": ["A", "B"],
        "votes": {},
    }

    async def fake_get_real_jid(bot, msg):
        return "alice@example.org", False, True

    async def fake_is_room_moderator_or_admin(bot, room_jid, nick):
        return False

    async def fake_user_has_room_plugin_grant(bot, jid, plugin, room_jid):
        assert jid == "alice@example.org"
        assert plugin == "poll"
        assert room_jid == "room@conf"
        return True

    monkeypatch.setattr(poll._core, "get_real_jid", fake_get_real_jid)
    monkeypatch.setattr(
        poll._core,
        "is_room_moderator_or_admin",
        fake_is_room_moderator_or_admin,
    )
    monkeypatch.setattr(
        poll,
        "user_has_room_plugin_grant",
        fake_user_has_room_plugin_grant,
    )

    assert await poll._can_manage_poll(dummy_bot, msg, True, poll_obj) is True


@pytest.mark.asyncio
async def test_cleanup_room_state_removes_poll_data_and_tasks(dummy_bot):
    await reset_poll_data(dummy_bot)
    room = "room@conf"
    other = "other@conf"
    data = {
        "rooms": {
            "Room@Conf": {"polls": {"1": {"status": "open"}}},
            other: {"polls": {"2": {"status": "open"}}},
        }
    }
    await poll._set_data(dummy_bot, data)

    class Task:
        def __init__(self, done=False):
            self.cancelled = False
            self._done = done

        def done(self):
            return self._done

        def cancel(self):
            self.cancelled = True

    matching_task = Task()
    done_task = Task(done=True)
    other_task = Task()
    poll.AUTO_CLOSE_TASKS.clear()
    poll.AUTO_CLOSE_TASKS.update({
        (room, 1): matching_task,
        (room, 2): done_task,
        (other, 3): other_task,
    })

    summary = await poll.cleanup_room_state(dummy_bot, "room@conf/nick")

    assert summary == {"rooms": 1, "auto_close_tasks": 1}
    assert matching_task.cancelled is True
    assert done_task.cancelled is False
    assert other_task.cancelled is False
    assert list(poll.AUTO_CLOSE_TASKS) == [(other, 3)]
    saved = await poll._get_data(dummy_bot)
    assert saved["rooms"] == {other: {"polls": {"2": {"status": "open"}}}}

class _PollPendingTask:
    def done(self):
        return False


class _PollDoneTask:
    def done(self):
        return True


@pytest.fixture(autouse=True)
def clear_poll_runtime_state():
    poll.AUTO_CLOSE_TASKS.clear()
    yield
    poll.AUTO_CLOSE_TASKS.clear()


@pytest.mark.asyncio
async def test_poll_runtime_state_global_and_room(monkeypatch):
    data = {
        "rooms": {
            "Room@Conf": {
                "polls": {
                    "1": {"status": "open"},
                    "2": {"status": "closed"},
                }
            },
            "bad@conf": {"polls": []},
        }
    }
    monkeypatch.setattr(poll, "_get_data", AsyncMock(return_value=data))
    poll.AUTO_CLOSE_TASKS[("room@conf", "1")] = _PollPendingTask()
    poll.AUTO_CLOSE_TASKS[("room@conf", "2")] = _PollDoneTask()
    poll.AUTO_CLOSE_TASKS[("other@conf", "3")] = _PollPendingTask()

    bot = DummyBot()

    assert await poll.get_runtime_state(bot, "room@conf/nick") == {
        "rooms": 1,
        "polls": 2,
        "active": 1,
        "auto_close_tasks": 1,
    }
    assert await poll.get_runtime_state(bot, "missing@conf") == {
        "rooms": 0,
        "polls": 0,
        "active": 0,
        "auto_close_tasks": 0,
    }
    assert await poll.get_runtime_state(bot) == {
        "rooms": 2,
        "polls": 2,
        "active": 1,
        "auto_close_tasks": 2,
    }


@pytest.mark.asyncio
async def test_poll_runtime_state_handles_non_dict_rooms(monkeypatch):
    monkeypatch.setattr(poll, "_get_data", AsyncMock(return_value={"rooms": []}))

    assert await poll.get_runtime_state(DummyBot()) == {
        "rooms": 0,
        "polls": 0,
        "active": 0,
        "auto_close_tasks": 0,
    }


@pytest.mark.asyncio
async def test_poll_restart_tasks_restarts_plugin_lifecycle(monkeypatch):
    bot = DummyBot()
    calls = []

    async def fake_on_unload(bot_arg):
        assert bot_arg is bot
        calls.append("unload")

    async def fake_on_load(bot_arg):
        assert bot_arg is bot
        calls.append("load")

    monkeypatch.setattr(poll, "on_unload", fake_on_unload)
    monkeypatch.setattr(poll, "on_load", fake_on_load)

    await poll.restart_tasks(bot)

    assert calls == ["unload", "load"]


def test_poll_multi_parse_normalize_totals_and_vote_choices(monkeypatch):
    monkeypatch.setattr(poll, "DEFAULT_MULTI_MAX_CHOICES", 3)
    assert poll._parse_multi_token("multi") == (True, 3)
    assert poll._parse_multi_token("multiple:2") == (True, 2)
    assert poll._parse_multi_token("multi:bad") == (True, None)
    assert poll._parse_multi_token("single") == (False, None)

    duration, question, options, multi_choice, max_choices, error = poll._parse_create_args_full(
        "15m | multi:2 | Lunch? | Pizza | Döner | Falafel"
    )
    assert duration == 900
    assert question == "Lunch?"
    assert options == ["Pizza", "Döner", "Falafel"]
    assert multi_choice is True
    assert max_choices == 2
    assert error is None

    _, _, _, multi_choice, max_choices, error = poll._parse_create_args_full(
        "multi:bad | Lunch? | Pizza | Döner"
    )
    assert multi_choice is False
    assert max_choices is None
    assert "Invalid multi-choice limit" in error

    p = poll._normalize_poll("room@conf", "7", {
        "question": "Lunch?",
        "options": ["Pizza", "Döner", "Falafel"],
        "votes": {"a": [0, 1], "b": [1, 2], "c": 2},
        "multi_choice": True,
        "max_choices": 99,
    })
    assert p["max_choices"] == 3
    assert poll._poll_vote_totals(p) == [1, 2, 2]
    assert "Tie: Döner, Falafel" in poll._winner_summary(p)

    assert poll._parse_vote_choices(["vote", "7", "1, 3"], p) == ([0, 2], None)
    choices, err = poll._parse_vote_choices(["vote", "7", "1,2,3,4"], p)
    assert choices is None
    assert "Option must be between 1 and 3" in err
    choices, err = poll._parse_vote_choices(["vote", "7", "1,2,3"], {**p, "max_choices": 2})
    assert choices is None
    assert "at most 2 choices" in err


@pytest.mark.asyncio
async def test_poll_command_multi_choice_end_to_end(dummy_bot):
    await reset_poll_data(dummy_bot)
    bot = dummy_bot
    create_args = ["create", "multi:2 | Lunch? | Pizza | Döner | Falafel"]
    await poll.poll_command(bot, "alice@svr", "alice", create_args, public_room_msg(create_args), True)
    assert _any_line(bot._reply_log, "Multi-choice: up to 2 choices")

    bot._reply_log.clear()
    await poll.poll_command(bot, "bob@svr", "bob", ["vote", "1", "1,3"], public_room_msg(["vote", "1", "1,3"], nick="bob"), True)
    assert _any_line(bot._reply_log, "Pizza")
    assert _any_line(bot._reply_log, "Falafel")

    bot._reply_log.clear()
    await poll.poll_command(bot, "carol@svr", "carol", ["vote", "1", "1,2,3"], public_room_msg(["vote", "1", "1,2,3"], nick="carol"), True)
    assert _any_line(bot._reply_log, "at most 2 choices")
