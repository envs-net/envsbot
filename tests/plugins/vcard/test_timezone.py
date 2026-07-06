from .helpers import *  # noqa: F401,F403


@pytest.mark.asyncio
async def test_set_timezone_command(fake_bot, monkeypatch):
    async def get_global(key, default=None): return {}
    async def set(j, k, v): pass
    fake_bot.db.users.plugin = lambda p: SimpleNamespace(
        get_global=get_global, set=set)

    async def _get_enabled_rooms(b, k, p): return {"bob@b": True}
    monkeypatch.setattr(vcard._core, "_get_enabled_rooms", _get_enabled_rooms)
    async def _check_user_exists(b, jid, msg): return True
    monkeypatch.setattr(vcard._core, "_check_user_exists", _check_user_exists)
    m = msg(from_jid="bob@b/resource")
    m["type"] = "chat"
    await vcard.set_timezone(fake_bot, "s", "n", ["Europe/Berlin"], m, False)
    found = any("TIMEZONE set to" in t[0]
                for t in getattr(fake_bot, "_replies", []))
    assert found


@pytest.mark.asyncio
async def test_set_timezone_invalid(fake_bot, monkeypatch):
    async def get_global(key, default=None): return {}
    async def set(j, k, v): pass
    fake_bot.db.users.plugin = lambda p: SimpleNamespace(
        get_global=get_global, set=set)

    async def _get_enabled_rooms(b, k, p): return {"bob@b": True}
    monkeypatch.setattr(vcard._core, "_get_enabled_rooms", _get_enabled_rooms)
    async def _check_user_exists(b, jid, msg): return True
    monkeypatch.setattr(vcard._core, "_check_user_exists", _check_user_exists)
    m = msg(from_jid="bob@b/resource")
    m["type"] = "chat"
    await vcard.set_timezone(fake_bot, "s", "n", ["NotAZone"], m, False)
    assert any("Invalid timezone" in t[0]
               for t in getattr(fake_bot, "_replies", []))


@pytest.mark.asyncio
async def test_vcard_field_room_lookup_and_timezone_branches(fake_bot, monkeypatch):
    monkeypatch.setattr(
        vcard._core,
        "get_real_jid_from_occupant",
        lambda bot, msg, target_nick: "alice@example.org",
    )
    monkeypatch.setattr(
        vcard._core,
        "_get_user_timezone",
        AsyncMock(return_value="Europe/Berlin"),
    )
    m = msg(from_jid="room@x/Alice", type_="groupchat")

    value = await vcard.vcard_field(fake_bot, m, "Alice", "TIMEZONE", is_room=True)

    assert value == "Europe/Berlin"
    vcard._core._get_user_timezone.assert_awaited_once_with(fake_bot, "alice@example.org")


@pytest.mark.asyncio
async def test_vcard_field_returns_none_for_invalid_missing_and_empty_timezone(fake_bot, monkeypatch):
    m = msg(from_jid="room@x/Alice", type_="groupchat")

    assert await vcard.vcard_field(fake_bot, m, "Alice", "UNKNOWN", is_room=True) is None

    monkeypatch.setattr(
        vcard._core,
        "get_real_jid_from_occupant",
        lambda bot, msg, target_nick: None,
    )
    assert await vcard.vcard_field(fake_bot, m, "Missing", "FN", is_room=True) is None

    monkeypatch.setattr(
        vcard._core,
        "get_real_jid_from_occupant",
        lambda bot, msg, target_nick: "alice@example.org",
    )
    monkeypatch.setattr(vcard._core, "_get_user_timezone", AsyncMock(return_value=None))
    assert await vcard.vcard_field(fake_bot, m, "Alice", "TIMEZONE", is_room=True) is None


@pytest.mark.asyncio
async def test_get_vcard_timezone_and_get_vcard_info_paths(fake_bot, monkeypatch):
    m = msg(from_jid="room@x/Alice", type_="chat")
    monkeypatch.setattr(vcard._core, "_is_muc_pm", lambda msg: True)
    monkeypatch.setattr(vcard._core, "_get_user_timezone", AsyncMock(return_value="Europe/Berlin"))
    monkeypatch.setattr(vcard._core, "get_real_jid", AsyncMock(return_value=("real@example.org", None, None)))

    assert await vcard._get_vcard_timezone(fake_bot, m, "target@example.org", True, ["Alice"]) == "Europe/Berlin"
    vcard._core._get_user_timezone.assert_awaited_with(fake_bot, "target@example.org")
    assert await vcard._get_vcard_timezone(fake_bot, m, None, True, ["Alice"]) is None
    assert await vcard._get_vcard_timezone(fake_bot, m, "ignored@example.org", True, []) == "Europe/Berlin"

    result_vcard = RichDummyVcard()
    plugin = SimpleNamespace(get_vcard=AsyncMock(return_value={"vcard_temp": result_vcard}))
    fake_bot.plugin = {"xep_0054": plugin}
    assert await ORIGINAL_GET_VCARD(fake_bot, m, "alice@example.org") is result_vcard
    plugin.get_vcard.assert_awaited_once()

    plugin.get_vcard = AsyncMock(side_effect=RuntimeError("boom"))
    assert await ORIGINAL_GET_VCARD(fake_bot, m, "alice@example.org") is None

    fake_bot.plugin = {}
    with pytest.raises(RuntimeError):
        await ORIGINAL_GET_VCARD(fake_bot, m, "alice@example.org")

    monkeypatch.setattr(vcard, "get_user_vcard", AsyncMock(return_value={"FN": "Alice"}))
    assert await vcard.get_info(fake_bot, m, "alice@example.org") == {"FN": "Alice"}
    vcard.get_user_vcard.return_value = None
    assert await vcard.get_info(fake_bot, m, "alice@example.org") is None
