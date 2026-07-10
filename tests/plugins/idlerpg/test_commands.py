from .helpers import (
    DummyBot,
    DummyMsg,
    JOINED_ROOMS,
    idlerpg,
    pytest,
    types,
)
from .helpers import _register_alice


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
async def test_enabled_shows_room_feature_state(monkeypatch):
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


@pytest.mark.asyncio
async def test_status_returns_player_status():
    bot = DummyBot()
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
async def test_message_penalty_falls_back_to_registered_nick_when_real_jid_missing(monkeypatch):
    bot = DummyBot()
    register_msg = DummyMsg(resource="P")
    await idlerpg._handle_register(
        bot,
        "p@example.org",
        ["register", "Battal", "picker"],
        register_msg,
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    player = room["players"]["p@example.org"]
    before = player["next"]

    JOINED_ROOMS["room@conf"]["nicks"]["P"] = {"jid": "room@conf/P", "affiliation": "member"}
    await idlerpg.on_message(bot, DummyMsg(body="Getting creative", resource="P"))

    assert player["next"] > before
    assert player["penalties"]["message"] > 0
    assert player["stats"]["messages"] == 1


@pytest.mark.asyncio
async def test_message_penalty_uses_character_name_when_jid_is_unavailable(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg(resource="Alice")
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

    JOINED_ROOMS["room@conf"]["nicks"]["Alice"] = {"jid": None, "affiliation": "member"}
    await idlerpg.on_message(bot, DummyMsg(body="hello without real jid", resource="Alice"))

    assert player["next"] > before
    assert player["penalties"]["message"] > 0


@pytest.mark.asyncio
async def test_message_penalty_generic_message_event_and_dedupe_by_stanza_id():
    bot = DummyBot()
    register_msg = DummyMsg(resource="skx")
    JOINED_ROOMS["room@conf"]["nicks"]["skx"] = {"jid": "skx@example.org", "affiliation": "member"}
    await idlerpg._handle_register(
        bot,
        "skx@example.org",
        ["register", "skx", "test"],
        register_msg,
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    player = room["players"]["skx@example.org"]
    before = player["next"]

    msg = DummyMsg(body="x", resource="skx", stanza_id="msg-1")
    await idlerpg.on_message(bot, msg)
    await idlerpg.on_message(bot, msg)
    msg2 = DummyMsg(body="x", resource="skx", stanza_id="msg-2")
    await idlerpg.on_message(bot, msg2)

    assert player["next"] == before + 2
    assert player["penalties"]["message"] == 2
    assert player["stats"]["messages"] == 2


@pytest.mark.asyncio
async def test_idlerpg_on_load_registers_generic_and_groupchat_message_events():
    bot = DummyBot()
    registered = []
    runtime_registered = []
    bot.bot_plugins = types.SimpleNamespace(
        register_event=lambda plugin, event, handler: registered.append(
            (plugin, event, handler)
        ),
        register_runtime_event=lambda plugin, event, handler: runtime_registered.append(
            (plugin, event, handler)
        ),
    )

    await idlerpg.on_load(bot)

    events = [(plugin, event) for plugin, event, _handler in registered]
    runtime_events = [(plugin, event) for plugin, event, _handler in runtime_registered]
    assert (idlerpg.PLUGIN_NAME, "groupchat_message") in events
    assert (idlerpg.PLUGIN_NAME, "message") in events
    assert (idlerpg.PLUGIN_NAME, "groupchat_presence") in events
    assert (idlerpg.PLUGIN_NAME, "public_groupchat_message") in runtime_events
    groupchat_handler = next(
        handler for _plugin, event, handler in registered if event == "groupchat_message"
    )
    generic_handler = next(
        handler for _plugin, event, handler in registered if event == "message"
    )
    runtime_handler = next(
        handler
        for _plugin, event, handler in runtime_registered
        if event == "public_groupchat_message"
    )
    assert groupchat_handler == generic_handler == runtime_handler


@pytest.mark.asyncio
async def test_login_while_already_online_is_noop(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    monkeypatch.setattr(idlerpg, "ANNOUNCE_LOGIN", True)
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    player = room["players"]["alice@envs.net"]
    player["last_login"] = 123
    player["last_seen"] = 123
    room["events"] = []

    bot.replies.clear()
    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["login"], msg, True)

    assert "already online" in bot.replies[-1][0]
    assert "is now online from nickname" not in "\n".join(text for text, _kwargs in bot.replies)
    assert player["last_login"] == 123
    assert player["last_seen"] == 123
    assert room["events"] == []


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

    invalid_before = room["players"]["alice@envs.net"]["next"]
    bot.replies.clear()
    await idlerpg.idlerpg_command(
        bot, "admin@envs.net", "Admin", ["push", "Alice", "notaduration"], msg, True
    )
    assert room["players"]["alice@envs.net"]["next"] == invalid_before
    assert "Invalid duration" in bot.replies[-1][0]

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
        room["players"][jid] = idlerpg._normalize_player(
            jid,
            {
                "name": f"U{idx}",
                "class": "idler",
                "level": 40,
                "next": 100,
                "last_login": idlerpg._now() - idlerpg.QUEST_MIN_ONLINE_SECONDS,
            },
        )
        JOINED_ROOMS["room@conf"]["nicks"][f"U{idx}"] = {"jid": jid, "affiliation": "member"}
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = data
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])

    messages = []

    await idlerpg._maybe_run_quest(room, "room@conf", messages)
    assert room["quest"]["active"] is True
    assert messages

    state = await idlerpg.get_runtime_state(bot, "room@conf")
    assert state["players"] == 4
    assert state["active_quests"] == 1

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["quest"], msg, True)
    assert "are on a quest" in bot.replies[-1][0]


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
async def test_achievements_command_shows_founder():
    bot = DummyBot()
    msg = DummyMsg()
    await _register_alice(bot, msg)

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["achievements"], msg, True)

    assert "Founder" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_title_command_sets_founder():
    bot = DummyBot()
    msg = DummyMsg()
    await _register_alice(bot, msg)

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["title", "founder"], msg, True)

    assert "Founder" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_profile_command_includes_public_json(tmp_path, monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    monkeypatch.setattr(idlerpg, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg, "EXPORT_PUBLIC_BASE_URL", "https://envs.net/idlerpg")
    await _register_alice(bot, msg)
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    room["players"]["alice@envs.net"]["created_at"] = 1_000_000
    monkeypatch.setattr(idlerpg, "_now", lambda: 1_090_061)

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["profile"], msg, True)

    assert "Profile: Alice" in bot.replies[-1][0]
    assert "Playing since:" in bot.replies[-1][0]
    assert "Playing for: 1 days, 01:01:01" in bot.replies[-1][0]
    assert "Idled online:" in bot.replies[-1][0]
    assert "Profile JSON: https://envs.net/idlerpg/room_at_conf/profiles/Alice.json" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_map_command_includes_public_json(tmp_path, monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    monkeypatch.setattr(idlerpg, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg, "EXPORT_PUBLIC_BASE_URL", "https://envs.net/idlerpg")
    await _register_alice(bot, msg)

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["map"], msg, True)

    assert "IdleRPG map for room@conf" in bot.replies[-1][0]
    assert "Map JSON: https://envs.net/idlerpg/room_at_conf/map.json" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_export_command_writes_public_files(tmp_path, monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    monkeypatch.setattr(idlerpg, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg, "EXPORT_ENABLED", True)
    await _register_alice(bot, msg)

    admin_msg = DummyMsg(resource="Admin")
    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["export"], admin_msg, True)

    assert (tmp_path / "index.json").exists()
    assert (tmp_path / "leaderboard.json").exists()
    profile_payload = (tmp_path / "room_at_conf" / "profiles" / "Alice.json").read_text()
    assert '"played_for"' in profile_payload


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

    admin_only_commands = [
        ["export"],
        ["season", "end"],
        ["delete", "Alice"],
        ["setlevel", "Alice", "1"],
        ["reset", "Alice"],
        ["push", "Alice", "9"],
        ["hof", "clear", "confirm"],
        ["season", "reset"],
        ["season", "extend", "7"],
        ["announce", "top"],
        ["topic", "update"],
    ]
    for command_args in admin_only_commands:
        bot.replies.clear()
        await idlerpg.idlerpg_command(
            bot, "mod@envs.net", "Mod", command_args, mod_msg, True
        )
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
    monkeypatch.setattr(idlerpg, "MAP_STEP_PER_SECOND", 1)
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[-1])

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
    assert (room_dir / "players.json").exists()
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


def test_quest_candidates_require_original_online_time(monkeypatch):
    room_jid = "room@conf"
    now = 50_000
    eligible = idlerpg._normalize_player(
        "eligible@envs.net",
        {"name": "Eligible", "level": idlerpg.QUEST_MIN_LEVEL, "last_login": now - idlerpg.QUEST_MIN_ONLINE_SECONDS},
    )
    too_fresh = idlerpg._normalize_player(
        "fresh@envs.net",
        {"name": "Fresh", "level": idlerpg.QUEST_MIN_LEVEL, "last_login": now - idlerpg.QUEST_MIN_ONLINE_SECONDS + 1},
    )
    too_low = idlerpg._normalize_player(
        "low@envs.net",
        {"name": "Low", "level": idlerpg.QUEST_MIN_LEVEL - 1, "last_login": now - idlerpg.QUEST_MIN_ONLINE_SECONDS},
    )
    JOINED_ROOMS[room_jid] = {
        "nicks": {
            "Eligible": {"jid": "eligible@envs.net"},
            "Fresh": {"jid": "fresh@envs.net"},
            "Low": {"jid": "low@envs.net"},
        }
    }

    assert idlerpg._quest_candidate_is_eligible(room_jid, "eligible@envs.net", eligible, now) is True
    assert idlerpg._quest_candidate_is_eligible(room_jid, "fresh@envs.net", too_fresh, now) is False
    assert idlerpg._quest_candidate_is_eligible(room_jid, "low@envs.net", too_low, now) is False

    fallback = idlerpg._normalize_player(
        "fallback@envs.net",
        {"name": "Fallback", "level": idlerpg.QUEST_MIN_LEVEL, "idled": idlerpg.QUEST_MIN_ONLINE_SECONDS},
    )
    fallback["last_login"] = now + 60
    JOINED_ROOMS[room_jid]["nicks"]["Fallback"] = {"jid": "fallback@envs.net"}
    assert idlerpg._quest_candidate_is_eligible(room_jid, "fallback@envs.net", fallback, now) is True


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
                "idled": idlerpg.QUEST_MIN_ONLINE_SECONDS,
            },
        )
    room["quest"] = {"active": False, "next_at": 0}
    monkeypatch.setattr(idlerpg, "_now", lambda: 1000)
    monkeypatch.setattr(idlerpg, "QUEST_TIME_ENABLED", False)
    monkeypatch.setattr(idlerpg, "QUEST_GRID_ENABLED", True)
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
    assert "quest_hero" not in room["players"][first_jid]["achievements"]
    assert not any(
        event.get("kind") == "quest" and "completed" in event.get("text", "").lower()
        for event in room["events"]
    )
    room["players"][first_jid]["unique_items"] = {"pair of boots": "The Boots of Silent Idling"}
    before = int(room["players"][first_jid]["next"])
    for point in room["quest"]["route"]:
        for jid in room["quest"]["questers"]:
            room["players"][jid]["x"] = point[0]
            room["players"][jid]["y"] = point[1]
        messages.clear()
        await idlerpg._maybe_run_quest(room, room_jid, messages)
    room["quest"]["complete_at"] = 999
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

    assert idlerpg._battle_amount(evil, 100, "win") == 100
    assert idlerpg._battle_amount(good, 100, "loss") == 100
    assert idlerpg._battle_amount(neutral, 100, "win") == 100
    assert idlerpg._battle_amount(unknown, 100, "win") == 100
    assert idlerpg._alignment_battle_factor(good) == 1.10
    assert idlerpg._alignment_battle_factor(evil) == 0.90
    assert idlerpg._alignment_battle_factor(neutral) == 1.0

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
async def test_on_load_registers_message_and_presence_handlers():
    registered = []
    bot = DummyBot()
    bot.bot_plugins = types.SimpleNamespace(
        register_event=lambda *args: registered.append(args)
    )

    await idlerpg.on_load(bot)

    assert [entry[:2] for entry in registered] == [
        (idlerpg.PLUGIN_NAME, "groupchat_message"),
        (idlerpg.PLUGIN_NAME, "message"),
        (idlerpg.PLUGIN_NAME, "groupchat_presence"),
    ]
    assert all(callable(entry[2]) for entry in registered)


@pytest.mark.asyncio
async def test_hof_clear_requires_confirmation_and_admin():
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
    room["players"]["alice@envs.net"]["level"] = 9
    idlerpg._end_season("room@conf", room)
    assert room["hall_of_fame"]

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["hof", "clear"], msg, True)
    assert "Usage" in bot.replies[-1][0]
    assert room["hall_of_fame"]

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["hof", "clear", "confirm"], DummyMsg(resource="Mod"), True)
    assert "Only room owners/admins" in bot.replies[-1][0]
    assert room["hall_of_fame"]

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["hof", "clear", "confirm"], msg, True)
    assert "Hall of Fame cleared" in bot.replies[-1][0]
    assert room["hall_of_fame"] == []


@pytest.mark.asyncio
async def test_season_extend_and_clear_end(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg(resource="Admin")
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        DummyMsg(),
        True,
    )
    data = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]
    room = data["rooms"]["room@conf"]
    room["season"] = {"id": "test-season", "started_at": idlerpg._now() - 10, "ends_at": idlerpg._now() + 10}

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["season", "extend", "1h"], DummyMsg(resource="Mod"), True)
    assert "Only room owners/admins" in bot.replies[-1][0]

    before = int(room["season"]["ends_at"])
    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["season", "extend", "1h"], msg, True)
    assert "extended by 1h" in bot.replies[-1][0]
    assert int(room["season"]["ends_at"]) == before + 3600

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["season", "extend", "nonsense"], msg, True)
    assert "Usage" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["season", "clear-end"], msg, True)
    assert "manual/endless" in bot.replies[-1][0]
    assert int(room["season"]["ends_at"]) == 0

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["season"], msg, True)
    assert "ends in manual" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_season_extend_uses_config_or_manual(monkeypatch):
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
    room["season"] = {"id": "config-season", "started_at": idlerpg._now(), "ends_at": 0}

    monkeypatch.setattr(idlerpg, "SEASON_DURATION_DAYS", 2)
    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["season", "extend"], msg, True)
    assert "extended by 2d" in bot.replies[-1][0]
    assert int(room["season"]["ends_at"]) > idlerpg._now()

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["season", "extend", "manual"], msg, True)
    assert int(room["season"]["ends_at"]) == 0

    monkeypatch.setattr(idlerpg, "SEASON_DURATION_DAYS", 0)
    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["season", "extend"], msg, True)
    assert "manual/endless" in bot.replies[-1][0]
    assert int(room["season"]["ends_at"]) == 0


@pytest.mark.asyncio
async def test_season_hof_clear_confirm_alias_path():
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
    room["hall_of_fame"] = [{"id": "old", "champion": "Alice"}]

    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["season", "hof", "clear", "confirm"], msg, True)
    assert "Hall of Fame cleared" in bot.replies[-1][0]
    assert room["hall_of_fame"] == []


def test_item_damage_swap_top_topic_and_season_gated_rewards(monkeypatch):
    room = idlerpg._blank_room()
    now = 2_000_000_000
    room["season"] = {"id": "s", "started_at": now - 8 * 86400, "ends_at": 0}
    monkeypatch.setattr(idlerpg, "_now", lambda: now)
    alice = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "wizard", "level": 75, "next": 1000, "items": {"weapon": 10}},
    )
    bob = idlerpg._normalize_player(
        "bob@envs.net",
        {"name": "Bob", "class": "fighter", "level": 60, "next": 2000, "items": {"weapon": 30}},
    )
    room["players"] = {"alice@envs.net": alice, "bob@envs.net": bob}
    players = [("alice@envs.net", alice), ("bob@envs.net", bob)]
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])

    messages: list[str] = []
    idlerpg._run_item_damage(players, messages)
    assert alice["items"]["weapon"] == 9
    assert "item_damaged" in alice["achievements"]
    assert any("damaged their weapon" in line for line in messages)

    messages.clear()
    idlerpg._run_item_swap(players, messages)
    assert alice["items"]["weapon"] == 30
    assert bob["items"]["weapon"] == 9
    assert "item_swapped" in alice["achievements"]
    assert any("leaves their old level" in line for line in messages)

    idlerpg._check_level_achievements(alice, room)
    assert "level_reward_50" in alice["achievements"]
    assert "level_reward_75" in alice["achievements"]
    assert idlerpg._format_top_lines(room, limit=2)[0] == "IdleRPG Top 2 Players:"
    assert "#1" in idlerpg._topic_text(room)
    assert idlerpg._topic_text(room, custom_text="CustomText").startswith("CustomText #1")


def test_normalize_player_does_not_bypass_season_achievement_gates(monkeypatch):
    now = 2_000_000_000
    monkeypatch.setattr(idlerpg, "_now", lambda: now)
    room = idlerpg._blank_room()
    room["season"] = {"id": "fresh", "started_at": now, "ends_at": 0}
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": 75, "next": 1000},
    )

    assert "level_50" not in player["achievements"]
    assert "level_75" not in player["achievements"]

    idlerpg._check_level_achievements(player, room)
    assert "level_50" not in player["achievements"]

    room["season"]["started_at"] = now - 8 * 86400
    idlerpg._check_level_achievements(player, room)
    assert "level_50" in player["achievements"]
    assert "level_75" in player["achievements"]


@pytest.mark.asyncio
async def test_login_announcement_and_manual_top_command(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    monkeypatch.setattr(idlerpg, "ANNOUNCE_LOGIN", True)
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "wizard"],
        msg,
        True,
    )
    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["logout"], msg, True)
    bot.replies.clear()
    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["login"], msg, True)
    assert any("is now online from nickname" in text for text, _kwargs in bot.replies)

    admin_msg = DummyMsg(resource="Admin")
    bot.replies.clear()
    await idlerpg.idlerpg_command(bot, "admin@envs.net", "Admin", ["announce", "top"], admin_msg, True)
    top_replies = [text for text, _kwargs in bot.replies if "IdleRPG Top 5 Players" in text]
    assert len(top_replies) == 1
    assert "\n" in top_replies[0]
    assert "announced" in bot.replies[-1][0]

    bot.replies.clear()
    await idlerpg.idlerpg_command(
        bot,
        "admin@envs.net",
        "Admin",
        ["topic", "update", "CustomText"],
        admin_msg,
        True,
    )
    assert "CustomText #1" in bot.replies[-1][0]


def test_achievement_awards_respect_season_gate_on_stat_updates(monkeypatch):
    now = 2_000_000_000
    monkeypatch.setattr(idlerpg, "_now", lambda: now)
    room = idlerpg._blank_room()
    room["season"] = {"id": "fresh", "started_at": now, "ends_at": 0}
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice",
            "class": "sysadmin",
            "level": 75,
            "next": 1000,
            "stats": {"quests_completed": 2},
        },
    )

    idlerpg._inc_stat(player, "quests_completed", 1, room)

    assert player["stats"]["quests_completed"] == 3
    assert "level_10" in player["achievements"]
    assert "level_25" in player["achievements"]
    for gated in {"level_50", "level_reward_50", "level_75", "level_reward_75", "quest_walker"}:
        assert gated not in player["achievements"]

    room["season"]["started_at"] = now - 8 * 86400
    idlerpg._check_level_achievements(player, room)

    for gated in {"level_50", "level_reward_50", "level_75", "level_reward_75", "quest_walker"}:
        assert gated in player["achievements"]


@pytest.mark.asyncio
async def test_level_reward_badges_do_not_bypass_season_gate_on_tick(monkeypatch):
    now = 2_000_000_000
    monkeypatch.setattr(idlerpg, "_now", lambda: now)
    monkeypatch.setattr(idlerpg.random, "random", lambda: 1.0)
    bot = DummyBot()
    room = idlerpg._blank_room()
    room["season"] = {"id": "fresh", "started_at": now, "ends_at": 0}
    room["last_tick"] = now - max(1, idlerpg.TICK_SECONDS)
    room["players"]["alice@envs.net"] = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice",
            "class": "sysadmin",
            "level": 49,
            "next": 1,
            "logged_out": False,
        },
    )
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {"rooms": {"room@conf": room}}

    await idlerpg._tick_room(bot, "room@conf", announce=True)

    player = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]["players"]["alice@envs.net"]
    assert player["level"] >= 50
    assert "level_reward_50" not in player["achievements"]
    assert not any("reward badge" in text for text, _kwargs in bot.replies)


@pytest.mark.asyncio
async def test_manual_duel_nearby_online_players_and_cooldown(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    JOINED_ROOMS["room@conf"]["nicks"]["Bob"] = {
        "jid": "bob@envs.net",
        "affiliation": "member",
    }

    await _register_alice(bot, msg)
    await idlerpg._handle_register(
        bot,
        "bob@envs.net",
        ["register", "Bob", "wizard"],
        DummyMsg(resource="Bob"),
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    alice = room["players"]["alice@envs.net"]
    bob = room["players"]["bob@envs.net"]
    alice.update({"x": 10, "y": 10, "level": 10, "next": 1000})
    bob.update({"x": 16, "y": 18, "level": 10, "next": 1000})
    monkeypatch.setattr(idlerpg, "MANUAL_DUEL_MAX_DISTANCE", 10)
    monkeypatch.setattr(idlerpg, "MANUAL_DUEL_COOLDOWN_SECONDS", 3600)
    rolls = iter([999, 0])
    monkeypatch.setattr(idlerpg.random, "randint", lambda _start, _stop: next(rolls))
    monkeypatch.setattr(idlerpg.random, "random", lambda: 1.0)

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["duel", "@~Bob"], msg, True)

    assert "Alice" in bot.replies[-1][0]
    assert "challenged Bob" in bot.replies[-1][0]
    assert "to a duel" in bot.replies[-1][0]
    assert alice["next"] < 1000
    assert alice["last_manual_duel_at"] == bob["last_manual_duel_at"]
    assert any(event.get("kind") == "duel" for event in room["events"])

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["challenge", "Bob"], msg, True)
    assert "can duel again" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_manual_duel_rejects_far_offline_and_self(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    JOINED_ROOMS["room@conf"]["nicks"]["Bob"] = {
        "jid": "bob@envs.net",
        "affiliation": "member",
    }
    await _register_alice(bot, msg)
    await idlerpg._handle_register(
        bot,
        "bob@envs.net",
        ["register", "Bob", "wizard"],
        DummyMsg(resource="Bob"),
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    room["players"]["alice@envs.net"].update({"x": 0, "y": 0})
    room["players"]["bob@envs.net"].update({"x": 500, "y": 500})
    monkeypatch.setattr(idlerpg, "MANUAL_DUEL_MAX_DISTANCE", 10)

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["duel", "Alice"], msg, True)
    assert "cannot duel yourself" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["duel", "Bob"], msg, True)
    assert "too far away" in bot.replies[-1][0]

    room["players"]["bob@envs.net"].update({"x": 1, "y": 1, "logged_out": True})
    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["duel", "Bob"], msg, True)
    assert "not online" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_message_penalty_scans_players_when_name_index_is_stale():
    bot = DummyBot()
    msg = DummyMsg(resource="skx")
    await idlerpg._handle_register(
        bot,
        "skx@example.org",
        ["register", "skx", "test"],
        msg,
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    player = room["players"]["skx@example.org"]
    room["name_index"] = {"someone-else": "other@example.org"}
    JOINED_ROOMS["room@conf"]["nicks"]["skx"] = {"jid": "room@conf/skx", "affiliation": "member"}

    before = player["next"]
    await idlerpg.on_message(bot, DummyMsg(body="test2", resource="skx", stanza_id="stale-index"))

    assert player["next"] > before
    assert player["penalties"]["message"] > 0
    assert player["stats"]["messages"] == 1
    assert any("is penalized" in text for text, _kwargs in bot.replies)


@pytest.mark.asyncio
async def test_message_penalty_dedupe_only_after_player_is_found():
    bot = DummyBot()
    unknown = DummyMsg(body="hello", resource="stranger", stanza_id="same-id")
    await idlerpg.on_message(bot, unknown)

    msg = DummyMsg(resource="stranger")
    await idlerpg._handle_register(
        bot,
        "stranger@example.org",
        ["register", "stranger", "test"],
        msg,
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    player = room["players"]["stranger@example.org"]
    before = player["next"]
    await idlerpg.on_message(bot, DummyMsg(body="hello", resource="stranger", stanza_id="same-id"))

    assert player["next"] > before
    assert player["stats"]["messages"] == 1
