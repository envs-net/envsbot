from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import plugins.birthday_notify as birthday
import plugins.ducks as ducks
import plugins.idlerpg.state as idlerpg_state
import plugins.idlerpg.tasks as idlerpg_tasks
import plugins.karma as karma
import plugins.pin as pin
import plugins.reminder.store as reminder_store
import plugins.rss.store as rss_store
import plugins.tell as tell
import plugins.urlcheck as urlcheck
import plugins.weather as weather


class FakeTask:
    def __init__(self, done: bool = False):
        self._done = done

    def done(self):
        return self._done


class FakePluginStore:
    def __init__(self, globals=None, values=None):
        self.globals = dict(globals or {})
        self.values = dict(values or {})
        self.set_globals = []

    async def get_global(self, key, default=None):
        return self.globals.get(key, default)

    async def set_global(self, key, value):
        self.globals[key] = value
        self.set_globals.append((key, value))

    async def get(self, jid, key, default=None):
        return self.values.get((jid, key), default)

    async def set(self, jid, key, value):
        self.values[(jid, key)] = value


class FakeUsers:
    def __init__(self, stores=None, users=None):
        self.stores = dict(stores or {})
        self.users = list(users or [])

    def plugin(self, name):
        return self.stores[name]

    async def list(self):
        return list(self.users)


class FakeDB:
    def __init__(self, stores=None, users=None):
        self.users = FakeUsers(stores=stores, users=users)


@pytest.mark.asyncio
async def test_room_toggle_diagnostic_hooks_count_enabled_rooms_and_scope(monkeypatch):
    stores = {
        "weather": FakePluginStore({weather.WEATHER_KEY: {"Room@Conf/Nick": True, "other@conf": True}}),
        "urlcheck": FakePluginStore({urlcheck.URLCHECK_KEY: {"Room@Conf/Nick": True, "other@conf": True}}),
    }
    bot = SimpleNamespace(db=FakeDB(stores=stores))

    monkeypatch.setattr(urlcheck, "_url_timestamps", {
        "room@conf": {"https://a.example": 1, "https://b.example": 2},
        "other@conf": {"https://c.example": 3},
    })

    assert await weather.get_runtime_state(bot) == {"enabled_rooms": 2}
    assert await weather.get_runtime_state(bot, room_jid="room@conf") == {"enabled_rooms": 1}
    assert await weather.get_runtime_state(bot, room_jid="missing@conf") == {"enabled_rooms": 0}
    assert await weather.doctor(bot, room_jid="room@conf") == [
        f"✅ Weather for room@conf: enabled_rooms=1, timeout={weather.WEATHER_HTTP_TIMEOUT:g}s"
    ]

    assert await urlcheck.get_runtime_state(bot) == {"enabled_rooms": 2, "cached_urls": 3}
    assert await urlcheck.get_runtime_state(bot, room_jid="room@conf") == {
        "enabled_rooms": 1,
        "cached_urls": 2,
    }
    assert await urlcheck.get_runtime_state(bot, room_jid="missing@conf") == {
        "enabled_rooms": 0,
        "cached_urls": 0,
    }
    assert await urlcheck.doctor(bot, room_jid="room@conf") == [
        f"✅ URLCheck for room@conf: enabled_rooms=1, cached_urls=2, max_redirects={urlcheck.URLCHECK_MAX_REDIRECTS}"
    ]


@pytest.mark.asyncio
async def test_tell_runtime_state_and_doctor_counts_pending_messages_by_room():
    tell_store = FakePluginStore(
        globals={tell.TELL_KEY: {"room@conf/nick": True, "other@conf": True}},
        values={
            ("alice@example.org", "tell_messages"): [
                {"room_jid": "room@conf/Alice", "message": "one"},
                {"room_jid": "other@conf", "message": "two"},
                "ignored-non-dict-for-room-filter",
            ],
            ("bob@example.org", "tell_messages"): [
                {"room_jid": "room@conf", "message": "three"},
            ],
            ("bad@example.org", "tell_messages"): "not-a-list",
        },
    )
    users = [
        {"jid": "alice@example.org"},
        {"jid": "bob@example.org"},
        {"jid": "bad@example.org"},
        {"jid": "__GLOBAL__"},
        {"not_jid": "ignored"},
        "not-a-dict",
    ]
    bot = SimpleNamespace(db=FakeDB(stores={"tell": tell_store}, users=users))

    assert await tell.get_runtime_state(bot) == {"enabled_rooms": 2, "pending_messages": 4}
    assert await tell.get_runtime_state(bot, room_jid="room@conf") == {
        "enabled_rooms": 1,
        "pending_messages": 2,
    }
    assert await tell.get_runtime_state(bot, room_jid="missing@conf") == {
        "enabled_rooms": 0,
        "pending_messages": 0,
    }
    assert await tell.doctor(bot, room_jid="room@conf") == [
        "✅ Tell for room@conf: enabled_rooms=1, pending_messages=2"
    ]


@pytest.mark.asyncio
async def test_karma_runtime_state_and_doctor_counts_room_scores(monkeypatch):
    store = FakePluginStore(
        globals={
            karma.KARMA_ENABLED_KEY: {"room@conf/nick": True, "other@conf": True},
            karma.KARMA_SCORES_KEY: {
                "room@conf": {"alice": 2, "bob": -1},
                "other@conf": {"carol": 5},
                "broken@conf": "not-a-dict",
            },
        }
    )
    bot = SimpleNamespace(db=FakeDB(stores={"karma": store}))
    monkeypatch.setattr(karma, "LAST_KARMA_ACTIONS", {"room@conf:alice@example.org": {"bob": 1.0}})

    assert await karma.get_runtime_state(bot) == {
        "enabled_rooms": 2,
        "rooms_with_scores": 3,
        "tracked_targets": 3,
        "throttled_users": 1,
    }
    assert await karma.get_runtime_state(bot, room_jid="room@conf") == {
        "enabled_rooms": 1,
        "tracked_targets": 2,
        "throttled_users": 1,
    }
    assert await karma.get_runtime_state(bot, room_jid="missing@conf") == {
        "enabled_rooms": 0,
        "tracked_targets": 0,
        "throttled_users": 1,
    }
    assert await karma.doctor(bot, room_jid="room@conf") == [
        "✅ Karma for room@conf: enabled_rooms=1, tracked_targets=2"
    ]


@pytest.mark.asyncio
async def test_birthday_runtime_state_and_doctor_handles_task_and_room_scope(monkeypatch):
    store = FakePluginStore({"birthday_notify": {"room@conf/nick": True, "other@conf": True}})
    bot = SimpleNamespace(db=FakeDB(stores={"birthday_notify": store}))
    monkeypatch.setattr(birthday, "ANNOUNCED_TODAY", {
        ("room@conf", "alice@example.org"): "2026-07-09",
        ("room@conf/nick", "bob@example.org"): "2026-07-09",
        ("other@conf", "carol@example.org"): "2026-07-09",
    })
    monkeypatch.setattr(birthday, "_BIRTHDAY_CHECK_TASK", FakeTask(done=False))

    assert await birthday.get_runtime_state(bot) == {
        "enabled_rooms": 2,
        "announced_today": 3,
        "task_running": 1,
    }
    assert await birthday.get_runtime_state(bot, room_jid="room@conf") == {
        "enabled_rooms": 1,
        "announced_today": 2,
        "task_running": 1,
    }
    assert await birthday.doctor(bot, room_jid="room@conf") == [
        "✅ Birthday for room@conf: enabled_rooms=1, announced_today=2, task_running=1"
    ]

    monkeypatch.setattr(birthday, "_BIRTHDAY_CHECK_TASK", None)
    assert await birthday.doctor(bot) == [
        "⚠️ Birthday: enabled_rooms=2, announced_today=3, task_running=0"
    ]


@pytest.mark.asyncio
async def test_idlerpg_runtime_state_and_doctor_counts_rooms_players_tasks(monkeypatch):
    data = {
        "rooms": {
            "room@conf": {
                "players": {
                    "alice@example.org": {"name": "alice", "logged_out": False},
                    "bob@example.org": {"name": "bob", "logged_out": True},
                },
                "quest": {"active": True},
            },
            "broken@conf": "not-a-dict",
        }
    }
    store = FakePluginStore({idlerpg_tasks.IDLERPG_DATA_KEY: data})
    bot = SimpleNamespace(db=FakeDB(stores={"idlerpg": store}))
    monkeypatch.setitem(idlerpg_state.JOINED_ROOMS, "room@conf", {"nicks": {"alice": {"jid": "alice@example.org/res"}}})
    monkeypatch.setattr(idlerpg_tasks, "ROOM_TASKS", {
        "room@conf": FakeTask(done=False),
        "old@conf": FakeTask(done=True),
    })

    assert await idlerpg_tasks.get_runtime_state(bot) == {
        "rooms": 2,
        "players": 2,
        "online_players": 1,
        "active_quests": 1,
        "tasks": 1,
    }
    assert await idlerpg_tasks.get_runtime_state(bot, room_jid="room@conf") == {
        "rooms": 1,
        "players": 2,
        "online_players": 1,
        "active_quests": 1,
        "tasks": 1,
    }
    assert await idlerpg_tasks.doctor(bot, room_jid="room@conf") == [
        "✅ IdleRPG for room@conf: rooms=1, players=2, online=1, active_quests=1, tasks=1"
    ]

    monkeypatch.setattr(idlerpg_tasks, "ROOM_TASKS", {})
    assert await idlerpg_tasks.doctor(bot, room_jid="room@conf") == [
        "⚠️ IdleRPG for room@conf: rooms=1, players=2, online=1, active_quests=1, tasks=0"
    ]


@pytest.mark.asyncio
async def test_reminder_runtime_state_and_doctor_counts_pending_and_active(monkeypatch):
    pending = [
        {"id": 1, "room_jid": "room@conf/nick"},
        {"id": 2, "room_jid": "room@conf"},
        {"id": 3, "room_jid": "other@conf"},
    ]
    monkeypatch.setattr(reminder_store, "_init_reminder_db", AsyncMock())
    monkeypatch.setattr(reminder_store, "_get_all_pending_reminders", AsyncMock(return_value=pending))
    monkeypatch.setattr(reminder_store, "ACTIVE_REMINDERS", {
        1: FakeTask(done=False),
        2: FakeTask(done=True),
        3: FakeTask(done=False),
    })
    monkeypatch.setattr(reminder_store, "REMINDER_ENABLED", True)

    assert await reminder_store.get_runtime_state(SimpleNamespace()) == {
        "pending_reminders": 3,
        "active_tasks": 2,
        "enabled": 1,
    }
    assert await reminder_store.get_runtime_state(SimpleNamespace(), room_jid="room@conf") == {
        "pending_reminders": 2,
        "active_tasks": 1,
    }
    assert await reminder_store.doctor(SimpleNamespace(), room_jid="room@conf") == [
        "✅ Reminder for room@conf: enabled, pending=2, active_tasks=1"
    ]

    monkeypatch.setattr(reminder_store, "REMINDER_ENABLED", False)
    assert await reminder_store.doctor(SimpleNamespace()) == [
        "ℹ️ Reminder: disabled, pending=3, active_tasks=2"
    ]


@pytest.mark.asyncio
async def test_ducks_runtime_state_and_doctor_reports_runtime_maps(monkeypatch):
    monkeypatch.setattr(ducks, "ACTIVE_DUCKS", {"room@conf": {"duck": True}})
    monkeypatch.setattr(ducks, "PENDING_DUCKS", {"pending@conf"})
    monkeypatch.setattr(ducks, "SPAWN_TASKS", {"room@conf/nick": FakeTask(done=False), "done@conf": FakeTask(done=True)})
    monkeypatch.setattr(ducks, "EXPIRE_TASKS", {"room@conf": FakeTask(done=False)})
    monkeypatch.setattr(ducks, "MESSAGE_COUNTS", {"room@conf/resource": 10, "other@conf": 3})

    assert await ducks.get_runtime_state(SimpleNamespace()) == {
        "active_ducks": 1,
        "pending_rooms": 1,
        "spawn_tasks": 1,
        "expire_tasks": 1,
        "tracked_rooms": 2,
    }
    assert await ducks.get_runtime_state(SimpleNamespace(), room_jid="room@conf") == {
        "active_ducks": 1,
        "pending_spawn": 1,
        "expire_tasks": 1,
        "message_counts": 1,
    }
    assert await ducks.doctor(SimpleNamespace(), room_jid="room@conf") == [
        "✅ Ducks for room@conf: active_ducks=1, spawn_tasks=1, expire_tasks=1"
    ]


@pytest.mark.asyncio
async def test_rss_runtime_state_and_doctor_reports_backoff(monkeypatch):
    feeds = {
        "https://one.example/feed": {"rooms": ["room@conf"], "next_retry": 200},
        "https://two.example/feed": {"rooms": ["room@conf", "other@conf"], "next_retry": 0},
        "https://three.example/feed": {"rooms": ["other@conf"], "next_retry": 300},
        "https://bad.example/feed": "not-a-dict",
    }
    store = FakePluginStore({rss_store.RSS_KEY: feeds})
    bot = SimpleNamespace(db=FakeDB(stores={"rss": store}))
    monkeypatch.setattr(rss_store, "_now", lambda: 100)
    monkeypatch.setattr(rss_store, "CHECK_TASKS", {
        "https://one.example/feed": FakeTask(done=False),
        "https://two.example/feed": FakeTask(done=True),
        "https://three.example/feed": FakeTask(done=False),
    })

    assert await rss_store.get_runtime_state(bot) == {
        "feeds": 4,
        "active_tasks": 2,
        "retry_backoff": 2,
    }
    assert await rss_store.get_runtime_state(bot, room_jid="room@conf") == {
        "feeds": 2,
        "active_tasks": 1,
        "retry_backoff": 1,
    }
    assert await rss_store.doctor(bot, room_jid="room@conf") == [
        "✅ RSS for room@conf: feeds=2, active_tasks=1, retry_backoff=1",
        "🟡️ RSS: one or more feeds are currently in retry/backoff",
    ]


@pytest.mark.asyncio
async def test_pin_runtime_state_and_doctor_counts_normalized_rooms(monkeypatch):
    pin_data = {
        "room@conf/nick": {pin.PINS_FIELD: [{"id": 1}, {"id": 2}]},
        "other@conf": {pin.PINS_FIELD: [{"id": 3}]},
        "broken@conf": {pin.PINS_FIELD: "not-a-list"},
    }
    store = FakePluginStore({pin.PIN_DATA_KEY: pin_data})
    bot = SimpleNamespace(db=FakeDB(stores={"pin": store}))

    assert await pin.get_runtime_state(bot) == {"rooms": 3, "pins": 3}
    assert await pin.get_runtime_state(bot, room_jid="room@conf") == {"rooms": 1, "pins": 2}
    assert await pin.get_runtime_state(bot, room_jid="missing@conf") == {"rooms": 0, "pins": 0}
    assert await pin.doctor(bot, room_jid="room@conf") == ["✅ Pin for room@conf: rooms=1, pins=2"]
    assert await pin.doctor(bot, room_jid="missing@conf") == ["ℹ️ Pin for missing@conf: no stored pins"]


@pytest.mark.asyncio
async def test_simple_optional_plugin_diagnostic_hooks(monkeypatch, tmp_path):
    import plugins.dice as dice
    import plugins.info as info
    import plugins.sed as sed
    import plugins.tools as tools
    import plugins.vcard as vcard
    import plugins.xmpp as xmpp

    stores = {
        "dice": FakePluginStore({dice.DICE_KEY: {"Room@Conf/Nick": True, "other@conf": True}}),
        "information": FakePluginStore({info.INFO_KEY: {"Room@Conf": True}}),
        "sed": FakePluginStore({sed.SED_KEY: {"Room@Conf": True, "other@conf": True}}),
        "tools": FakePluginStore({tools.TOOLS_KEY: {"Room@Conf": True}}),
        "vcard": FakePluginStore({vcard.VCARD_KEY: {"Room@Conf": True}}),
        "xmpp": FakePluginStore({xmpp.XMPP_KEY: {"Room@Conf": True, "disabled@conf": False}}),
    }
    bot = SimpleNamespace(
        db=FakeDB(stores=stores),
        plugin={"xep_0054": object()},
    )

    main_csv = tmp_path / "chat_slang.csv"
    additions_csv = tmp_path / "slang_additions.csv"
    removals_csv = tmp_path / "slang_removals.csv"
    main_csv.write_text("brb,be right back\nbrb,be right back soon\nlol,laughing out loud\n", encoding="utf-8")
    additions_csv.write_text("idk,I do not know\n", encoding="utf-8")
    removals_csv.write_text("lol,laughing out loud\n", encoding="utf-8")
    monkeypatch.setattr(info, "SLANG_CSV", str(main_csv))
    monkeypatch.setattr(info, "SLANG_ADDITIONS_CSV", str(additions_csv))
    monkeypatch.setattr(info, "SLANG_REMOVALS_CSV", str(removals_csv))

    sed._core._SHARED_MESSAGE_CACHES[sed.CACHE_NAMESPACE].clear()
    sed._core.cache_message(sed.CACHE_NAMESPACE, "room@conf", "alice", "hello", "stanza-1")

    joined = {"room@conf": {"nicks": {"alice": {"jid": "alice@example.org"}}}}
    monkeypatch.setattr(tools, "JOINED_ROOMS", joined)
    monkeypatch.setattr(vcard, "JOINED_ROOMS", joined)
    monkeypatch.setattr(xmpp, "JOINED_ROOMS", joined)

    dice_state = await dice.get_runtime_state(bot, room_jid="room@conf/nick")
    assert dice_state["enabled_rooms"] == 1
    assert dice_state["max_dice"] == 10
    assert dice_state["max_sides"] == 100
    assert await dice.doctor(bot, room_jid="room@conf") == [
        "✅ Dice for room@conf: enabled_rooms=1, limits=10d100"
    ]

    info_state = await info.get_runtime_state(bot, room_jid="room@conf")
    assert info_state["enabled_rooms"] == 1
    assert info_state["acronyms"] == 2
    assert info_state["definitions"] == 3
    assert info_state["pending_additions"] == 1
    assert info_state["pending_removals"] == 1
    assert info_state["timeout"] == info.INFO_HTTP_TIMEOUT
    assert await info.doctor(bot, room_jid="room@conf") == [
        f"✅ Info for room@conf: enabled_rooms=1, acronyms=2, definitions=3, "
        f"pending_additions=1, pending_removals=1, timeout={info.INFO_HTTP_TIMEOUT:g}s"
    ]

    sed_state = await sed.get_runtime_state(bot, room_jid="room@conf")
    assert sed_state["enabled_rooms"] == 1
    assert sed_state["cached_rooms"] == 1
    assert sed_state["cached_messages"] == 1
    assert sed_state["cache_size"] == sed.SED_CACHE_SIZE
    assert sed_state["regex_timeout"] == sed.REGEX_TIMEOUT
    assert await sed.doctor(bot, room_jid="room@conf") == [
        f"✅ Sed for room@conf: enabled_rooms=1, cached_rooms=1, "
        f"cached_messages=1, cache_size={sed.SED_CACHE_SIZE}, regex_timeout={sed.REGEX_TIMEOUT:g}s"
    ]

    tools_state = await tools.get_runtime_state(bot, room_jid="room@conf")
    assert tools_state["enabled_rooms"] == 1
    assert tools_state["joined_rooms"] == 1
    assert tools_state["tracked_nicks"] == 1
    assert tools_state["timezones_known"] > 0
    assert (await tools.doctor(bot, room_jid="room@conf"))[0].startswith(
        "✅ Tools for room@conf: enabled_rooms=1, joined_rooms=1, tracked_nicks=1"
    )

    vcard_state = await vcard.get_runtime_state(bot, room_jid="room@conf")
    assert vcard_state["enabled_rooms"] == 1
    assert vcard_state["joined_rooms"] == 1
    assert vcard_state["tracked_nicks"] == 1
    assert vcard_state["xep_0054_available"] == 1
    assert vcard_state["fetch_timeout"] == 10.0
    assert await vcard.doctor(bot, room_jid="room@conf") == [
        "✅ vCard for room@conf: enabled_rooms=1, joined_rooms=1, "
        "tracked_nicks=1, xep_0054_available=1, fetch_timeout=10s"
    ]

    xmpp_state = await xmpp.get_runtime_state(bot, room_jid="room@conf")
    assert xmpp_state["enabled_rooms"] == 1
    assert xmpp_state["joined_rooms"] == 1
    assert xmpp_state["query_timeout"] == xmpp.XMPP_QUERY_TIMEOUT_SECONDS
    assert xmpp_state["http_timeout"] == xmpp.XMPP_HTTP_TIMEOUT_SECONDS
    assert await xmpp.doctor(bot, room_jid="room@conf") == [
        f"✅ XMPP for room@conf: enabled_rooms=1, joined_rooms=1, "
        f"query_timeout={xmpp.XMPP_QUERY_TIMEOUT_SECONDS:g}s, "
        f"http_timeout={xmpp.XMPP_HTTP_TIMEOUT_SECONDS:g}s"
    ]


@pytest.mark.asyncio
async def test_poll_and_xkcd_doctor_hooks(monkeypatch):
    import plugins.poll as poll
    import plugins.xkcd as xkcd

    monkeypatch.setattr(poll, "_get_data", AsyncMock(return_value={
        "rooms": {
            "room@conf": {"polls": {"1": {"status": "open"}, "2": {"status": "closed"}}},
        }
    }))
    monkeypatch.setattr(poll, "AUTO_CLOSE_TASKS", {("room@conf", "1"): FakeTask(done=False)})
    assert await poll.doctor(SimpleNamespace(), "room@conf") == [
        "✅ Poll for room@conf: rooms=1, polls=2, active=1, auto_close_tasks=1"
    ]

    store = FakePluginStore({
        xkcd.XKCD_KEY: {"rooms": ["Room@Conf", "other@conf"]},
        xkcd.XKCD_INDEX_KEY: {"1": {}, "2": {}},
    })
    bot = SimpleNamespace(db=FakeDB(stores={"xkcd": store}))
    monkeypatch.setattr(xkcd, "CHECK_TASK", FakeTask(done=False))
    monkeypatch.setattr(xkcd, "INDEX_TASK", FakeTask(done=True))

    assert await xkcd.doctor(bot, "room@conf") == [
        "✅ XKCD for room@conf: legacy_rooms=1, indexed_comics=2"
    ]
    assert await xkcd.doctor(bot) == [
        "✅ XKCD: legacy_rooms=2, indexed_comics=2, "
        "check_task_running=1, index_task_running=0"
    ]
