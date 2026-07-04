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
            "Mod": {"jid": "mod@envs.net", "affiliation": "admin"},
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
    msg = DummyMsg(resource="Mod")
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        DummyMsg(),
        True,
    )

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["setlevel", "Alice", "5"], msg, True)
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    assert room["players"]["alice@envs.net"]["level"] == 5

    before = room["players"]["alice@envs.net"]["next"]
    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["push", "Alice", "1m"], msg, True)
    assert room["players"]["alice@envs.net"]["next"] < before

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["reset", "Alice"], msg, True)
    assert room["players"]["alice@envs.net"]["level"] == 0

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["delete", "Alice"], msg, True)
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
    randint_values = iter([999, 0, 120, 30])
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

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["export"], msg, True)
    assert (tmp_path / "index.json").exists()
    assert (tmp_path / "leaderboard.json").exists()
    assert (tmp_path / "room_at_conf" / "profiles" / "Alice.json").exists()


@pytest.mark.asyncio
async def test_season_hall_of_fame_and_manual_reset(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg(resource="Mod")
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

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["season", "end"], msg, True)
    assert "Champion: Alice" in bot.replies[-1][0]
    assert room["hall_of_fame"][-1]["champion"] == "Alice"
    assert room["players"]["alice@envs.net"]["level"] == 12

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["season", "reset"], msg, True)
    assert "Players were reset" in bot.replies[-1][0]
    assert room["players"]["alice@envs.net"]["level"] == 0

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["hof"], DummyMsg(), True)
    assert "Hall of Fame" in bot.replies[-1][0]
    assert "Alice" in bot.replies[-1][0]


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
