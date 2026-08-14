import asyncio
from unittest.mock import AsyncMock, Mock
import pytest
import types
import os
import json
from datetime import datetime, timedelta, timezone

import core_plugins._admin as _admin

import pytest_asyncio


class Sender:
    def __str__(self): return "jid/sender"
    @property
    def bare(self): return "jid"


class DummyMsg:
    def __init__(self, groupchat=False):
        self.from_ = types.SimpleNamespace(bare="room@conf", resource="BOT")
        self.type = "groupchat" if groupchat else "chat"

    def __getitem__(self, key):
        if key == "from":
            return self.from_
        if key == "type":
            return self.type
        raise KeyError(key)

    def get(self, key, default=None):
        if key == "from":
            return self.from_
        if key == "type":
            return self.type
        return default
    # Attribute access fallback

    def __getattr__(self, key):
        if key == "from":
            return self.from_
        if key == "type":
            return self.type
        raise AttributeError(key)


@pytest_asyncio.fixture
async def fake_bot(monkeypatch):
    """
    Creates a fake bot object with all needed attributes for _admin commands.
    """
    class FakeDB:
        def __init__(self):
            self.closed = False
            self.path = "/tmp/test.db"
            self.conn = object()

        async def close(self):
            self.closed = True

        async def fetch_one(self, query):
            if "integrity_check" in query:
                return ("ok",)
            return (1,)

    class FakePlugins:
        @staticmethod
        def discover():
            return ["x", "y", "z"]
        plugins = {"foo": None, "bar": None}
        meta = {"foo": {"version": "1.0", "category": "test"}}

    class FakeBound:
        @property
        def bare(self): return "bot@domain"
        def __str__(self): return "bot@domain"
    bot = types.SimpleNamespace()
    bot.disconnected = await _awaitable(True)
    bot.db = FakeDB()
    bot.prefix = ","
    bot.bot_plugins = FakePlugins()
    bot.boundjid = FakeBound()
    bot.reply = lambda msg, text, *a, **k: bot._replies.append((text, msg))
    bot._replies = []
    bot.disconnect = lambda: setattr(bot, "disco", True)
    bot.connection_start_time = datetime.now() - timedelta(hours=1,
                                                           minutes=3,
                                                           seconds=2)
    bot.version = "1.3.0"
    bot.last_version_check_result = None
    bot.last_update_notified_version = None
    bot.presence = types.SimpleNamespace(status={"show": "chat", "status": "ready"})
    bot.avatar_hash = "abc123"
    return bot


async def _awaitable(val):
    return val


def test_human_time():
    assert _admin.human_time(0) == "0s"
    assert _admin.human_time(-5) == "0s"
    assert _admin.human_time(61) == "1m 1s"
    assert _admin.human_time(3662) == "1h 1m 2s"
    assert _admin.human_time(3600*26+120+12) == "1d 2h 2m 12s"


def test_human_size():
    assert _admin.human_size(0) == "0 B"
    assert _admin.human_size(-1) == "unknown"
    assert _admin.human_size(1024) == "1.0 KiB"
    assert _admin.human_size(1024*1024) == "1.0 MiB"
    assert _admin.human_size(123456789) == "117.7 MiB"
    assert _admin.human_size(int(1e12)) == "931.3 GiB"


def test_set_bot_start_time_sets_global():
    bot = object()
    _admin.BOT_START_TIME = None
    _admin.set_bot_start_time(bot)
    assert isinstance(_admin.BOT_START_TIME, datetime)
    old_time = _admin.BOT_START_TIME
    # Should not reset if called again
    _admin.set_bot_start_time(bot)
    assert _admin.BOT_START_TIME == old_time


@pytest.mark.asyncio
async def test_bot_status_success_and_all_fields(monkeypatch, fake_bot):
    _admin.BOT_START_TIME = datetime.now() - timedelta(hours=2)
    _admin.JOINED_ROOMS.clear()
    _admin.JOINED_ROOMS["room1"] = {"nick": "anon1"}
    _admin.JOINED_ROOMS["room2"] = {"nick": "anon2"}
    fake_bot.client_roster = {
        "bot@domain": {"subscription": "both"},
        "room1": {"subscription": "both"},
        "alice@example.org": {"subscription": "both"},
        "removed@example.org": {"subscription": "remove"},
    }
    # Patch psutil
    monkeypatch.setattr(_admin, "psutil", types.SimpleNamespace(
        Process=lambda x=None: types.SimpleNamespace(
            memory_info=lambda: types.SimpleNamespace(rss=12*1024*1024),
            cpu_percent=lambda x: 42.0
        ),
        getloadavg=lambda: (1.23, 4.56, 7.89),
        cpu_count=lambda: 8
    ))
    monkeypatch.setattr(os.path, "getsize", lambda p: 12345)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    from utils.health import HealthCheck, HealthSnapshot

    monkeypatch.setattr(
        _admin,
        "collect_health_snapshot",
        AsyncMock(
            return_value=HealthSnapshot(
                checked_at="now",
                checks={
                    "alerts": HealthCheck("alerts", "ok", "no alerts", {"active": 0}),
                    "outbox": HealthCheck("outbox", "unknown", "unavailable"),
                    "message_cache": HealthCheck(
                        "message_cache", "unknown", "unavailable"
                    ),
                },
            )
        ),
    )
    await _admin.bot_status(fake_bot, Sender(), "nick", [], DummyMsg(), False)
    replies = fake_bot._replies
    assert any(isinstance(r[0], list)
               and "🤖 EnvsBot Status" in r[0][0] for r in replies)
    reply_lines = replies[-1][0]
    reply = "\n".join(reply_lines)
    assert "Core:" in reply
    assert "Runtime:" in reply
    assert "XMPP:" in reply
    assert "Rooms: 2 joined MUCs · 1 direct contact (1:1/DM)" in reply
    assert "Plugins:" in reply
    assert "Database:" in reply
    assert "Health:" in reply
    assert "Overall: ✅ OK" in reply
    assert "Avatar: published" in reply
    assert "Integrity: ok" in reply


@pytest.mark.asyncio
async def test_bot_version_shows_current_and_latest(fake_bot):
    replies = []
    fake_bot.reply = lambda msg, text, *a, **k: replies.append((text, k))
    fake_bot.last_version_check_result = "1.4.0"

    await _admin.bot_version(fake_bot, Sender(), "nick", [], DummyMsg(), False)

    text, kwargs = replies[-1]
    reply = "\n".join(text)
    assert "🏷️ EnvsBot Version" in reply
    assert "Current: v1.3.0" in reply
    assert "Latest release: v1.4.0" in reply
    assert kwargs["no_store"] is False


@pytest.mark.asyncio
async def test_bot_checkupdate_reports_new_version(monkeypatch, fake_bot):
    replies = []
    fake_bot.reply = lambda msg, text, *a, **k: replies.append((text, k))

    async def fake_check(bot, *, announce=True, require_enabled=True):
        return True, "1.4.0", None

    monkeypatch.setattr(_admin, "check_for_updates_once", fake_check)

    await _admin.bot_checkupdate(fake_bot, Sender(), "nick", [], DummyMsg(), False)

    text, kwargs = replies[-1]
    reply = "\n".join(text)
    assert "New EnvsBot version available: v1.4.0" in reply
    assert "Current version: v1.3.0" in reply
    assert kwargs["no_store"] is False


@pytest.mark.asyncio
async def test_bot_checkupdate_reports_current(monkeypatch, fake_bot):
    replies = []
    fake_bot.reply = lambda msg, text, *a, **k: replies.append((text, k))
    fake_bot.reply_ok = lambda msg, text, **k: fake_bot.reply(msg, f"✅ {text}", **k)

    async def fake_check(bot, *, announce=True, require_enabled=True):
        return False, "1.3.0", None

    monkeypatch.setattr(_admin, "check_for_updates_once", fake_check)

    await _admin.bot_checkupdate(fake_bot, Sender(), "nick", [], DummyMsg(), False)

    assert "up to date" in replies[-1][0]
    assert replies[-1][1]["no_store"] is False


@pytest.mark.asyncio
async def test_bot_checkupdate_reports_error(monkeypatch, fake_bot):
    replies = []
    fake_bot.reply_warn = lambda msg, text, **k: replies.append((text, k))

    async def fake_check(bot, *, announce=True, require_enabled=True):
        return False, None, "network down"

    monkeypatch.setattr(_admin, "check_for_updates_once", fake_check)

    await _admin.bot_checkupdate(fake_bot, Sender(), "nick", [], DummyMsg(), False)

    assert "Update check failed: network down" in replies[-1][0]


@pytest.mark.asyncio
async def test_bot_status_uses_persistent_reply(fake_bot):
    replies = []
    fake_bot.reply = lambda msg, text, *a, **k: replies.append((text, k))

    await _admin.bot_status(fake_bot, Sender(), "nick", [], DummyMsg(), False)

    assert replies
    assert replies[-1][1]["no_store"] is False


@pytest.mark.asyncio
async def test_bot_status_handles_db_missing_and_errors(monkeypatch, fake_bot):
    fake_bot.db.path = None
    fake_bot.bot_plugins.discover = lambda: (
        _ for _ in ()).throw(ValueError("err"))
    # Patch psutil to throw
    monkeypatch.setattr(_admin, "psutil", types.SimpleNamespace(
        Process=lambda x=None: (_ for _ in ()).throw(ValueError("fail")),
        getloadavg=lambda: (_ for _ in ()).throw(ValueError("fail")),
        cpu_count=lambda: (_ for _ in ()).throw(ValueError("fail"))
    ))

    def raise_oserror_getsize(p):
        raise OSError()
    monkeypatch.setattr(os.path, "getsize", raise_oserror_getsize)
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    _admin.JOINED_ROOMS.clear()
    await _admin.bot_status(fake_bot, Sender(), "nick", [], DummyMsg(), False)
    replies = fake_bot._replies
    assert any(isinstance(r[0], list) or "Failed" in r[0] for r in replies)


@pytest.mark.asyncio
async def test_bot_status_handles_exception(monkeypatch, fake_bot):
    monkeypatch.setattr(_admin, "set_bot_start_time", lambda b: (
        _ for _ in ()).throw(Exception("fail")))
    await _admin.bot_status(fake_bot, Sender(), "nick", [], DummyMsg(), False)
    replies = fake_bot._replies
    assert any("❌" in r[0] for r in replies)


@pytest.mark.asyncio
async def test_bot_status_full_omits_healthy_rooms_and_includes_plugin_details(monkeypatch, fake_bot):
    _admin.BOT_START_TIME = datetime.now() - timedelta(minutes=5)
    fake_bot.last_version_check_result = "1.4.0"
    _admin.JOINED_ROOMS.clear()
    _admin.JOINED_ROOMS["room@example.org"] = {
        "nick": "EnvsBot",
        "role": "moderator",
        "affiliation": "member",
        "nicks": {"alice": {}, "bob": {}},
    }
    fake_bot.presence.joined_rooms = {"room@example.org": "EnvsBot"}
    await _admin.bot_status(fake_bot, Sender(), "nick", ["full"], DummyMsg(), False)
    reply_lines = fake_bot._replies[-1][0]
    reply = "\n".join(reply_lines)
    assert reply_lines.index("├─ Latest release: v1.4.0") == (
        reply_lines.index("├─ Version: v1.3.0") + 1
    )
    assert "Page count: 1" in reply
    assert "Page size: 1" in reply
    assert "Freelist pages: 1" in reply
    assert "Room issues:" not in reply
    assert "room@example.org | nick=EnvsBot | occupants=2" not in reply
    assert "Loaded plugins:" in reply
    assert "Caches:" in reply
    assert "Users: unavailable" in reply


@pytest.mark.asyncio
async def test_bot_status_rejects_unknown_args(fake_bot):
    await _admin.bot_status(fake_bot, Sender(), "nick", ["wat"], DummyMsg(), False)
    assert "Usage:" in fake_bot._replies[-1][0]


@pytest.mark.asyncio
async def test_bot_shutdown_handles_errors(monkeypatch, fake_bot):
    fake_bot.disconnect = lambda: None

    class FakeDB:
        async def close(self): raise Exception("fail")
        path = "/tmp/foo"
    fake_bot.db = FakeDB()
    async def immediate_sleep(*args, **kwargs): return None
    monkeypatch.setattr(_admin.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(_admin.asyncio, "wait_for", immediate_sleep)
    monkeypatch.setattr(_admin, "log",
                        types.SimpleNamespace(info=lambda *a, **k: None,
                                              error=lambda *a, **k: None,
                                              warning=lambda *a, **k: None,
                                              exception=lambda *a, **k: None))
    msg = DummyMsg()
    await _admin.bot_shutdown(fake_bot, Sender(), "nick", [], msg, False)


@pytest.mark.asyncio
async def test_bot_restart_saves_notification_to_persistent_paths(monkeypatch, fake_bot, tmp_path):
    paths = [
        tmp_path / "configured" / "restart.json",
        tmp_path / "data" / "envsbot_restart_notification.json",
    ]

    async def immediate_sleep(*args, **kwargs):
        return None

    async def immediate_wait_for(awaitable, timeout):
        return True

    monkeypatch.setattr(_admin, "_restart_notification_paths", lambda config_obj: [str(path) for path in paths])
    monkeypatch.setattr(_admin.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(_admin.asyncio, "wait_for", immediate_wait_for)
    shutdown_calls = []

    async def shutdown_runtime():
        shutdown_calls.append("shutdown")

    fake_bot.shutdown_runtime = shutdown_runtime

    await _admin.bot_restart(fake_bot, Sender(), "creme", [], DummyMsg(groupchat=True), True)

    assert getattr(fake_bot, "disco", False) is True
    assert shutdown_calls == ["shutdown"]
    for path in paths:
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["nick"] == "creme"
        assert data["room"] == "room@conf"
        assert data["is_room"] is True


@pytest.mark.asyncio
async def test_on_load_sets_start_time(monkeypatch):
    called = []
    monkeypatch.setattr(_admin, "set_bot_start_time",
                        lambda b: called.append("set"))

    class FakeLogger:
        def info(self, *a, **k): called.append("info")
    monkeypatch.setattr(_admin, "log", FakeLogger())
    await _admin.on_load("bot")
    assert "set" in called and "info" in called


def test_status_formatting_helpers_cover_edges(monkeypatch):
    assert _admin.human_time(24 * 3600 + 60) == "1d 1m"
    assert _admin.human_size(1024 ** 4) == "1.0 TiB"
    assert _admin._section("Title", ["one", "two"]) == [
        "• Title:", "├─ one", "└─ two", ""
    ]
    assert _admin._section("Core", ["ready"]) == [
        "⚙️ Core:", "└─ ready", ""
    ]

    monkeypatch.setattr(_admin.metadata, "version", lambda package: "9.9")
    assert _admin._package_version("pkg") == "9.9"

    def missing_version(package):
        raise _admin.metadata.PackageNotFoundError

    monkeypatch.setattr(_admin.metadata, "version", missing_version)
    assert _admin._package_version("missing") == "unknown"

    monkeypatch.setitem(_admin.config, "visible_key", "value")
    monkeypatch.setitem(_admin.config, "empty_key", "")
    monkeypatch.setitem(_admin.config, "none_key", None)
    assert _admin._safe_config_value("visible_key") == "value"
    assert _admin._safe_config_value("empty_key", "fallback") == "fallback"
    assert _admin._safe_config_value("none_key", "fallback") == "fallback"
    assert _admin._safe_config_value("missing_key", "fallback") == "fallback"


def test_presence_connection_and_room_snapshots(monkeypatch):
    assert _admin._format_presence(types.SimpleNamespace()) == "unknown"
    assert _admin._format_presence(
        types.SimpleNamespace(presence=types.SimpleNamespace(status={"show": "away"}))
    ) == "away"
    assert _admin._format_presence(
        types.SimpleNamespace(presence=types.SimpleNamespace(status={"show": "chat", "status": "ready"}))
    ) == "chat / ready"

    assert _admin._connection_line(types.SimpleNamespace()) == "Connection: unknown"

    class BadConnectionTime:
        def __rsub__(self, other):
            return NotImplemented

    assert _admin._connection_line(
        types.SimpleNamespace(connection_start_time=BadConnectionTime())
    ) == "Connection: unknown"

    aware_connection = datetime.now(timezone.utc) - timedelta(seconds=5)
    aware_line = _admin._connection_line(
        types.SimpleNamespace(connection_start_time=aware_connection)
    )
    assert aware_line.startswith("Connection: ")
    assert aware_line != "Connection: unknown"

    assert _admin._room_occupant_count({"nicks": {"a": {}, "b": {}}}) == 2
    assert _admin._room_occupant_count({"nicks": ["a"]}) == 0

    monkeypatch.setattr(_admin, "JOINED_ROOMS", {
        "room@example.org": {"nicks": {"alice": {}}},
        "empty@example.org": None,
    })
    snapshot = _admin._joined_rooms_snapshot()
    assert snapshot == (
        ("room@example.org", {"nicks": {"alice": {}}}),
        ("empty@example.org", {}),
    )

    class BrokenRooms:
        def items(self):
            raise RuntimeError("broken")

    monkeypatch.setattr(_admin, "JOINED_ROOMS", BrokenRooms())
    assert _admin._joined_rooms_snapshot() == ()


@pytest.mark.asyncio
async def test_status_room_and_direct_contact_helpers(monkeypatch):
    stored_rows = [("stored@conference.example.org", None, True)]

    class Rooms:
        async def list(self):
            return stored_rows

    bot = types.SimpleNamespace(
        db=types.SimpleNamespace(rooms=Rooms()),
        boundjid=types.SimpleNamespace(bare="bot@example.org"),
        client_roster={
            "bot@example.org": {"subscription": "both"},
            "stored@conference.example.org": {"subscription": "both"},
            "alice@example.org": {"subscription": "both"},
            "removed@example.org": {"subscription": "remove"},
        },
    )

    assert await _admin._stored_rooms_snapshot(bot) == tuple(stored_rows)
    assert _admin._direct_contact_count(bot, stored_rows) == 1
    assert _admin._xmpp_status_lines(bot, tuple(), stored_rows)[0] == (
        "Rooms: 0 joined MUCs · 1 direct contact (1:1/DM)"
    )
    bot.client_roster["bob@example.org"] = {"subscription": "both"}
    assert _admin._xmpp_status_lines(bot, (("joined@example.org", {}),), stored_rows)[0] == (
        "Rooms: 1 joined MUC · 2 direct contacts (1:1/DM)"
    )

    monkeypatch.setattr(
        _admin,
        "direct_roster_contacts",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broken")),
    )
    assert _admin._direct_contact_count(bot, stored_rows) is None
    assert "unknown direct contacts" in _admin._xmpp_status_lines(
        bot, tuple(), stored_rows
    )[0]


@pytest.mark.asyncio
async def test_stored_rooms_snapshot_handles_missing_and_failed_manager():
    assert await _admin._stored_rooms_snapshot(types.SimpleNamespace()) == ()

    class BrokenRooms:
        async def list(self):
            raise RuntimeError("broken")

    bot = types.SimpleNamespace(db=types.SimpleNamespace(rooms=BrokenRooms()))
    assert await _admin._stored_rooms_snapshot(bot) == ()


def test_command_plugin_and_task_status_helpers(monkeypatch):
    class Cmd:
        def __init__(self, name):
            self.name = name

    class FakeCommands(dict):
        pass

    fake_commands = FakeCommands({
        ("ping",): Cmd("ping"),
        ("p",): Cmd("ping"),
        ("bot", "status"): Cmd("bot status"),
    })
    fake_commands.by_plugin = {"foo": (("ping",),)}
    monkeypatch.setattr(_admin, "COMMANDS", fake_commands)
    assert _admin._command_counts() == (2, 1)

    assert _admin._task_summary_line(types.SimpleNamespace()) == "Tasks: unavailable"
    failed_supervisor = types.SimpleNamespace(summary=lambda: (2, 1, 3))
    assert _admin._task_summary_line(
        types.SimpleNamespace(tasks=failed_supervisor)
    ) == "Tasks: 2 running, 1 failed, 3 finished"
    ok_supervisor = types.SimpleNamespace(summary=lambda: (2, 0, 3))
    assert _admin._task_summary_line(
        types.SimpleNamespace(tasks=ok_supervisor)
    ) == "Tasks: 2 running, 3 finished"
    modern_supervisor = types.SimpleNamespace(
        summary_by_kind=lambda: {
            "services_running": 2,
            "one_shots_running": 1,
            "one_shots_completed": 3,
            "services_finished": 0,
            "failed": 0,
            "cancelled": 0,
        }
    )
    assert _admin._task_summary_line(
        types.SimpleNamespace(tasks=modern_supervisor)
    ) == "Tasks: 2 services running, 1 one-shots running, 3 one-shots completed, 0 failed"

    finished_supervisor = types.SimpleNamespace(
        summary_by_kind=lambda: {
            "services_running": 2,
            "one_shots_running": 0,
            "one_shots_completed": 1,
            "services_finished": 1,
            "failed": 0,
            "cancelled": 0,
        }
    )
    assert _admin._task_summary_line(
        types.SimpleNamespace(tasks=finished_supervisor)
    ).endswith("1 services finished unexpectedly")

    assert _admin._plugin_status_lines(types.SimpleNamespace(bot_plugins=None))[:2] == [
        "Loaded: 0/0", "Commands: 2 (+1 aliases)"
    ]

    class BrokenDiscover:
        plugins = {"foo": object()}

        def discover(self):
            raise RuntimeError("nope")

    lines = _admin._plugin_status_lines(types.SimpleNamespace(
        bot_plugins=BrokenDiscover(), tasks=ok_supervisor
    ))
    assert "Loaded: 1/unknown" in lines
    assert "Tasks: 2 running, 3 finished" in lines


def test_detail_line_helpers(monkeypatch):
    from utils.health import HealthCheck, HealthSnapshot

    healthy = HealthSnapshot(
        checked_at="now",
        checks={"rooms": HealthCheck("rooms", "ok", "ok", {"missing": ()})},
    )
    bot = types.SimpleNamespace(
        prefix=",",
        presence=types.SimpleNamespace(joined_rooms={"z@example.org": "bot"}),
    )
    room_snapshot = (("z@example.org", {"nick": "bot"}),)
    assert _admin._room_problem_lines(bot, room_snapshot, healthy) == []

    warning = HealthSnapshot(
        checked_at="now",
        checks={
            "rooms": HealthCheck(
                "rooms",
                "warning",
                "missing",
                {"missing": ("missing@example.org",)},
            )
        },
    )
    bot.presence.joined_rooms = {
        "presence-only@example.org": "bot",
        "nick-mismatch@example.org": "other",
    }
    problem_snapshot = (
        ("core-only@example.org", {"nick": "bot"}),
        ("nick-mismatch@example.org", {"nick": "bot"}),
    )
    room_lines = _admin._room_problem_lines(bot, problem_snapshot, warning)
    assert room_lines == [
        "⚠️ core-only@example.org | presence routing state is missing",
        "⚠️ missing@example.org | autojoin room is not joined",
        "⚠️ nick-mismatch@example.org | presence nick differs from runtime nick (other != bot)",
        "⚠️ presence-only@example.org | core room state is missing",
    ]

    assert _admin._plugin_detail_lines(types.SimpleNamespace(bot_plugins=None)) == ["—"]

    plugin_module = types.SimpleNamespace(PLUGIN_META={"version": "2.0", "category": "fun"})
    manager = types.SimpleNamespace(plugins={"foo": plugin_module, "bar": object()}, meta={"bar": {"version": "1.0"}})
    lines = _admin._plugin_detail_lines(types.SimpleNamespace(bot_plugins=manager))
    assert "bar 1.0 | category=unknown" in lines[0]
    assert "foo 2.0 | category=fun" in lines[1]

    assert _admin._task_detail_lines(types.SimpleNamespace(tasks=None)) == ["unavailable"]
    empty_supervisor = types.SimpleNamespace(snapshot=lambda include_done=True: [])
    assert _admin._task_detail_lines(types.SimpleNamespace(tasks=empty_supervisor)) == ["—"]
    task = types.SimpleNamespace(
        plugin="rss", name="feed", status="failed",
        created_at="2026-06-24T10:00:00", last_error="boom",
        heartbeat_at=None, restart_count=2, circuit_state="open",
    )
    supervisor = types.SimpleNamespace(snapshot=lambda include_done=True: [task])
    assert _admin._task_detail_lines(types.SimpleNamespace(tasks=supervisor)) == [
        "rss/feed | failed | heartbeat=not reported | restarts=2 | "
        "circuit=open | created=2026-06-24T10:00:00 | error=boom"
    ]


def test_room_problem_lines_are_limited_and_point_to_rooms_list_all():
    from utils.health import HealthCheck, HealthSnapshot

    missing = tuple(f"room{i:02d}@example.org" for i in range(12))
    health = HealthSnapshot(
        checked_at="now",
        checks={
            "rooms": HealthCheck(
                "rooms",
                "warning",
                "missing",
                {"missing": missing},
            )
        },
    )
    bot = types.SimpleNamespace(
        prefix=",",
        presence=types.SimpleNamespace(joined_rooms={}),
    )
    lines = _admin._room_problem_lines(bot, (), health)

    assert len(lines) == 11
    assert sum(line.startswith("⚠️ room") for line in lines) == 10
    assert lines[-1] == "… 2 more room problems; see ,rooms list all"


@pytest.mark.asyncio
async def test_health_and_cache_status_helpers():
    bot = types.SimpleNamespace(
        alerts=types.SimpleNamespace(runtime_state=lambda: {"active": 2}),
        outbox=types.SimpleNamespace(runtime_state=AsyncMock(return_value={
            "pending": 3,
            "dead": 1,
            "last_error": None,
        })),
        message_cache=types.SimpleNamespace(stats=lambda: {
            "messages": 42,
            "pending_writes": 1,
            "retry_backlog": 2,
            "dropped_persistence_entries": 3,
            "persistent": True,
            "degraded": True,
        }),
        db=types.SimpleNamespace(users=types.SimpleNamespace(cache_state=lambda: {
            "users": 12,
            "runtime": 8,
            "dirty_users": 1,
            "dirty_runtime": 2,
            "user_limit": 100,
            "runtime_limit": 200,
            "evicted_users": 4,
            "evicted_runtime": 5,
        })),
    )

    assert await _admin._health_status_lines(bot) == [
        "Overall: ⚠️ 2 active alerts",
        "Outbox: 3 pending · 1 dead",
        "Message cache: 42 messages · persistent · degraded",
    ]
    assert _admin._cache_detail_lines(bot) == [
        "Users: 12/100 · dirty=1 · evicted=4",
        "Runtime: 8/200 · dirty=2 · evicted=5",
        "Message cache: 42 messages · pending=1 · retry=2 · dropped=3 · persistent · degraded",
    ]


@pytest.mark.asyncio
async def test_database_status_line_edges(tmp_path):
    assert await _admin._database_status_lines(types.SimpleNamespace()) == [
        "Status: disconnected"
    ]

    configured = types.SimpleNamespace(db=types.SimpleNamespace(conn=None, path=None))
    assert await _admin._database_status_lines(configured) == [
        "Status: configured", "Path: unknown", "Size: unknown", "Integrity: unknown"
    ]
    assert await _admin._database_status_lines(configured, full=True) == [
        "Status: configured",
        "Path: unknown",
        "Size: unknown",
        "Integrity: unknown",
        "Page count: unknown",
        "Page size: unknown",
        "Freelist pages: unknown",
    ]

    db_file = tmp_path / "bot.db"
    db_file.write_bytes(b"abc")

    async def no_row(query):
        return None

    lines = await _admin._database_status_lines(types.SimpleNamespace(
        db=types.SimpleNamespace(conn=object(), path=db_file, fetch_one=no_row)
    ))
    assert f"Path: {db_file}" in lines
    assert "Size: 3 B" in lines
    assert "Integrity: unknown" in lines

    async def pragma_rows(query):
        return {
            "PRAGMA integrity_check": ("ok",),
            "PRAGMA page_count": (11,),
            "PRAGMA page_size": (4096,),
            "PRAGMA freelist_count": (2,),
        }[query]

    full_lines = await _admin._database_status_lines(types.SimpleNamespace(
        db=types.SimpleNamespace(conn=object(), path=db_file, fetch_one=pragma_rows)
    ), full=True)
    assert f"Path: {db_file}" in full_lines
    assert "Size: 3 B" in full_lines
    assert "Integrity: ok" in full_lines
    assert "Page count: 11" in full_lines
    assert "Page size: 4096" in full_lines
    assert "Freelist pages: 2" in full_lines

    async def broken_fetch(query):
        raise RuntimeError("sqlite down")

    lines = await _admin._database_status_lines(types.SimpleNamespace(
        db=types.SimpleNamespace(conn=object(), path=tmp_path / "missing.db", fetch_one=broken_fetch)
    ), full=True)
    assert "Size: file not found" in lines
    assert "Integrity: unknown" in lines
    assert "Page count: unknown" in lines
    assert "Page size: unknown" in lines
    assert "Freelist pages: unknown" in lines


@pytest.mark.asyncio
async def test_room_feature_override_line_success_and_error(monkeypatch):
    async def fake_list_room_features(bot, room_jid):
        return [types.SimpleNamespace(modified=True), types.SimpleNamespace(modified=False)]

    import utils.room_features as room_features
    monkeypatch.setattr(room_features, "list_room_features", fake_list_room_features)
    assert await _admin._room_feature_override_line(
        object(), (("one@example.org", {}), ("two@example.org", {}))
    ) == "Room feature overrides: 2"

    async def broken_list_room_features(bot, room_jid):
        raise RuntimeError("db down")

    monkeypatch.setattr(room_features, "list_room_features", broken_list_room_features)
    assert await _admin._room_feature_override_line(
        object(), (("one@example.org", {}),)
    ) == "Room feature overrides: unknown"


def test_status_argument_helpers(fake_bot):
    assert _admin._invalid_status_args([]) is False
    assert _admin._invalid_status_args(["full"]) is False
    assert _admin._invalid_status_args(["all"]) is False
    assert _admin._invalid_status_args(["details"]) is False
    assert _admin._invalid_status_args(["nope"]) is True
    assert _admin._status_is_full([]) is False
    assert _admin._status_is_full(["FULL"]) is True
    assert _admin._status_is_full(["all"]) is True
    assert _admin._status_is_full(["details"]) is True

    replies = []
    fake_bot.reply_usage = lambda msg, text: replies.append(("usage", text))
    _admin._reply_status_usage(fake_bot, DummyMsg())
    assert replies == [("usage", ",bot status [full]")]

    del fake_bot.reply_usage
    _admin._reply_status_usage(fake_bot, DummyMsg())
    assert fake_bot._replies[-1][0] == "Usage: ,bot status [full]"


@pytest.mark.asyncio
async def test_on_ready_version_worker_branches(monkeypatch, fake_bot):
    monkeypatch.setitem(_admin.config, "version_check_enabled", False)
    await _admin.on_ready(fake_bot)
    assert not hasattr(fake_bot, "version_check_task")

    class ExistingTask:
        def done(self):
            return False

    monkeypatch.setitem(_admin.config, "version_check_enabled", True)
    fake_bot.version_check_task = ExistingTask()
    await _admin.on_ready(fake_bot)
    assert isinstance(fake_bot.version_check_task, ExistingTask)

    created = []

    monkeypatch.setattr(_admin, "version_check_worker", lambda bot: "worker")
    monkeypatch.setattr(
        _admin,
        "create_resilient_plugin_task",
        lambda *a, **k: created.append((a, k)) or "task",
    )
    fake_bot.version_check_task = types.SimpleNamespace(done=lambda: True)
    await _admin.on_ready(fake_bot)
    assert fake_bot.version_check_task == "task"
    assert created[0][0][1] == "_admin"
    assert created[0][0][2]() == "worker"
    assert created[0][1]["name"] == "version-check"


@pytest.mark.asyncio
async def test_restart_tasks_clears_worker_reference_before_resync(monkeypatch, fake_bot):
    old_task = object()
    fake_bot.version_check_task = old_task
    observed = []

    async def fake_on_ready(bot):
        observed.append(getattr(bot, "version_check_task", "missing"))

    monkeypatch.setattr(_admin, "on_ready", fake_on_ready)

    await _admin.restart_tasks(fake_bot)

    assert observed == [None]
    assert fake_bot.version_check_task is None


@pytest.mark.asyncio
async def test_bot_shutdown_external_success_still_drains_runtime(monkeypatch, fake_bot):
    monkeypatch.setitem(_admin.config, "stop_cmd", ["service", "envsbot", "stop"])
    monkeypatch.setitem(_admin.config, "stop_cmd_timeout_seconds", 3)
    monkeypatch.setattr(_admin, "_run_stop_command", AsyncMock(return_value=(0, "")))
    monkeypatch.setattr(_admin.asyncio, "sleep", AsyncMock())
    graceful = AsyncMock()
    monkeypatch.setattr(_admin, "_graceful_command_shutdown", graceful)

    await _admin.bot_shutdown(
        fake_bot, Sender(), "nick", [], DummyMsg(), False
    )

    _admin._run_stop_command.assert_awaited_once_with(
        ["service", "envsbot", "stop"], 3.0
    )
    graceful.assert_awaited_once_with(fake_bot, exit_code=0)


@pytest.mark.asyncio
async def test_run_stop_command_reports_output_and_timeout(monkeypatch):
    class Process:
        returncode = 3

        async def communicate(self):
            return b"", b"permission denied"

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(_admin.asyncio, "create_subprocess_exec", AsyncMock(return_value=Process()))
    code, detail = await _admin._run_stop_command(["systemctl", "stop", "envsbot"], 2)
    assert code == 3
    assert detail == "permission denied"


@pytest.mark.asyncio
async def test_graceful_command_shutdown_sets_clean_exit_code(fake_bot):
    fake_bot.disconnected = asyncio.sleep(0)
    fake_bot.disconnect = Mock()
    fake_bot.shutdown_runtime = AsyncMock()
    await _admin._graceful_command_shutdown(fake_bot, exit_code=0)
    assert fake_bot._requested_exit_code == 0
    fake_bot.disconnect.assert_called_once()
    fake_bot.shutdown_runtime.assert_awaited_once()
