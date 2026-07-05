import asyncio
import itertools
import types

import pytest

import plugins.idlerpg as idlerpg
from core_plugins.rooms import JOINED_ROOMS
from utils.command import Role


class DummyStore:
    def __init__(self):
        self.globals = {idlerpg.IDLERPG_ENABLED_KEY: {"room@conf": True}}

    async def get_global(self, key, default=None):
        return self.globals.get(key, default)

    async def set_global(self, key, value):
        self.globals[key] = value


class DummyBot:
    def __init__(self):
        self.store = DummyStore()
        self.db = types.SimpleNamespace(
            users=types.SimpleNamespace(plugin=lambda name: self.store)
        )
        self.replies = []
        self.reply = lambda msg, text, **kwargs: self.replies.append((text, kwargs))
        self.prefix = ","
        self.boundjid = types.SimpleNamespace(bare="bot@envs.net")
        self.plugin = {"xep_0045": object()}
        self.presence = types.SimpleNamespace(joined_rooms={"room@conf": "envsbot"})
        self.bot_plugins = types.SimpleNamespace(register_event=lambda *a, **k: None)
        self.audit_events = []
        self.tasks = types.SimpleNamespace(
            create=lambda plugin, coro, name=None: DummyTask(coro, name)
        )

    async def get_user_role(self, jid, room=None):
        if str(jid).startswith("admin@"):
            return Role.ADMIN
        if str(jid).startswith("mod@"):
            return Role.MODERATOR
        return Role.USER

    async def audit(self, event, actor=None, target=None, details=None):
        self.audit_events.append((event, actor, target, details or {}))


class DummyTask:
    def __init__(self, coro=None, name=None):
        self.coro = coro
        self.name = name
        self.cancelled = False
        if coro is not None:
            coro.close()

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True

    def __await__(self):
        async def _done():
            return None
        return _done().__await__()


class DummyMsg:
    def __init__(self, body=",idlerpg", bare="room@conf", resource="Alice", mtype="groupchat"):
        self.data = {
            "from": types.SimpleNamespace(bare=bare, resource=resource),
            "to": types.SimpleNamespace(bare="bot@envs.net"),
            "type": mtype,
            "body": body,
            "mucnick": resource,
        }

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)


@pytest.fixture(autouse=True)
def clear_idlerpg_state():
    idlerpg.ROOM_TASKS.clear()
    JOINED_ROOMS.clear()
    idlerpg._core.JOINED_ROOMS = JOINED_ROOMS
    JOINED_ROOMS["room@conf"] = {
        "nicks": {
            "Alice": {"jid": "alice@envs.net", "affiliation": "member"},
            "Mod": {"jid": "mod@envs.net", "affiliation": "member"},
            "Admin": {"jid": "admin@envs.net", "affiliation": "admin"},
        }
    }
    yield
    idlerpg.ROOM_TASKS.clear()
    JOINED_ROOMS.clear()


@pytest.mark.asyncio
async def test_register_status_and_lists():
    bot = DummyBot()
    msg = DummyMsg()

    await idlerpg.idlerpg_command(
        bot,
        "alice@envs.net",
        "Alice",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )
    assert "Welcome Alice" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["status"], msg, True)
    assert "level 0 sysadmin" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["top"], msg, True)
    assert "IdleRPG Top Players" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["players"], msg, True)
    assert "Alice" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_enabled_is_room_feature_status_and_status_stays_player_status(monkeypatch):
    bot = DummyBot()

    async def noop_sync(_bot):
        return None

    monkeypatch.setattr(idlerpg, "_sync_tasks_to_enabled_rooms", noop_sync)

    admin_pm = DummyMsg(bare="room@conf", resource="Mod", mtype="chat")
    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["enabled"], admin_pm, False)
    assert "IdleRPG is **enabled**" in bot.replies[-1][0]

    bot.store.globals[idlerpg.IDLERPG_ENABLED_KEY]["room@conf"] = False
    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["enabled"], admin_pm, False)
    assert "IdleRPG is **disabled**" in bot.replies[-1][0]
    bot.store.globals[idlerpg.IDLERPG_ENABLED_KEY]["room@conf"] = True

    public_msg = DummyMsg()
    await idlerpg.idlerpg_command(
        bot,
        "alice@envs.net",
        "Alice",
        ["register", "Alice", "sysadmin"],
        public_msg,
        True,
    )

    alice_pm = DummyMsg(bare="room@conf", resource="Alice", mtype="chat")
    await idlerpg.idlerpg_command(
        bot, "alice@envs.net", "Alice", ["status", "Alice"], alice_pm, False
    )
    assert "level 0 sysadmin" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_message_penalty_and_logout_login(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )

    before = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]["players"]["alice@envs.net"]["next"]
    await idlerpg.on_message(bot, DummyMsg(body="hello world"))
    after = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]["players"]["alice@envs.net"]["next"]
    assert after > before

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["logout"], msg, True)
    player = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]["players"]["alice@envs.net"]
    assert player["logged_out"] is True

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["login"], msg, True)
    assert player["logged_out"] is False


@pytest.mark.asyncio
async def test_tick_levels_up_and_can_show_items(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    player = room["players"]["alice@envs.net"]
    player["next"] = 1
    room["last_tick"] = idlerpg._now() - 2
    monkeypatch.setattr(idlerpg.random, "random", lambda: 1.0)

    await idlerpg._tick_room(bot, "room@conf", announce=True)

    assert player["level"] >= 1
    assert any("reached level" in text for text, _ in bot.replies)

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["items"], msg, True)
    assert "Items for Alice" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_admin_push_setlevel_reset_delete():
    bot = DummyBot()
    msg = DummyMsg(resource="Admin")
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        DummyMsg(),
        True,
    )

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["setlevel", "Alice", "5"], msg, True)
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    assert room["players"]["alice@envs.net"]["level"] == 5

    before = room["players"]["alice@envs.net"]["next"]
    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["push", "Alice", "1m"], msg, True)
    assert room["players"]["alice@envs.net"]["next"] < before

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["reset", "Alice"], msg, True)
    assert room["players"]["alice@envs.net"]["level"] == 0

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["delete", "Alice"], msg, True)
    assert "alice@envs.net" not in room["players"]


@pytest.mark.asyncio
async def test_quest_and_runtime_state(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    data = {"rooms": {"room@conf": {"players": {}, "name_index": {}, "quest": {"active": False, "next_at": idlerpg._now()}, "last_tick": idlerpg._now()}}}
    room = data["rooms"]["room@conf"]
    for idx in range(4):
        jid = f"u{idx}@envs.net"
        room["players"][jid] = idlerpg._normalize_player(jid, {"name": f"U{idx}", "class": "idler", "level": 40, "next": 100})
        JOINED_ROOMS["room@conf"]["nicks"][f"U{idx}"] = {"jid": jid, "affiliation": "member"}
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = data
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])

    await idlerpg._maybe_run_quest(room, "room@conf", messages := [])
    assert room["quest"]["active"] is True
    assert messages

    state = await idlerpg.get_runtime_state(bot, "room@conf")
    assert state["players"] == 4
    assert state["active_quests"] == 1

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["quest"], msg, True)
    assert "are on a quest" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_cleanup_room_state_removes_data_and_task():
    bot = DummyBot()
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {"rooms": {"room@conf": idlerpg._blank_room()}}
    idlerpg.ROOM_TASKS["room@conf"] = DummyTask()

    await idlerpg.cleanup_room_state(bot, "room@conf")

    assert "room@conf" not in bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]
    assert "room@conf" not in idlerpg.ROOM_TASKS


def test_duration_clock_and_next_level_line():
    player = {"name": "Alice", "next": 93784}
    assert idlerpg._duration_clock(93784) == "1 days, 02:03:04"
    assert idlerpg._next_level_line(player) == "Alice reaches next level in 1 days, 02:03:04."


def test_idlerpg_small_helper_edges(monkeypatch):
    bot = types.SimpleNamespace(prefix="!")
    assert idlerpg._command_prefix(bot) == "!"
    assert idlerpg._command_prefix(types.SimpleNamespace(prefix="")) == ","
    assert idlerpg._possessive("Chris") == "Chris'"
    assert idlerpg._possessive("Alice") == "Alice's"
    assert idlerpg._duration(None) == "0s"
    assert idlerpg._duration(90061) == "1d 1h 1m 1s"
    assert idlerpg._add_time({"next": -5}, -10) == 0
    player = {"next": 5}
    assert idlerpg._remove_time(player, 10) == 5
    assert player["next"] == 0
    assert idlerpg._safe_name(" Alice !@#_-. 123 ") == "Alice_-.123"
    assert idlerpg._safe_class("sys\n\tadmin   ops") == "sysadmin ops"
    assert idlerpg._ttl_for_level(-10) == idlerpg._ttl_for_level(0)
    monkeypatch.setattr(idlerpg, "MAX_PENALTY", 10)
    assert idlerpg._penalty_for(50, 100) == 10


def test_idlerpg_player_normalization_and_lookup_edges(monkeypatch):
    monkeypatch.setattr(idlerpg.random, "randint", lambda start, stop: stop)
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice!",
            "class": "sys\nadmin",
            "level": "bad",
            "next": "bad",
            "alignment": "x",
            "items": {"weapon": "bad", "shield": 3},
            "unique_items": {"weapon": "The Great Hammer of /bin/sh", "bad": "ignored"},
            "stats": {"wins": "bad", "losses": -5},
            "achievements": "bad",
            "title": "level_10",
            "x": 9999,
            "y": 9999,
        },
    )
    assert player["name"] == "Alice"
    assert player["class"] == "sysadmin"
    assert player["level"] == 0
    assert player["next"] == idlerpg._ttl_for_level(0)
    assert player["alignment"] == "n"
    assert player["items"]["weapon"] == 0
    assert player["items"]["shield"] == 3
    assert player["unique_items"] == {"weapon": "The Great Hammer of /bin/sh"}
    assert player["stats"] == {"wins": 0, "losses": 0}
    assert player["achievements"] == []
    assert player["title"] == ""
    assert 0 <= player["x"] <= idlerpg.MAP_X
    assert 0 <= player["y"] <= idlerpg.MAP_Y

    room = {
        "players": {"alice@envs.net": player, "bad@envs.net": "not-a-player"},
        "name_index": {},
    }
    assert idlerpg._rebuild_name_index(room) == {"alice": "alice@envs.net"}
    assert idlerpg._find_player(room, None) == (None, None)
    assert idlerpg._find_player(room, "alice@envs.net") == ("alice@envs.net", player)
    assert idlerpg._find_player(room, "Alice") == ("alice@envs.net", player)
    assert idlerpg._find_player(room, "missing") == (None, None)


def test_idlerpg_achievements_titles_stats_and_regions():
    player = {
        "level": 100,
        "idled": 604800,
        "items": {item: 100 for item in idlerpg.ITEMS},
        "stats": {
            "battles_won": 10,
            "team_battles_won": 5,
            "quests_completed": 3,
            "godsends": 10,
            "calamities": 10,
            "bad": "nope",
        },
        "unique_items": {
            "weapon": "The Great Hammer of /bin/sh",
            "shield": "The Ancient Shell of envs.net",
            "tunic": "The Cluehammer of Good Documentation",
        },
    }
    assert idlerpg._award(player, "does-not-exist") is False
    assert idlerpg._award(player, "founder") is True
    assert idlerpg._award(player, "founder") is False
    idlerpg._check_level_achievements(player)
    for achievement in [
        "level_10",
        "level_25",
        "level_50",
        "level_75",
        "level_100",
        "silent_24h",
        "silent_week",
        "collector",
        "hoarder",
        "battle_scarred",
        "team_veteran",
        "quest_walker",
        "very_lucky",
        "the_unlucky", "artifact_finder",
    ]:
        assert achievement in player["achievements"]
    assert idlerpg._stats(player)["bad"] == 0
    idlerpg._inc_stat(player, "battles_won", -99)
    assert idlerpg._stats(player)["battles_won"] == 0
    player["title"] = "level_100"
    assert idlerpg._display_title(player) == "Mythic Idler"
    assert (
        idlerpg._display_character(
            {"name": "Alice", "title": "level_100", "achievements": ["level_100"]}
        )
        == "Alice, Mythic Idler"
    )
    assert idlerpg._achievement_description("missing") == ""
    assert idlerpg._map_region_name("bad", 1) == "the wilderness"
    assert idlerpg._player_region({"x": 300, "y": 230}) == "Velbragh"
    assert idlerpg._room_slug("idlerpg@conference.envs.net") == "idlerpg_at_conference.envs.net"
    assert idlerpg._slug("***") == "idlerpg"
    assert idlerpg._season_duration_seconds() == max(0, idlerpg.SEASON_DURATION_DAYS * 86400)


def test_pvp_battle_can_crit_and_drop_item(monkeypatch):
    alice = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "level": 10, "next": 10000, "items": {"weapon": 1}},
    )
    bob = idlerpg._normalize_player(
        "bob@envs.net",
        {"name": "Bob", "class": "wizard", "level": 10, "next": 10000, "items": {"weapon": 20}},
    )
    players = [("alice@envs.net", alice), ("bob@envs.net", bob)]

    def choice(seq):
        return seq[0]

    monkeypatch.setattr(idlerpg.random, "choice", choice)
    monkeypatch.setattr(idlerpg.random, "random", lambda: 0.0)
    randint_values = itertools.cycle([999, 0, 120, 30])
    monkeypatch.setattr(idlerpg.random, "randint", lambda _start, _stop: next(randint_values))

    messages = []
    idlerpg._run_pvp_battle(players, messages)

    assert alice["next"] < 10000
    assert bob["next"] > 10000
    assert alice["items"]["weapon"] == 20
    assert bob["items"]["weapon"] == 1
    assert any("has challenged Bob" in line and "won" in line for line in messages)
    assert any("Critical Strike" in line for line in messages)
    assert any("dropped their level 20 weapon" in line for line in messages)
    assert any("Bob reaches next level in" in line for line in messages)


def test_godsend_calamity_and_alignment_bonus_messages(monkeypatch):
    alice = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "level": 10, "next": 10000, "alignment": "g"},
    )
    bob = idlerpg._normalize_player(
        "bob@envs.net",
        {"name": "Bob", "class": "wizard", "level": 11, "next": 9000, "alignment": "g"},
    )
    players = [("alice@envs.net", alice), ("bob@envs.net", bob)]

    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(idlerpg.random, "sample", lambda seq, count: seq[:count])
    monkeypatch.setattr(idlerpg.random, "randint", lambda start, stop: start)
    monkeypatch.setattr(idlerpg.random, "random", lambda: 0.0)

    calamity_messages = []
    idlerpg._run_godsend_or_calamity(players, calamity_messages)
    assert alice["next"] > 10000
    assert any("terrible calamity" in line for line in calamity_messages)
    assert any("Alice reaches next level in" in line for line in calamity_messages)

    alice["next"] = 10000
    bob["next"] = 9000
    alignment_messages = []
    assert idlerpg._run_alignment_bonus(players, alignment_messages) is True
    assert alice["next"] == 9300
    assert bob["next"] == 8370
    assert "7% of their time is removed" in alignment_messages[0]
    assert any("Bob reaches next level in" in line for line in alignment_messages)

@pytest.mark.asyncio
async def test_profile_achievements_title_map_and_export(tmp_path, monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    monkeypatch.setattr(idlerpg, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg, "EXPORT_PUBLIC_BASE_URL", "https://envs.net/idlerpg")

    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["achievements"], msg, True)
    assert "Founder" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["title", "founder"], msg, True)
    assert "Founder" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["profile"], msg, True)
    assert "Profile: Alice" in bot.replies[-1][0]
    assert "Profile JSON: https://envs.net/idlerpg/room_at_conf/profiles/Alice.json" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["map"], msg, True)
    assert "IdleRPG map for room@conf" in bot.replies[-1][0]
    assert "Map JSON: https://envs.net/idlerpg/room_at_conf/map.json" in bot.replies[-1][0]

    admin_msg = DummyMsg(resource="Admin")
    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["export"], admin_msg, True)
    assert (tmp_path / "index.json").exists()
    assert (tmp_path / "leaderboard.json").exists()
    assert (tmp_path / "room_at_conf" / "profiles" / "Alice.json").exists()


@pytest.mark.asyncio
async def test_season_hall_of_fame_and_manual_reset(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg(resource="Admin")
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        DummyMsg(),
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    room["players"]["alice@envs.net"]["level"] = 12
    room["players"]["alice@envs.net"]["next"] = 5

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["season", "end"], msg, True)
    assert "Champion: Alice" in bot.replies[-1][0]
    assert room["hall_of_fame"][-1]["champion"] == "Alice"
    assert room["players"]["alice@envs.net"]["level"] == 12

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["season", "reset"], msg, True)
    assert "Players were reset" in bot.replies[-1][0]
    assert room["players"]["alice@envs.net"]["level"] == 0

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["hof"], DummyMsg(), True)
    assert "Hall of Fame" in bot.replies[-1][0]
    assert "Alice" in bot.replies[-1][0]



@pytest.mark.asyncio
async def test_mutating_admin_commands_require_room_admin():
    bot = DummyBot()
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        DummyMsg(),
        True,
    )
    mod_msg = DummyMsg(resource="Mod")

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["export"], mod_msg, True)
    assert "Only room owners/admins" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["season", "end"], mod_msg, True)
    assert "Only room owners/admins" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["delete", "Alice"], mod_msg, True)
    assert "Only room owners/admins" in bot.replies[-1][0]


def test_ascii_map_rendering_contains_grid_and_legend():
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "level": 3, "x": 10, "y": 20},
    )
    lines = idlerpg._render_ascii_map("room@conf", [("alice@envs.net", player)], {"active": False})

    assert any(line.startswith("+") and line.endswith("+") for line in lines)
    assert any("1 Alice" in line for line in lines)
    assert any("lv.3" in line for line in lines)

def test_season_rollover_and_player_movement(monkeypatch):
    room = idlerpg._blank_room()
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "level": 3, "next": 100, "items": {}},
    )
    room["players"]["alice@envs.net"] = player
    room["season"] = {"id": "old", "started_at": idlerpg._now() - 10, "ends_at": idlerpg._now() - 1}
    monkeypatch.setattr(idlerpg, "SEASON_ENABLED", True)
    monkeypatch.setattr(idlerpg, "SEASON_DURATION_DAYS", 1)
    monkeypatch.setattr(idlerpg, "MAP_STEP_PER_TICK", 1)
    monkeypatch.setattr(idlerpg.random, "randint", lambda start, stop: 1)

    old_pos = (player["x"], player["y"])
    messages = []
    idlerpg._maybe_rollover_season("room@conf", room, messages)
    idlerpg._move_player(player, 2)

    assert room["hall_of_fame"][-1]["champion"] == "Alice"
    assert messages and "season old has ended" in messages[0]
    assert (player["x"], player["y"]) != old_pos

@pytest.mark.asyncio
async def test_events_export_has_no_raw_jids_and_events_command(tmp_path, monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    monkeypatch.setattr(idlerpg, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg, "EXPORT_ENABLED", True)

    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )
    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["events"], msg, True)
    assert "IdleRPG Recent Events" in bot.replies[-1][0]
    assert "alice@envs.net" not in bot.replies[-1][0]

    room_dir = tmp_path / "room_at_conf"
    assert (room_dir / "events.json").exists()
    payload = (room_dir / "players.json").read_text(encoding="utf-8")
    events_payload = (room_dir / "events.json").read_text(encoding="utf-8")
    assert "alice@envs.net" not in payload
    assert "jid_hash" not in payload
    assert "alice@envs.net" not in events_payload


def test_unique_item_roll_grants_title_and_public_record(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "level": 52, "next": 10000},
    )
    monkeypatch.setattr(idlerpg, "UNIQUE_ITEMS_ENABLED", True)
    monkeypatch.setattr(idlerpg, "UNIQUE_ITEM_MIN_LEVEL", 25)
    monkeypatch.setattr(idlerpg, "UNIQUE_ITEM_CHANCE", 1.0)
    monkeypatch.setattr(idlerpg.random, "random", lambda: 0.0)
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(idlerpg.random, "randint", lambda start, stop: start)

    message = idlerpg._grant_level_item(player)

    assert "The Ancient Shell of envs.net" in message
    assert player["unique_items"]["shield"] == "The Ancient Shell of envs.net"
    assert "unique_item" in player["achievements"]
    public = idlerpg._player_public_record("room@conf", "alice@envs.net", player, rank=1)
    assert "jid_hash" not in public
    assert public["unique_items"]["shield"] == "The Ancient Shell of envs.net"


def test_team_battle_changes_clocks_and_awards(monkeypatch):
    players = []
    for idx in range(6):
        jid = f"u{idx}@envs.net"
        player = idlerpg._normalize_player(
            jid,
            {"name": f"U{idx}", "class": "idler", "level": 30 + idx, "next": 10000, "items": {"weapon": 10 + idx}},
        )
        players.append((jid, player))

    monkeypatch.setattr(idlerpg.random, "sample", lambda seq, count: seq[:count])
    randint_values = itertools.cycle([9999, 0])
    monkeypatch.setattr(idlerpg.random, "randint", lambda _start, _stop: next(randint_values))

    messages = []
    idlerpg._run_team_battle(players, messages)

    assert any("team battled" in line for line in messages)
    assert players[0][1]["next"] < 10000
    assert players[3][1]["next"] > 10000
    assert "team_battle_winner" in players[0][1]["achievements"]


def test_random_event_uses_only_available_event_weights_for_small_rooms(monkeypatch):
    room = idlerpg._blank_room()
    room["players"]["alice@envs.net"] = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "online": True},
    )
    monkeypatch.setattr(idlerpg, "EVENT_CHANCE", 1.0)
    random_values = iter([0.0, 0.70])
    monkeypatch.setattr(idlerpg.random, "random", lambda: next(random_values))
    monkeypatch.setattr(
        idlerpg,
        "_run_item_blessing",
        lambda _players, _messages: _messages.append("item"),
    )
    monkeypatch.setattr(
        idlerpg,
        "_run_godsend_or_calamity",
        lambda _players, _messages: _messages.append("fate"),
    )

    messages = []
    asyncio.run(idlerpg._maybe_run_random_event(room, "room@conf", messages))

    assert messages == ["fate"]

@pytest.mark.asyncio
async def test_logout_grace_clears_pending_penalty(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    monkeypatch.setattr(idlerpg, "LOGOUT_GRACE_SECONDS", 300)
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    player = room["players"]["alice@envs.net"]
    before = player["next"]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["logout"], msg, True)
    assert player["logged_out"] is True
    assert player["pending_logout_penalty"]
    assert player["next"] == before

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["login"], msg, True)
    assert player["logged_out"] is False
    assert player["pending_logout_penalty"] == {}
    assert player["next"] == before
    assert "Logout grace used" in bot.replies[-1][0]


def test_event_retention_prunes_old_events(monkeypatch):
    room = idlerpg._blank_room()
    now = 1_700_000_000
    monkeypatch.setattr(idlerpg, "EVENT_RETENTION_DAYS", 1)
    monkeypatch.setattr(idlerpg, "EVENT_LOG_LIMIT", 10)
    monkeypatch.setattr(idlerpg, "_now", lambda: now)
    room["events"] = [
        {"ts": now - 3 * 86400, "kind": "old", "text": "old"},
        {"ts": now - 60, "kind": "new", "text": "new"},
    ]

    idlerpg._record_event(room, "game", "fresh")

    assert [event["text"] for event in room["events"]] == ["new", "fresh"]


def test_unique_item_bonuses_and_achievement_catalog_export(tmp_path, monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice",
            "class": "sysadmin",
            "level": 52,
            "next": 10000,
            "unique_items": {"weapon": "The Great Hammer of /bin/sh"},
            "items": {"weapon": 150},
            "x": 300,
            "y": 230,
        },
    )
    assert idlerpg._unique_bonus_percent(player, "battle_bonus") >= 5
    assert idlerpg._battle_power(player) > 52 * 10 + idlerpg._item_sum(player)
    public = idlerpg._player_public_record("room@conf", "alice@envs.net", player, rank=1)
    assert public["region"] == "Velbragh"
    assert public["unique_item_bonuses"][0]["bonus"] == "battle_bonus"

    monkeypatch.setattr(idlerpg, "EXPORT_PATH", str(tmp_path))
    room = idlerpg._blank_room()
    room["players"] = {"alice@envs.net": player}
    idlerpg._export_room_state(tmp_path, "room@conf", room, idlerpg._now())
    assert (tmp_path / "room_at_conf" / "achievements.json").exists()


@pytest.mark.asyncio
async def test_stats_command_admin_only():
    bot = DummyBot()
    msg = DummyMsg(resource="Admin")
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        DummyMsg(),
        True,
    )

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["stats"], DummyMsg(resource="Mod"), True)
    assert "Only room owners/admins" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["stats"], msg, True)
    assert "IdleRPG stats" in bot.replies[-1][0]
    assert "Logout grace" in bot.replies[-1][0]


def test_event_retention_sanitizes_and_limits(monkeypatch):
    room = {
        "events": [
            {"ts": 900, "kind": "old", "text": "too old"},
            {"ts": 1900, "kind": "keep", "text": "first"},
        ]
    }
    monkeypatch.setattr(idlerpg, "_now", lambda: 2000)
    monkeypatch.setattr(idlerpg, "EVENT_RETENTION_DAYS", 0)
    monkeypatch.setattr(idlerpg, "EVENT_LOG_LIMIT", 2)

    idlerpg._record_event(
        room,
        "bad kind !",
        "hello" * 200,
        players=["Alice", "", "Bob"],
        data={"jid": "secret@envs.net", "note": "public", "items": ["a", object(), 1]},
    )
    idlerpg._record_event(room, "latest", "last")

    public = idlerpg._room_events(room)
    assert [event["kind"] for event in public] == ["bad_kind__", "latest"]
    assert public[0]["text"].startswith("hello")
    assert len(public[0]["text"]) == 500
    assert public[0]["players"] == ["Alice", "Bob"]
    assert "jid" not in public[0]["data"]
    assert public[0]["data"]["note"] == "public"
    assert public[0]["data"]["items"] == ["a", 1]

    monkeypatch.setattr(idlerpg, "EVENT_RETENTION_DAYS", 1)
    room["events"] = [
        {"ts": 2000 - 90000, "kind": "old", "text": "too old"},
        {"ts": 1999, "kind": "new", "text": "kept"},
    ]
    assert [event["text"] for event in idlerpg._room_events(room)] == ["kept"]


def test_unique_item_level_gating_bonuses_and_grant(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": idlerpg.UNIQUE_ITEM_MIN_LEVEL - 1, "next": 1000},
    )
    assert idlerpg._roll_unique_item(player) is None

    player["level"] = 50
    monkeypatch.setattr(idlerpg.random, "random", lambda: 0.0)
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(idlerpg.random, "randint", lambda low, high: high)

    unique = idlerpg._roll_unique_item(player)
    assert unique is not None
    assert unique["name"] == idlerpg.UNIQUE_ITEMS[0]["name"]
    assert unique["level"] == idlerpg.UNIQUE_ITEMS[0]["max_item_level"]

    monkeypatch.setattr(
        idlerpg,
        "_roll_unique_item",
        lambda _player: {
            "name": "The Great Hammer of /bin/sh",
            "slot": "weapon",
            "level": 155,
            "bonus": "battle_bonus",
            "bonus_percent": 5,
        },
    )
    text = idlerpg._grant_level_item(player)
    assert "The Great Hammer of /bin/sh" in text
    assert player["items"]["weapon"] == 155
    assert player["unique_items"]["weapon"] == "The Great Hammer of /bin/sh"
    assert "unique_item" in player["achievements"]
    assert idlerpg._stats(player)["unique_items_found"] == 1
    assert idlerpg._unique_bonus_percent(player, "battle_bonus") == 5
    assert idlerpg._adjust_percent_amount(100, player, "battle_bonus", increase=True) == 105

    player["unique_items"] = {
        "weapon": "The Great Hammer of /bin/sh",
        "tunic": "The Cluehammer of Good Documentation",
        "shield": "not a real unique item",
    }
    assert idlerpg._unique_bonus_percent(player, "battle_bonus") == 13
    assert idlerpg._unique_bonus_percent(player, "missing_bonus") == 0


@pytest.mark.asyncio
async def test_quest_min_level_start_and_completion_with_bonus(monkeypatch):
    room = idlerpg._blank_room()
    room_jid = "room@conf"
    JOINED_ROOMS[room_jid] = {"nicks": {}}
    for index in range(4):
        jid = f"quester{index}@envs.net"
        name = f"Quester{index}"
        JOINED_ROOMS[room_jid]["nicks"][name] = {"jid": jid, "affiliation": "member"}
        room["players"][jid] = idlerpg._normalize_player(
            jid,
            {
                "name": name,
                "level": idlerpg.QUEST_MIN_LEVEL - 1,
                "next": 1000,
                "x": 320,
                "y": 240,
            },
        )
    room["quest"] = {"active": False, "next_at": 0}
    monkeypatch.setattr(idlerpg, "_now", lambda: 1000)
    monkeypatch.setattr(idlerpg.random, "shuffle", lambda seq: None)
    monkeypatch.setattr(idlerpg.random, "randint", lambda low, high: low)
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])

    messages: list[str] = []
    await idlerpg._maybe_run_quest(room, room_jid, messages)
    assert messages == []
    assert room["quest"] == {"active": False, "next_at": 1000 + idlerpg.QUEST_INTERVAL}

    for player in room["players"].values():
        player["level"] = idlerpg.QUEST_MIN_LEVEL
    room["quest"] = {"active": False, "next_at": 0}
    await idlerpg._maybe_run_quest(room, room_jid, messages)
    assert room["quest"]["active"] is True
    assert len(room["quest"]["questers"]) == 4
    assert any("have been chosen" in line for line in messages)
    assert all("quester" in player["achievements"] for player in room["players"].values())

    first_jid = room["quest"]["questers"][0]
    room["players"][first_jid]["unique_items"] = {"pair of boots": "The Boots of Silent Idling"}
    before = int(room["players"][first_jid]["next"])
    room["quest"]["complete_at"] = 999
    messages.clear()
    await idlerpg._maybe_run_quest(room, room_jid, messages)
    assert room["quest"]["active"] is False
    assert room["players"][first_jid]["next"] == int(before * 70 / 100)
    assert "quest_hero" in room["players"][first_jid]["achievements"]
    assert any("completed their quest" in line for line in messages)


def test_export_room_state_includes_public_rules_and_achievement_catalog(tmp_path, monkeypatch):
    room = idlerpg._blank_room()
    room["players"] = {
        "alice@envs.net": idlerpg._normalize_player(
            "alice@envs.net",
            {"name": "Alice", "level": 25, "next": 1000, "x": 300, "y": 200},
        )
    }
    idlerpg._record_event(room, "level", "Alice reached level 25", players=["Alice"])

    monkeypatch.setattr(idlerpg, "EXPORT_PUBLIC_BASE_URL", "https://example.org/idlerpg/data")
    summary = idlerpg._export_room_state(tmp_path, "room@conf", room, 1234)
    assert summary["leaderboard_url"].endswith("/room_at_conf/leaderboard.json")

    import json
    room_payload = json.loads((tmp_path / "room_at_conf" / "room.json").read_text())
    assert room_payload["achievement_catalog"] == idlerpg._achievement_catalog()
    assert room_payload["map"] == {"width": idlerpg.MAP_X, "height": idlerpg.MAP_Y}
    assert room_payload["events"][0]["players"] == ["Alice"]
    assert "jid" not in room_payload["players"][0]


@pytest.mark.asyncio
async def test_stats_command_is_primary_and_balance_alias_still_works():
    bot = DummyBot()
    msg = DummyMsg(resource="Admin")
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        DummyMsg(),
        True,
    )

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["stats"], msg, True)
    assert "IdleRPG stats" in bot.replies[-1][0]
    assert "Average level" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["balance"], msg, True)
    assert "IdleRPG stats" in bot.replies[-1][0]
    assert "balance" not in idlerpg._usage(bot)


def test_battle_amount_alignment_factors_and_logout_penalty(monkeypatch):
    monkeypatch.setattr(idlerpg, "PENALTY_STEP", 1.0)
    monkeypatch.setattr(idlerpg, "MAX_PENALTY", 0)
    evil = {"name": "Eve", "level": 5, "next": 1000, "alignment": "e", "stats": {}}
    good = {"name": "Grace", "level": 5, "next": 1000, "alignment": "g", "stats": {}}
    neutral = {"name": "Neo", "level": 5, "next": 1000, "alignment": "n", "stats": {}}
    unknown = {"name": "Myst", "level": 5, "next": 1000, "alignment": "x", "stats": {}}

    assert idlerpg._battle_amount(evil, 100, "win") == 110
    assert idlerpg._battle_amount(good, 100, "loss") == 90
    assert idlerpg._battle_amount(neutral, 100, "win") == 97
    assert idlerpg._battle_amount(unknown, 100, "win") == 100

    monkeypatch.setattr(idlerpg, "LOGOUT_PENALTY", 20)
    changed = idlerpg._apply_logout_penalty(neutral)
    assert changed == 20
    assert neutral["next"] == 1020
    assert neutral["penalties"]["logout"] == 20
    assert neutral["pending_logout_penalty"] == {}
    assert neutral["stats"]["logouts"] == 1


def test_pending_logout_penalty_waits_then_applies(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": 1, "next": 1000, "pending_logout_penalty": {"due_at": 2000}},
    )
    monkeypatch.setattr(idlerpg, "_now", lambda: 1000)
    messages: list[str] = []
    idlerpg._maybe_apply_pending_logout_penalty(player, messages)
    assert messages == []
    assert player["next"] == 1000
    assert player["pending_logout_penalty"] == {"due_at": 2000}

    monkeypatch.setattr(idlerpg, "_now", lambda: 3000)
    monkeypatch.setattr(idlerpg, "LOGOUT_PENALTY", 1)
    monkeypatch.setattr(idlerpg, "PENALTY_STEP", 1.0)
    idlerpg._maybe_apply_pending_logout_penalty(player, messages)
    assert player["next"] == 1001
    assert player["pending_logout_penalty"] == {}
    assert any("stayed logged out past the grace period" in line for line in messages)
    assert any("reaches next level" in line for line in messages)


def test_item_blessing_normalizes_bad_item_level_and_records(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": 21, "next": 1000, "items": {"ring": "bad"}, "x": 300, "y": 230},
    )
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])

    messages: list[str] = []
    idlerpg._run_item_blessing([("alice@envs.net", player)], messages)

    assert player["items"][idlerpg.ITEMS[0]] == 2
    assert player["stats"]["item_blessings"] == 1
    assert messages and "wandering enchanter" in messages[0]
    assert "Velbragh" in messages[0]


@pytest.mark.asyncio
async def test_align_command_usage_missing_character_and_success():
    bot = DummyBot()
    room_msg = DummyMsg()
    private_without_room = DummyMsg(bare="user@envs.net", resource="Alice", mtype="chat")

    await idlerpg._handle_align(bot, "alice@envs.net", ["align", "good"], private_without_room, False)
    assert "Alignment is room-scoped" in bot.replies[-1][0]

    await idlerpg._handle_align(bot, "alice@envs.net", ["align"], room_msg, True)
    assert "Usage:" in bot.replies[-1][0]

    await idlerpg._handle_align(bot, "alice@envs.net", ["align", "evil"], room_msg, True)
    assert "do not have" in bot.replies[-1][0]

    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        room_msg,
        True,
    )
    await idlerpg._handle_align(bot, "alice@envs.net", ["align", "good"], room_msg, True)
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    assert room["players"]["alice@envs.net"]["alignment"] == "g"
    assert room["events"][-1]["kind"] == "alignment"
    assert "now good" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_remove_me_command_room_scope_missing_and_success():
    bot = DummyBot()
    room_msg = DummyMsg()
    private_without_room = DummyMsg(bare="user@envs.net", resource="Alice", mtype="chat")

    await idlerpg._handle_remove_me(bot, "alice@envs.net", private_without_room, False)
    assert "remove-me is room-scoped" in bot.replies[-1][0]

    await idlerpg._handle_remove_me(bot, "alice@envs.net", room_msg, True)
    assert "do not have" in bot.replies[-1][0]

    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        room_msg,
        True,
    )
    await idlerpg._handle_remove_me(bot, "alice@envs.net", room_msg, True)
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    assert "alice@envs.net" not in room["players"]
    assert room["name_index"] == {}
    assert bot.audit_events[-1][0] == "idlerpg_remove_me"
    assert "character Alice removed" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_enabled_rooms_and_task_sync_lifecycle(monkeypatch):
    bot = DummyBot()
    bot.store.globals[idlerpg.IDLERPG_ENABLED_KEY] = {
        "room@conf": True,
        "off@conf": False,
        123: True,
    }
    ensured: list[str] = []
    cancelled: list[str] = []

    async def fake_ensure(_bot, room_jid):
        ensured.append(room_jid)
        idlerpg.ROOM_TASKS[room_jid] = DummyTask(name=room_jid)
        return idlerpg.ROOM_TASKS[room_jid]

    async def fake_cancel(room_jid):
        cancelled.append(room_jid)
        idlerpg.ROOM_TASKS.pop(room_jid, None)

    monkeypatch.setattr(idlerpg, "_ensure_game_task", fake_ensure)
    monkeypatch.setattr(idlerpg, "_cancel_room_task", fake_cancel)

    assert await idlerpg._enabled_rooms(bot) == {"room@conf": True, "off@conf": False, 123: True}
    await idlerpg._start_enabled_room_tasks(bot)
    assert ensured == ["room@conf", "123"]

    idlerpg.ROOM_TASKS["old@conf"] = DummyTask(name="old")
    ensured.clear()
    await idlerpg._sync_tasks_to_enabled_rooms(bot)
    assert ensured == ["123", "room@conf"]
    assert cancelled == ["old@conf"]

    bot.store.globals[idlerpg.IDLERPG_ENABLED_KEY] = "broken"
    assert await idlerpg._enabled_rooms(bot) == {}


@pytest.mark.asyncio
async def test_ready_restart_unload_delegate_to_task_helpers(monkeypatch):
    bot = DummyBot()
    started = 0
    cancelled: list[str] = []

    async def fake_start(_bot):
        nonlocal started
        started += 1

    async def fake_cancel(room_jid):
        cancelled.append(room_jid)
        idlerpg.ROOM_TASKS.pop(room_jid, None)

    monkeypatch.setattr(idlerpg, "_start_enabled_room_tasks", fake_start)
    monkeypatch.setattr(idlerpg, "_cancel_room_task", fake_cancel)

    await idlerpg.on_ready(bot)
    assert started == 1

    idlerpg.ROOM_TASKS["a@conf"] = DummyTask(name="a")
    idlerpg.ROOM_TASKS["b@conf"] = DummyTask(name="b")
    await idlerpg.restart_tasks(bot)
    assert cancelled == ["a@conf", "b@conf"]
    assert started == 2

    idlerpg.ROOM_TASKS["c@conf"] = DummyTask(name="c")
    await idlerpg.on_unload(bot)
    assert cancelled[-1] == "c@conf"


@pytest.mark.asyncio
async def test_on_load_registers_message_and_presence_handlers():
    registered = []
    bot = DummyBot()
    bot.bot_plugins = types.SimpleNamespace(
        register_event=lambda *args: registered.append(args)
    )

    await idlerpg.on_load(bot)

    assert [entry[:2] for entry in registered] == [
        (idlerpg.PLUGIN_NAME, "groupchat_message"),
        (idlerpg.PLUGIN_NAME, "groupchat_presence"),
    ]
    assert all(callable(entry[2]) for entry in registered)


@pytest.mark.asyncio
async def test_on_muc_presence_starts_task_only_when_enabled(monkeypatch):
    bot = DummyBot()
    pres = DummyMsg(bare="room@conf", resource="Alice")
    ensured: list[str] = []

    async def fake_enabled(_bot, _key, _plugin, room_jid):
        return room_jid == "room@conf"

    async def fake_ensure(_bot, room_jid):
        ensured.append(room_jid)
        return DummyTask(name=room_jid)

    monkeypatch.setattr(idlerpg._core, "_is_enabled_for_room", fake_enabled)
    monkeypatch.setattr(idlerpg, "_ensure_game_task", fake_ensure)

    await idlerpg.on_muc_presence(bot, pres)
    assert ensured == ["room@conf"]

    await idlerpg.on_muc_presence(bot, DummyMsg(bare="other@conf", resource="Alice"))
    assert ensured == ["room@conf"]

    async def raising_enabled(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(idlerpg._core, "_is_enabled_for_room", raising_enabled)
    await idlerpg.on_muc_presence(bot, pres)
    assert ensured == ["room@conf"]
