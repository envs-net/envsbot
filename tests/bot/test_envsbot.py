import pytest
import asyncio
import slixmpp
import types
from unittest.mock import patch, MagicMock, AsyncMock

import envsbot
import bot.lifecycle as lifecycle


def noop(self):
    pass


slixmpp.ClientXMPP.__del__ = noop


class DummyFrom:
    def __init__(self, bare, resource):
        self.bare = bare
        self.resource = resource


class ControlledBot(envsbot.Bot):
    async def get_user_role(self, jid, room=None):
        return envsbot.Role.USER

    def reply(self, msg, text, *args, **kwargs):
        print(f"[TEST DEBUG REPLY CALLED] text={text!r}")
        if not hasattr(self, "_replies"):
            self._replies = []
        self._replies.append((msg, text, args, kwargs))


def _check_no_mock_jid(val, path="jid"):
    import unittest.mock as _mock
    if isinstance(val, dict):
        for k, v in val.items():
            _check_no_mock_jid(v, path+f".{k}")
    elif isinstance(val, list) or isinstance(val, tuple):
        for idx, v in enumerate(val):
            _check_no_mock_jid(v, path+f"[{idx}]")
    elif isinstance(val, _mock.MagicMock):
        raise RuntimeError(f"MagicMock detected at {path}: {val}")


@pytest.fixture
def bot(monkeypatch):
    # Patch direct dependencies
    monkeypatch.setattr(envsbot, "PresenceManager", MagicMock())
    monkeypatch.setattr(envsbot, "PluginManager", MagicMock())
    monkeypatch.setattr(envsbot, "TokenBucketRateLimiter", MagicMock())
    monkeypatch.setattr(envsbot, "DatabaseManager", MagicMock())
    monkeypatch.setattr(envsbot, "config", {
                        "jid": "jid", "password": "pw", "prefix": ","})
    monkeypatch.setattr(envsbot, "setup_logging", lambda: None)

    with patch.object(envsbot.slixmpp.ClientXMPP,
                      "__init__", lambda self, jid, pw: None), \
            patch.object(envsbot.slixmpp.ClientXMPP,
                         "register_plugin", lambda self, *a, **k: None), \
            patch.object(envsbot.slixmpp.ClientXMPP,
                         "add_event_handler", lambda self, *a, **k: None), \
            patch.object(envsbot.slixmpp.ClientXMPP,
                         "make_message", lambda self, *a, **k:
                         MagicMock(send=MagicMock(return_value=None))):
        b = ControlledBot()
    b.default_ns = "jabber:client"
    b.Message = MagicMock()
    b._XMLStream__event_handlers = {}

    class FakeMUCPlugin:
        def get_jid_property(self, *a, **k):
            return "user@host"

    b.plugin = {"xep_0045": FakeMUCPlugin()}

    class FakeUsers:
        async def get(self, jid):
            return {"role": 80, "jid": "user@host"}

        async def flush_all(self):
            pass

    class FakeDB:
        def __init__(self):
            self.users = FakeUsers()

    b.db = FakeDB()
    b.presence = MagicMock()
    b.presence.joined_rooms = {}
    b.bot_plugins = MagicMock()
    b.rate_limiter = MagicMock()
    b.rate_limiter.allow = AsyncMock(return_value=(True, 0))
    b.rate_limiter.notify_allowed = MagicMock(return_value=False)
    b.make_message = MagicMock(return_value=MagicMock(
        send=MagicMock(return_value=None)))

    _check_no_mock_jid(b.plugin, "plugin")
    _check_no_mock_jid(b.db, "db")
    return b


@pytest.mark.asyncio
async def test_safe_send_message_sync_and_async(bot):
    msg = MagicMock()
    msg.send.return_value = None
    await bot._safe_send_message(msg)
    msg.send.assert_called_once()

    msg = MagicMock()
    coro = AsyncMock()
    msg.send.return_value = coro()
    await bot._safe_send_message(msg)
    assert msg.send.call_count >= 1

    msg = MagicMock()

    def raise_exc():
        raise Exception("fail")
    msg.send.side_effect = raise_exc
    await bot._safe_send_message(msg)


@pytest.mark.asyncio
async def test_reply_groupchat_and_private(monkeypatch, bot):
    monkeypatch.setattr(bot, "_reply_send_wrapper", AsyncMock())
    msg_obj = MagicMock()
    bot.make_message.return_value = msg_obj

    msg = {
        "type": "groupchat",
        "from": DummyFrom("room1", "tester"),
        "get": lambda k, d=None: "tester" if k == "mucnick" else None
    }
    bot.reply(msg, "hi", mention=True, ephemeral=True)
    await asyncio.sleep(0)
    assert hasattr(bot, "_replies") and bot._replies

    bot._replies = []
    msg = {
        "type": "chat",
        "from": DummyFrom("user@host", "sender"),
        "get": lambda k, d=None: None
    }
    bot.reply(msg, "hi")
    await asyncio.sleep(0)
    assert bot._replies


@pytest.mark.asyncio
async def test_handle_command_no_body_or_prefix(bot):
    m = {
        "type": "chat",
        "from": DummyFrom("room@conf", "sender"),
        "get": lambda k, d=None: None
    }
    for body in [None, "foo"]:
        await bot.handle_command(body, "jid@host", None, m, False)
    await bot.handle_command(",", "jid@host", None, m, False)


@pytest.mark.asyncio
async def test_handle_command_unresolved_or_noperm(bot):
    m = {
        "type": "groupchat",
        "from": DummyFrom("room@conf", "sender"),
        "get": lambda k, d=None: None
    }
    with patch("envsbot.resolve_command", return_value=(None, [])):
        replies = []
        bot.reply = lambda msg, text, * \
            a, **k: replies.append((msg, text, a, k))
        await bot.handle_command(",unknown", "user@host", None, m, False)
        assert replies == []

    def fakeDef():
        pass

    class FakeCmd:
        name = "test"
        handler = fakeDef
        role = 80
    with patch("envsbot.resolve_command", return_value=(FakeCmd, [])), \
            patch("envsbot.check_permission", return_value=False):
        replies = []
        bot.reply = lambda msg, text, * \
            a, **k: replies.append((msg, text, a, k))
        await bot.handle_command(",test", "user@host", None, m, False)
        print("Replies:", replies)
        found = any(
            "🔴 You are not allowed to use this command."
            in r[1] for r in replies)
        assert found


@pytest.mark.asyncio
async def test_handle_command_moderator_check(bot):
    m = {
        "type": "groupchat",
        "from": DummyFrom("room@conf", "sender"),
        "get": lambda k, d=None: "nick"
    }

    class FakeCmd:
        name = "testcmd"
        handler = AsyncMock()
        role = envsbot.Role.MODERATOR
    with patch("envsbot.resolve_command", return_value=(FakeCmd, [])), \
            patch("envsbot.check_permission", return_value=True):
        bot._replies = []
        await bot.handle_command(",testcmd", "user@host", "nick", m, True)
        found = any(
            "🔴 Use this command in MUC Direct Message only."
            in r[1] for r in bot._replies)
        assert found


@pytest.mark.asyncio
async def test_admin_command_executes_in_direct_message(bot):
    msg = {
        "type": "chat",
        "from": DummyFrom("admin@example.org", "desktop"),
        "get": lambda k, d=None: None,
    }
    handler = AsyncMock()

    class FakeCmd:
        name = "admincmd"
        role = envsbot.Role.ADMIN

    FakeCmd.handler = handler

    role_mock = AsyncMock(return_value=envsbot.Role.ADMIN)
    with patch("envsbot.resolve_command", return_value=(FakeCmd, [])), \
            patch("envsbot.check_permission", return_value=True), \
            patch.object(bot, "get_user_role", role_mock):
        await bot.handle_command(",admincmd", "admin@example.org/desktop",
                                 None, msg, False)

    handler.assert_awaited_once()
    assert handler.await_args.args[1] == "admin@example.org"
    role_mock.assert_awaited_once_with("admin@example.org", None)


@pytest.mark.asyncio
async def test_admin_command_executes_in_muc_private_message(bot):
    bot.presence.joined_rooms = {"room@conf": "Bot"}
    msg = {
        "type": "chat",
        "from": DummyFrom("room@conf", "alice"),
        "get": lambda k, d=None: None,
    }
    handler = AsyncMock()

    class FakeCmd:
        name = "admincmd"
        role = envsbot.Role.ADMIN

    FakeCmd.handler = handler

    role_mock = AsyncMock(return_value=envsbot.Role.ADMIN)
    with patch("envsbot.resolve_command", return_value=(FakeCmd, [])), \
            patch("envsbot.check_permission", return_value=True), \
            patch.object(bot, "get_user_role", role_mock):
        await bot.handle_command(",admincmd", "room@conf/alice", None, msg, False)

    handler.assert_awaited_once()
    assert handler.await_args.args[1] == "user@host"
    role_mock.assert_awaited_once_with("user@host", "room@conf")


@pytest.mark.asyncio
async def test_handle_command_execution(bot):
    m = {
        "type": "chat",
        "from": DummyFrom("room@conf", "sender"),
        "get": lambda k, d=None: None
    }
    handled = {"ok": False}

    class C:
        name = "mycmd"
        handler = AsyncMock(side_effect=lambda *a, **
                            k: handled.update(ok=True))
        role = 80
    with patch("envsbot.resolve_command", return_value=(C, [])), \
            patch("envsbot.check_permission", return_value=True):
        await bot.handle_command(",mycmd foo", "user@host", None, m, False)
        assert handled["ok"]

    class F:
        name = "badcmd"
        handler = AsyncMock(side_effect=Exception("fail"))
        role = 80
    with patch("envsbot.resolve_command", return_value=(F, [])), \
            patch("envsbot.check_permission", return_value=True), \
            patch.object(bot, "get_user_role",
                         AsyncMock(return_value=envsbot.Role.OWNER)):
        bot._replies = []
        await bot.handle_command(",badcmd", "user@host", None, m, False)
        # No assertion, just for coverage


@pytest.mark.asyncio
async def test_send_restart_notification_room_and_private(bot, monkeypatch,
                                                          tmp_path):
    import json
    notif_path = str(tmp_path / "restart_notification.json")
    fallback_path = str(tmp_path / "data" / "envsbot_restart_notification.json")
    monkeypatch.setitem(
        envsbot.config,
        "restart_notification_file",
        notif_path,
    )
    monkeypatch.setattr(
        lifecycle,
        "_restart_notification_paths",
        lambda config_obj: [notif_path, fallback_path],
    )
    notif = {
        "room": "room@conf",
        "nick": "yo",
        "sender": "jid@server",
        "is_room": True,
    }
    with open(notif_path, "w") as f:
        json.dump(notif, f)
    sent = []

    async def fake_send(msg):
        sent.append(msg)
    bot._safe_send_message = fake_send
    await bot._send_restart_notification()
    assert sent, "Should send a message"
    assert not (tmp_path / "restart_notification.json").exists()

    notif2 = dict(notif)
    notif2["is_room"] = False
    with open(notif_path, "w") as f:
        json.dump(notif2, f)
    sent.clear()
    await bot._send_restart_notification()
    assert sent, "Should send a private message"


def test_restart_notification_paths_include_persistent_fallback(tmp_path):
    configured = str(tmp_path / "custom.json")
    paths = lifecycle._restart_notification_paths({"restart_notification_file": configured})
    assert paths[0] == configured
    assert "data/envsbot_restart_notification.json" in paths
    assert "/tmp/envsbot_restart_notification.json" in paths


def test_get_latest_git_tag(monkeypatch):
    monkeypatch.setattr(envsbot.subprocess, "check_output",
                        lambda *a, **k: b"v1.2.3\n")
    assert envsbot.get_latest_git_tag() == "v1.2.3"
    def raise_cpe(
        *a, **k): raise envsbot.subprocess.CalledProcessError(1, "git")
    monkeypatch.setattr(envsbot.subprocess, "check_output", raise_cpe)
    assert envsbot.get_latest_git_tag() is None


def test_main_copy_behavior(monkeypatch, tmp_path):
    source = tmp_path / "init_chat_slang.csv"
    target = tmp_path / "chat_slang.csv"
    source.write_text("hello, world\n")
    called = {}

    # Patch os.path.exists so envsbot logic matches file expectations
    monkeypatch.setattr(envsbot.os.path, "exists", lambda path: str(
        path).endswith("init_chat_slang.csv"))
    # Patch shutil.copyfile to mark when called and simulate a copy
    monkeypatch.setattr(envsbot.shutil, "copyfile", lambda s,
                        t: target.write_text(source.read_text()))
    # Patch logger methods to record messages
    monkeypatch.setattr(envsbot.log, "info", lambda *a, **
                        k: called.setdefault("info", True))
    monkeypatch.setattr(envsbot.log, "warning", lambda *a,
                        **k: called.setdefault("warning", True))
    monkeypatch.setattr(envsbot.log, "error", lambda *a, **
                        k: called.setdefault("error", True))

    # Simulate the file copy block as in envsbot.py's __main__ logic
    if (envsbot.os.path.exists("init_chat_slang.csv")
            and not envsbot.os.path.exists("chat_slang.csv")):
        try:
            envsbot.shutil.copyfile("init_chat_slang.csv", "chat_slang.csv")
            envsbot.log.info(
                "[INIT] ✅ Copied init_chat_slang.csv to chat_slang.csv")
        except Exception as e:
            envsbot.log.error(
                f"[INIT] 🔴 Failed to copy init_chat_slang.csv to"
                f" chat_slang.csv: {e}")
    elif not envsbot.os.path.exists("init_chat_slang.csv"):
        envsbot.log.warning(
            "[INIT] 🔴 Source file init_chat_slang.csv not found."
            " Skipping copy.")
    else:
        envsbot.log.info(
            "[INIT] ✅ Target file chat_slang.csv already exists."
            " Skipping copy.")

    assert called.get("info") or called.get("warning") or called.get("error")


@pytest.mark.asyncio
async def test_startup_backup_created_once(monkeypatch, bot):
    from pathlib import Path
    import utils.audit as audit_mod
    import utils.backups as backups_mod

    create_backup = AsyncMock(return_value=Path("envsbot-backup-startup.zip"))
    audit_event = AsyncMock()
    monkeypatch.setattr(backups_mod, "create_backup", create_backup)
    monkeypatch.setattr(audit_mod, "audit_event", audit_event)
    monkeypatch.setitem(envsbot.config, "backup_on_start", True)

    await bot._create_startup_backup()
    await bot._create_startup_backup()

    create_backup.assert_awaited_once_with(bot, reason="startup")
    audit_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_startup_backup_can_be_disabled(monkeypatch, bot):
    import utils.backups as backups_mod

    create_backup = AsyncMock()
    monkeypatch.setattr(backups_mod, "create_backup", create_backup)
    monkeypatch.setitem(envsbot.config, "backup_on_start", False)

    await bot._create_startup_backup()

    create_backup.assert_not_called()


def test_bot_init_wires_core_runtime_objects(monkeypatch):
    registered_plugins = []
    event_handlers = []
    client_init_args = {}
    limiter_kwargs = {}

    class FakePresenceManager:
        def __init__(self, owner):
            self.owner = owner

    class FakeTaskSupervisor:
        pass

    class FakeLimiter:
        def __init__(self, **kwargs):
            limiter_kwargs.update(kwargs)

    class FakeDB:
        def __init__(self, path):
            self.path = path

    class FakePluginManager:
        def __init__(self, owner):
            self.owner = owner

    def fake_client_init(self, jid, password):
        client_init_args["jid"] = jid
        client_init_args["password"] = password

    def fake_register_plugin(self, plugin_name, *args, **kwargs):
        registered_plugins.append(plugin_name)

    def fake_add_event_handler(self, event_name, handler):
        event_handlers.append((event_name, handler.__name__))

    monkeypatch.setattr(envsbot, "PresenceManager", FakePresenceManager)
    monkeypatch.setattr(envsbot, "TaskSupervisor", FakeTaskSupervisor)
    monkeypatch.setattr(envsbot, "TokenBucketRateLimiter", FakeLimiter)
    monkeypatch.setattr(envsbot, "DatabaseManager", FakeDB)
    monkeypatch.setattr(envsbot, "PluginManager", FakePluginManager)
    monkeypatch.setattr(envsbot, "config", {
        "jid": "bot@example.org",
        "password": "secret",
        "resource": "service",
        "nick": "EnvBot",
        "prefix": "!",
        "db": "envsbot.sqlite3",
    })
    monkeypatch.setattr(envsbot.slixmpp.ClientXMPP, "__init__", fake_client_init)
    monkeypatch.setattr(envsbot.slixmpp.ClientXMPP, "register_plugin", fake_register_plugin)
    monkeypatch.setattr(envsbot.slixmpp.ClientXMPP, "add_event_handler", fake_add_event_handler)

    bot = envsbot.Bot()

    assert client_init_args == {"jid": "bot@example.org/service", "password": "secret"}
    assert bot.nick == "EnvBot"
    assert bot.prefix == "!"
    assert bot.admins == []
    assert bot.version == envsbot.__version__
    assert bot.last_version_check_result is None
    assert bot.last_update_notified_version is None
    assert bot.connection_start_time is None
    assert bot._startup_backup_done is False
    assert bot.db.path == "envsbot.sqlite3"
    assert bot.presence.owner is bot
    assert bot.bot_plugins.owner is bot
    assert limiter_kwargs == {
        "capacity": 4,
        "refill_amount": 1,
        "refill_interval": 0.5,
        "deny_window": 10.0,
        "deny_threshold": 6,
        "base_block_seconds": 30.0,
        "backoff_multiplier": 2.0,
        "max_block_seconds": 3600.0,
        "notify_cooldown": 10.0,
    }
    assert registered_plugins == [
        "xep_0012", "xep_0030", "xep_0045", "xep_0054",
        "xep_0084", "xep_0092", "xep_0153", "xep_0163",
        "xep_0199", "xep_0249", "xep_0359", "xep_0461", "xep_0511",
    ]
    assert event_handlers == [
        ("session_start", "on_start"),
        ("groupchat_message", "on_muc_message"),
        ("message", "on_private_message"),
    ]


def test_build_reply_message_formats_groupchat_private_and_hints(bot):
    group_msg_obj = MagicMock()
    bot.make_message.return_value = group_msg_obj
    group_msg = {
        "type": "groupchat",
        "from": DummyFrom("room@conference.example.org", "alice"),
        "body": "!cmd",
        "id": "fallback-thread",
        "get": lambda key, default=None: {
            "type": "groupchat",
            "mucnick": "Alice",
            "id": "fallback-thread",
        }.get(key, default),
    }

    message, body = bot._build_reply_message(
        group_msg,
        ["line one", "line two"],
        mention=True,
        thread=True,
        ephemeral=True,
        no_store=None,
    )

    assert message is group_msg_obj
    assert body == "alice: line one\nline two"
    bot.make_message.assert_called_with(
        mto="room@conference.example.org",
        mbody="alice: line one\nline two",
        mtype="groupchat",
    )
    group_msg_obj.__setitem__.assert_called_with("thread", "fallback-thread")
    group_msg_obj.append.assert_called_once()

    private_msg_obj = MagicMock()
    bot.make_message.return_value = private_msg_obj
    private_msg = {
        "type": "chat",
        "from": "bob@example.org/resource",
        "thread": "thread-1",
        "get": lambda key, default=None: {
            "type": "chat",
            "thread": "thread-1",
        }.get(key, default),
    }

    message, body = bot._build_reply_message(
        private_msg,
        "hello",
        mention=True,
        thread=True,
        ephemeral=False,
        no_store=False,
    )

    assert message is private_msg_obj
    assert body == "hello"
    bot.make_message.assert_called_with(
        mto="bob@example.org/resource",
        mbody="hello",
        mtype="chat",
    )
    private_msg_obj.__setitem__.assert_called_with("thread", "thread-1")
    private_msg_obj.append.assert_not_called()


@pytest.mark.asyncio
async def test_muc_and_private_message_handlers_route_expected_messages(bot):
    bot.handle_command = AsyncMock()
    bot.bot_plugins.dispatch_runtime_event = AsyncMock()
    bot.presence.joined_rooms = {"room@conference.example.org": "EnvBot"}

    own_msg = {
        "type": "groupchat",
        "body": ",help",
        "from": DummyFrom("room@conference.example.org", "EnvBot"),
        "mucnick": "EnvBot",
        "get": lambda key, default=None: "EnvBot" if key == "mucnick" else default,
    }
    await bot.on_muc_message(own_msg)
    bot.handle_command.assert_not_called()
    bot.bot_plugins.dispatch_runtime_event.assert_not_called()

    room_msg = {
        "type": "groupchat",
        "body": ",help",
        "from": DummyFrom("room@conference.example.org", "alice"),
        "mucnick": "Alice",
        "get": lambda key, default=None: "Alice" if key == "mucnick" else default,
    }
    await bot.on_muc_message(room_msg)
    bot.bot_plugins.dispatch_runtime_event.assert_awaited_once_with(
        "public_groupchat_message", room_msg
    )
    bot.handle_command.assert_awaited_with(
        ",help", room_msg["from"], "Alice", room_msg, True
    )

    bot.handle_command.reset_mock()
    private_msg = {
        "type": "chat",
        "body": ",status",
        "from": DummyFrom("alice@example.org", "desktop"),
        "get": lambda key, default=None: default,
    }
    await bot.on_private_message(private_msg)
    bot.handle_command.assert_awaited_with(
        ",status", private_msg["from"], None, private_msg, False
    )

    bot.handle_command.reset_mock()
    await bot.on_private_message({"type": "headline", "get": lambda key, default=None: default})
    bot.handle_command.assert_not_called()

    bot.handle_command.reset_mock()
    bot.message_cache.add_message = AsyncMock(side_effect=RuntimeError("cache failed"))
    await bot.on_private_message(private_msg)
    bot.handle_command.assert_awaited_with(
        ",status", private_msg["from"], None, private_msg, False
    )


@pytest.mark.asyncio
async def test_room_role_from_presence_elevates_only_room_admins(monkeypatch, bot):
    import bot.room_state as rooms_mod

    monkeypatch.setattr(rooms_mod, "JOINED_ROOMS", {
        "room@conf": {
            "nicks": {
                "alice": {"jid": "alice@example.org", "affiliation": "admin"},
                "bob": {"jid": "bob@example.org", "affiliation": "member"},
                "broken": object(),
            }
        }
    })

    assert await bot._get_room_role_from_presence(
        "alice@example.org", "room@conf", envsbot.Role.USER
    ) == envsbot.Role.MODERATOR
    assert await bot._get_room_role_from_presence(
        "bob@example.org", "room@conf", envsbot.Role.USER
    ) == envsbot.Role.USER
    assert await bot._get_room_role_from_presence(
        "alice@example.org", None, envsbot.Role.USER
    ) == envsbot.Role.USER
    assert await bot._get_room_role_from_presence(
        "alice@example.org", "missing@conf", envsbot.Role.USER
    ) == envsbot.Role.USER


@pytest.mark.asyncio
async def test_audit_writes_when_available_and_ignores_missing_or_failed(bot):
    append = AsyncMock()
    bot.db = types.SimpleNamespace(audit=types.SimpleNamespace(append=append))

    await bot.audit("event", actor=123, target="target", details={"x": 1})
    append.assert_awaited_once_with(
        "event",
        actor="123",
        target="target",
        details={"x": 1},
    )

    bot.db = types.SimpleNamespace(audit=None)
    await bot.audit("ignored")

    append = AsyncMock(side_effect=RuntimeError("boom"))
    bot.db = types.SimpleNamespace(audit=types.SimpleNamespace(append=append))
    await bot.audit("broken")
    append.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_sender_jid_direct_and_muc_private(bot):
    bot.presence.joined_rooms = {"room@conference.example.org": "EnvBot"}
    direct_msg = {
        "type": "chat",
        "from": DummyFrom("alice@example.org", "desktop"),
        "get": lambda key, default=None: "chat" if key == "type" else default,
    }
    assert bot._resolve_sender_jid(direct_msg, "alice@example.org/desktop", None) == (
        "alice@example.org",
        None,
    )

    muc_pm_msg = {
        "type": "chat",
        "from": DummyFrom("room@conference.example.org", "alice"),
        "get": lambda key, default=None: "chat" if key == "type" else default,
    }
    assert bot._is_muc_private_message(muc_pm_msg) is True
    assert bot._resolve_sender_jid(muc_pm_msg, "room@conference.example.org/alice", None) == (
        "user@host",
        "room@conference.example.org",
    )


def test_real_reply_schedules_send_and_records_test_reply(monkeypatch, bot):
    message = MagicMock()
    build = MagicMock(return_value=(message, "body"))
    monkeypatch.setattr(bot, "_build_reply_message", build)
    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return MagicMock()

    monkeypatch.setattr(envsbot.asyncio, "create_task", fake_create_task)
    msg = types.SimpleNamespace(replies=[])

    envsbot.Bot.reply(
        bot,
        msg,
        ["hello", "world"],
        mention=False,
        thread=False,
        rate_limit=False,
        ephemeral=True,
        no_store=True,
    )

    build.assert_called_once_with(msg, ["hello", "world"], False, False, True, True)
    assert scheduled
    assert msg.replies == ["hello\nworld"]


def test_real_reply_logs_creation_errors(monkeypatch, bot):
    monkeypatch.setattr(bot, "_build_reply_message", MagicMock(side_effect=RuntimeError("boom")))
    logged = []
    monkeypatch.setattr(envsbot.log, "exception", lambda *args, **kwargs: logged.append(args))
    group_msg = {"type": "groupchat", "get": lambda key, default=None: "groupchat" if key == "type" else default}
    private_msg = {"type": "chat", "get": lambda key, default=None: "chat" if key == "type" else default}

    envsbot.Bot.reply(bot, group_msg, "x")
    envsbot.Bot.reply(bot, private_msg, "x")

    assert "groupchat reply" in logged[0][0]
    assert "private reply" in logged[1][0]


def test_build_client_jid_handles_optional_resource():
    assert envsbot._build_client_jid(
        "bot@example.org", None
    ) == "bot@example.org"
    assert envsbot._build_client_jid(
        "bot@example.org", "service"
    ) == "bot@example.org/service"
    assert envsbot._build_client_jid(
        "bot@example.org/old", "service"
    ) == "bot@example.org/service"


def test_get_configured_resource_strips_empty_values(monkeypatch):
    monkeypatch.setattr(envsbot, "config", {"resource": "  service  "})
    assert envsbot._get_configured_resource() == "service"

    monkeypatch.setattr(envsbot, "config", {"resource": "  "})
    assert envsbot._get_configured_resource() is None


def test_connect_kwargs_supports_host_port_direct_tls(monkeypatch):
    class FakeXMPP:
        def connect(
            self,
            host=None,
            port=None,
            use_ssl=False,
            force_starttls=True,
        ):
            return True

    monkeypatch.setattr(envsbot, "config", {
        "jid": "bot@example.org",
        "host": "xmpp.example.org",
        "port": 5223,
        "direct_tls": True,
    })

    assert envsbot._connect_kwargs(FakeXMPP()) == {
        "host": "xmpp.example.org",
        "port": 5223,
        "use_ssl": True,
        "force_starttls": False,
    }


def test_connect_kwargs_uses_configured_jid_domain_and_starttls(monkeypatch):
    class FakeXMPP:
        def connect(self, host=None, port=None, use_ssl=False):
            return True

    monkeypatch.setattr(envsbot, "config", {
        "jid": "bot@example.org/service",
        "host": None,
        "port": 5222,
        "direct_tls": False,
    })

    assert envsbot._connect_kwargs(FakeXMPP()) == {
        "host": "example.org",
        "port": 5222,
        "use_ssl": False,
    }


def test_connect_kwargs_uses_address_only_when_supported(monkeypatch):
    class FakeXMPP:
        def connect(self, address=None, use_ssl=False, force_starttls=True):
            return True

    monkeypatch.setattr(envsbot, "config", {
        "jid": "bot@example.org",
        "host": None,
        "port": 5223,
        "direct_tls": True,
    })

    assert envsbot._connect_kwargs(FakeXMPP()) == {
        "address": ("example.org", 5223),
        "use_ssl": True,
        "force_starttls": False,
    }


@pytest.mark.asyncio
async def test_connect_xmpp_awaits_async_connect(monkeypatch):
    calls = []

    class FakeXMPP:
        async def connect(self, host=None, port=None, use_ssl=False):
            calls.append({"host": host, "port": port, "use_ssl": use_ssl})
            return "connected"

    monkeypatch.setattr(envsbot, "config", {
        "jid": "bot@example.org",
        "host": "xmpp.example.org",
        "port": 5222,
        "direct_tls": False,
    })

    assert await envsbot.connect_xmpp(FakeXMPP()) == "connected"
    assert calls == [{"host": "xmpp.example.org", "port": 5222, "use_ssl": False}]


def test_boundjid_domain_and_configured_domain_edges(monkeypatch):
    assert envsbot._boundjid_domain(types.SimpleNamespace(boundjid=None)) is None
    assert envsbot._boundjid_domain(types.SimpleNamespace(boundjid=types.SimpleNamespace(domain=" xmpp.example.org "))) == "xmpp.example.org"
    assert envsbot._boundjid_domain(types.SimpleNamespace(boundjid=types.SimpleNamespace(host=" host.example.org "))) == "host.example.org"
    assert envsbot._boundjid_domain(types.SimpleNamespace(boundjid=types.SimpleNamespace(domain=" ", host=""))) is None

    monkeypatch.setattr(envsbot, "config", {"jid": "invalid"})
    assert envsbot._configured_jid_domain() is None
    monkeypatch.setattr(envsbot, "config", {"jid": "bot@example.org/resource"})
    assert envsbot._configured_jid_domain() == "example.org"


def test_connect_kwargs_falls_back_to_boundjid_and_uninspectable_signature(monkeypatch):
    class FakeXMPP:
        boundjid = types.SimpleNamespace(domain="bound.example.org")

        def connect(self, host=None, port=None):
            return True

    monkeypatch.setattr(envsbot, "config", {"jid": "invalid", "host": None, "port": 5222, "direct_tls": False})
    assert envsbot._connect_kwargs(FakeXMPP()) == {"host": "bound.example.org", "port": 5222}

    assert envsbot._connect_signature_parameters(object()) == {}


@pytest.mark.asyncio
async def test_on_start_runs_startup_sequence(monkeypatch, bot):
    features = []
    broadcasts = []
    calls = []

    monkeypatch.setattr(envsbot.Bot, "__getitem__", lambda self, key: types.SimpleNamespace(add_feature=lambda feature: features.append((key, feature))), raising=False)
    bot.presence = types.SimpleNamespace(broadcast=lambda: broadcasts.append("broadcast"))
    bot.get_roster = AsyncMock(side_effect=lambda: calls.append("roster"))
    cache_store = object()
    bot.db = types.SimpleNamespace(
        connect=AsyncMock(side_effect=lambda: calls.append("db")),
        message_cache=cache_store,
    )
    bot.message_cache = types.SimpleNamespace(
        start=AsyncMock(side_effect=lambda store: calls.append(
            "cache" if store is cache_store else "wrong-cache-store"
        )),
    )
    bot.bot_plugins = types.SimpleNamespace(
        load_all=AsyncMock(side_effect=lambda: calls.append("load_all")),
        call_on_ready=AsyncMock(side_effect=lambda: calls.append("ready")),
    )
    bot._create_startup_backup = AsyncMock(side_effect=lambda: calls.append("backup"))
    bot._send_restart_notification = AsyncMock(side_effect=lambda: calls.append("restart"))
    bot.roster = types.SimpleNamespace(auto_subscribe=False)

    await envsbot.Bot.on_start(bot, object())

    assert bot.connection_start_time is not None
    assert features == [("xep_0030", "http://jabber.org/protocol/muc#user")]
    assert broadcasts == ["broadcast", "broadcast"]
    assert calls == ["roster", "db", "cache", "load_all", "ready", "backup", "restart"]
    assert bot.roster.auto_subscribe is True


@pytest.mark.asyncio
async def test_parse_owner_role_and_reply_shortcuts(monkeypatch, bot):
    monkeypatch.setattr(envsbot, "config", {"owner": "owner@example.org/res"})
    assert bot._parse_bare_jid("user@example.org/res", label="user") == "user@example.org"
    assert bot._parse_bare_jid("bad@@example", label="user") is None
    assert await bot._get_owner_bare_jid() == "owner@example.org"

    bot.db.users.get = AsyncMock(side_effect=[
        None,
        {"jid": "u@example.org"},
        {"jid": "u@example.org", "role": 80},
        {"jid": "legacy-owner@example.org", "role": envsbot.Role.OWNER.value},
        {"jid": "none@example.org", "role": envsbot.Role.NONE.value},
    ])
    assert await envsbot.Bot.get_user_role(bot, "missing@example.org") == envsbot.Role.NONE
    assert await envsbot.Bot.get_user_role(bot, "norole@example.org") == envsbot.Role.NONE
    assert await envsbot.Bot.get_user_role(bot, "user@example.org") == envsbot.Role.USER
    assert await envsbot.Bot.get_user_role(bot, "legacy-owner@example.org") == envsbot.Role.USER
    assert await envsbot.Bot.get_user_role(bot, "none@example.org") == envsbot.Role.USER
    assert await envsbot.Bot.get_user_role(bot, "owner@example.org") == envsbot.Role.OWNER
    assert await envsbot.Bot.get_user_role(bot, "bad@@example") == envsbot.Role.NONE

    sent = []
    monkeypatch.setattr(bot, "reply", lambda msg, text, **kwargs: sent.append((text, kwargs)))
    m = {"type": "chat", "get": lambda key, default=None: "chat" if key == "type" else default}
    bot.reply_ok(m, "done", mention=False)
    bot.reply_info(m, "heads up")
    bot.reply_warn(m, "careful")
    bot.reply_error(m, "broken")
    bot.reply_usage(m, ",demo <arg>")
    assert [text for text, _kwargs in sent] == [
        "✅ done",
        "ℹ️ heads up",
        "🟡️ careful",
        "🔴 broken",
        "🟡️ Usage: ,demo <arg>",
    ]
    assert sent[0][1]["mention"] is False


@pytest.mark.asyncio
async def test_reply_send_wrapper_and_muc_helper_edges(monkeypatch, bot):
    safe = AsyncMock()
    monkeypatch.setattr(bot, "_safe_send_message", safe)
    await envsbot.Bot._reply_send_wrapper(bot, "message")
    safe.assert_awaited_once_with("message")

    safe.side_effect = RuntimeError("boom")
    await envsbot.Bot._reply_send_wrapper(bot, "message")

    class BrokenPresence:
        @property
        def joined_rooms(self):
            raise RuntimeError("broken")

    bot.presence = BrokenPresence()
    import core_plugins.rooms as rooms_mod
    rooms_mod.JOINED_ROOMS.clear()
    rooms_mod.JOINED_ROOMS["room@conf"] = {"nicks": {"Alice": {"jid": "alice@example.org/res"}}}
    try:
        assert bot._joined_room_jids() == {"room@conf"}
        assert bot._is_muc_private_message({"type": "chat", "from": DummyFrom("room@conf", "Alice"), "get": lambda key, default=None: "chat" if key == "type" else default}) is True
        assert bot._is_muc_private_message({"type": "chat", "from": DummyFrom("room@conf", ""), "get": lambda key, default=None: "chat" if key == "type" else default}) is False
        assert bot._is_muc_private_message({"get": lambda key, default=None: default}) is False
        assert bot._get_message_room_and_nick({"from": DummyFrom("room@conf", "Alice"), "get": lambda key, default=None: None}) == ("room@conf", "Alice")
        assert bot._get_message_room_and_nick({}) == (None, None)
        bot.plugin = {"xep_0045": types.SimpleNamespace(get_jid_property=lambda *args: None)}
        assert bot._lookup_muc_occupant_jid("room@conf", "Alice") == "alice@example.org/res"
        assert bot._lookup_muc_occupant_jid("room@conf", "Missing") is None
    finally:
        rooms_mod.JOINED_ROOMS.clear()


@pytest.mark.asyncio
async def test_main_normal_path_closes_database(monkeypatch):
    calls = []

    class FakeDB:
        async def close(self):
            calls.append("db.close")

    class FakeXMPP:
        def __init__(self):
            self.disconnected = asyncio.Future()
            self.disconnected.set_result(None)
            self.db = FakeDB()

        def disconnect(self):
            calls.append("disconnect")

    fake_xmpp = FakeXMPP()
    monkeypatch.setattr(
        envsbot,
        "validate_startup_config",
        lambda cfg: calls.append(("validate", cfg)),
    )
    monkeypatch.setattr(envsbot, "Bot", lambda: fake_xmpp)

    async def fake_connect(xmpp):
        calls.append(("connect", xmpp))

    monkeypatch.setattr(envsbot, "connect_xmpp", fake_connect)

    await envsbot.main()

    assert calls == [
        ("validate", envsbot.config),
        ("connect", fake_xmpp),
        "db.close",
    ]


@pytest.mark.asyncio
async def test_main_config_error_uses_exit_handler(monkeypatch):
    error = envsbot.ConfigError("bad config")
    exit_handler = MagicMock(side_effect=SystemExit(2))
    bot_factory = MagicMock()

    def fail_validation(cfg):
        raise error

    monkeypatch.setattr(envsbot, "validate_startup_config", fail_validation)
    monkeypatch.setattr(envsbot, "exit_on_config_error", exit_handler)
    monkeypatch.setattr(envsbot, "Bot", bot_factory)

    with pytest.raises(SystemExit) as excinfo:
        await envsbot.main()

    assert excinfo.value.code == 2
    exit_handler.assert_called_once_with(error)
    bot_factory.assert_not_called()


@pytest.mark.asyncio
async def test_main_shutdown_timeout_and_close_error(monkeypatch):
    calls = []

    class RestartableDisconnected:
        def __init__(self):
            self.await_count = 0

        def __await__(self):
            async def inner():
                self.await_count += 1
                if self.await_count == 1:
                    raise KeyboardInterrupt()
                return None

            return inner().__await__()

    class FakeDB:
        async def close(self):
            calls.append("db.close")
            raise RuntimeError("close failed")

    class FakeXMPP:
        def __init__(self):
            self.disconnected = RestartableDisconnected()
            self.db = FakeDB()

        def disconnect(self):
            calls.append("disconnect")

    fake_xmpp = FakeXMPP()
    monkeypatch.setattr(
        envsbot,
        "validate_startup_config",
        lambda cfg: calls.append("validate"),
    )
    monkeypatch.setattr(envsbot, "Bot", lambda: fake_xmpp)

    async def fake_connect(xmpp):
        calls.append("connect")

    async def fake_wait_for(awaitable, timeout):
        calls.append(("wait_for", awaitable, timeout))
        raise asyncio.TimeoutError()

    monkeypatch.setattr(envsbot, "connect_xmpp", fake_connect)
    monkeypatch.setattr(envsbot.asyncio, "wait_for", fake_wait_for)

    await envsbot.main()

    assert calls == [
        "validate",
        "connect",
        "disconnect",
        ("wait_for", fake_xmpp.disconnected, 2.0),
        "db.close",
    ]


def test_copy_initial_chat_slang_paths(tmp_path, monkeypatch):
    source = tmp_path / "init_chat_slang.csv"
    target = tmp_path / "chat_slang.csv"
    source.write_text("hello,world\n", encoding="utf-8")

    envsbot.copy_initial_chat_slang(str(source), str(target))
    assert target.read_text(encoding="utf-8") == "hello,world\n"

    source.write_text("changed\n", encoding="utf-8")
    envsbot.copy_initial_chat_slang(str(source), str(target))
    assert target.read_text(encoding="utf-8") == "hello,world\n"

    missing_target = tmp_path / "missing_chat_slang.csv"
    envsbot.copy_initial_chat_slang(
        str(tmp_path / "missing.csv"),
        str(missing_target),
    )
    assert not missing_target.exists()

    error_target = tmp_path / "error_chat_slang.csv"

    def fail_copy(_source, _target):
        raise OSError("nope")

    monkeypatch.setattr(envsbot.shutil, "copyfile", fail_copy)
    envsbot.copy_initial_chat_slang(str(source), str(error_target))
    assert not error_target.exists()


def test_cli_runs_main_and_handles_keyboard_interrupt(monkeypatch):
    calls = []

    async def fake_main():
        calls.append("main")

    def fake_copy():
        calls.append("copy")

    def run_success(coro):
        calls.append("run")
        coro.close()

    monkeypatch.setattr(envsbot, "copy_initial_chat_slang", fake_copy)
    monkeypatch.setattr(envsbot, "main", fake_main)
    monkeypatch.setattr(envsbot.asyncio, "run", run_success)

    envsbot.cli()
    assert calls == ["copy", "run"]

    def run_interrupted(coro):
        calls.append("run-interrupted")
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(envsbot.asyncio, "run", run_interrupted)
    envsbot.cli()
    assert calls[-2:] == ["copy", "run-interrupted"]

def test_configured_rate_limit_bypass_role_edges(monkeypatch):
    monkeypatch.setattr(envsbot, "config", {"command_rate_limit_bypass_role": " admin "})
    assert envsbot._configured_rate_limit_bypass_role() is envsbot.Role.ADMIN
    assert envsbot._role_bypasses_rate_limit(envsbot.Role.OWNER) is True
    assert envsbot._role_bypasses_rate_limit(envsbot.Role.ADMIN) is True
    assert envsbot._role_bypasses_rate_limit(envsbot.Role.MODERATOR) is False

    monkeypatch.setattr(envsbot, "config", {"command_rate_limit_bypass_role": "off"})
    assert envsbot._configured_rate_limit_bypass_role() is None
    assert envsbot._role_bypasses_rate_limit(envsbot.Role.OWNER) is False

    monkeypatch.setattr(envsbot, "config", {"command_rate_limit_bypass_role": "unknown"})
    assert envsbot._configured_rate_limit_bypass_role() is envsbot.Role.MODERATOR

    monkeypatch.setattr(envsbot, "config", {})
    assert envsbot._configured_rate_limit_bypass_role() is envsbot.Role.MODERATOR
