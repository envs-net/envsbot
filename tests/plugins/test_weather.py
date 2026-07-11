import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, Mock, MagicMock
from types import SimpleNamespace
import plugins.weather as weather

ORIGINAL_GET_WEATHER_STORE = weather.get_weather_store

# --- Support patching of weather.JOINED_ROOMS ---


@pytest_asyncio.fixture(autouse=True)
def patch_joined_rooms(monkeypatch):
    join_data = {
        "testroom@conference.example.com": {
            "nicks": {
                "Alice": {"jid": "alice@example.com"},
                "Bob": {"jid": "bob@example.com"},
            }
        }
    }
    monkeypatch.setattr(weather, "JOINED_ROOMS", join_data)


@pytest_asyncio.fixture(autouse=True)
def patch_config(monkeypatch):
    class DummyConfig(dict):
        def get(self, key, default=None):
            return self[key] if key in self else default
    cfg = DummyConfig({"weather_api_key": "TESTKEY", "prefix": ","})
    monkeypatch.setattr(weather, "config", cfg)


@pytest_asyncio.fixture
def fake_bot():
    class DummyStore:
        async def get(self, jid, key, default=None): return None
        async def set(self, *a, **k): pass
        async def get_global(self, k, default=None): return {}

    class DummyUsers:
        def plugin(self, _): return DummyStore()

    class DummyDB:
        users = DummyUsers()
    bot = Mock()
    bot.db = DummyDB()
    bot.bot_plugins = Mock()
    bot.plugin = {}
    bot.presence = Mock()
    bot.presence.emoji = lambda status: "😀"
    bot.reply = Mock()
    return bot


@pytest_asyncio.fixture
def fake_msg():
    """Standard groupchat message with mucnick."""
    return {
        "from": Mock(bare="testroom@conference.example.com", resource="Alice"),
        "body": ",weather",
        "mucnick": "Alice",
        "type": "groupchat"
    }

# Patch plumbing helpers from _core and our own DB


@pytest_asyncio.fixture(autouse=True)
def patch_plugins(monkeypatch):
    monkeypatch.setattr(
        weather._core, "handle_room_toggle_command",
        AsyncMock(return_value=False))
    monkeypatch.setattr(weather._core, "_get_enabled_rooms", AsyncMock(
        return_value={"testroom@conference.example.com": True}))
    monkeypatch.setattr(weather._core, "_is_muc_pm", lambda msg: False)
    monkeypatch.setattr(weather, "get_weather_store",
                        AsyncMock(return_value=Mock()))


@pytest_asyncio.fixture
def patch_aiohttp(monkeypatch):
    """Patch aiohttp.ClientSession to return a weather string."""
    class DummyResp:
        status = 200

        async def text(self):
            return "Berlin: Sunny 21°C 🌤️"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class DummyAiohttpSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def get(self, *a, **k): return DummyResp()
    monkeypatch.setattr(weather, "aiohttp", Mock(
        ClientSession=DummyAiohttpSession))


@pytest_asyncio.fixture(autouse=True)
def patch_vcard(monkeypatch):
    # Default: LOCALITY=Berlin, to satisfy minimum weather lookups
    monkeypatch.setattr(weather.vcard, "get_user_vcard",
                        AsyncMock(return_value={"LOCALITY": "Berlin"}))
    monkeypatch.setattr(weather.vcard, "vcard_field",
                        AsyncMock(return_value="Berlin"))


def output_of_reply(reply):
    out = reply.call_args[0][1]
    if isinstance(out, list):
        out = ' '.join(out)
    return out


@pytest.mark.asyncio
async def test_weather_command_happy_path(fake_bot, fake_msg,
                                          patch_plugins, patch_aiohttp):
    await weather.weather_command(fake_bot, "jid", "Alice", [],
                                  fake_msg, True)
    fake_bot.reply.assert_called()
    out = output_of_reply(fake_bot.reply)
    assert "Berlin" in out
    assert "Sunny" in out
    assert "Forecast: https://wttr.in/Berlin" in out


@pytest.mark.asyncio
async def test_weather_with_nick(fake_bot, fake_msg, patch_plugins,
                                 patch_aiohttp):
    # Use Bob for the target nick and London as location
    nicks = weather.JOINED_ROOMS["testroom@conference.example.com"]["nicks"]
    with patch.dict(nicks, {"Bob": {"jid": "bob@example.com"}}, clear=False), \
            patch.object(weather.vcard, "get_user_vcard",
                         AsyncMock(return_value={"LOCALITY": "London"})), \
            patch.object(weather.vcard, "vcard_field",
                         AsyncMock(return_value="London")):
        fake_msg["body"] = ",weather Bob"
        await weather.weather_command(fake_bot, "jid", "Alice", ["Bob"],
                                      fake_msg, True)
        fake_bot.reply.assert_called()
        out = output_of_reply(fake_bot.reply)
        # Should at least contain Bob or London somewhere!
        assert "London" in out or "Bob" in out


@pytest.mark.asyncio
async def test_weather_with_direct_city(fake_bot, fake_msg, patch_plugins,
                                        patch_aiohttp):
    fake_msg["body"] = ",w Dresden"

    await weather.weather_command(fake_bot, "jid", "Alice", ["Dresden"],
                                  fake_msg, True)

    fake_bot.reply.assert_called()
    out = output_of_reply(fake_bot.reply)
    assert "Weather for Dresden" in out
    assert "Dresden: Dresden" not in out
    assert "Forecast: https://wttr.in/Dresden" in out


@pytest.mark.asyncio
async def test_weather_with_direct_zip(fake_bot, fake_msg, patch_plugins,
                                       patch_aiohttp):
    fake_msg["body"] = ",w 01067"

    await weather.weather_command(fake_bot, "jid", "Alice", ["01067"],
                                  fake_msg, True)

    fake_bot.reply.assert_called()
    out = output_of_reply(fake_bot.reply)
    assert "Weather for 01067" in out
    assert "01067: 01067" not in out
    assert "Forecast: https://wttr.in/01067" in out


@pytest.mark.asyncio
async def test_weather_no_location(fake_bot, fake_msg, patch_plugins,
                                   patch_aiohttp):
    # .vcard_field returns {}
    with patch.object(weather.vcard, "get_user_vcard",
                      AsyncMock(return_value={})):
        await weather.weather_command(fake_bot, "jid", "Alice", [],
                                      fake_msg, True)
        fake_bot.reply.assert_called()
        out = output_of_reply(fake_bot.reply).lower()
        assert "no location" in out or "no location" in out.replace(" ", "")


@pytest.mark.asyncio
async def test_weather_api_fail(fake_bot, fake_msg, patch_plugins,
                                monkeypatch):
    """Simulate a 404/failure status"""
    class FailResp:
        status = 404

        async def text(self):
            return "Error from wttr"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class DummyAiohttpSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def get(self, *a, **k):
            return FailResp()

    monkeypatch.setattr(weather, "aiohttp", Mock(
        ClientSession=DummyAiohttpSession))
    with patch.object(weather.vcard, "get_user_vcard",
                      AsyncMock(return_value={"LOCALITY": "Berlin"})):
        await weather.weather_command(fake_bot, "jid", "Alice", [],
                                      fake_msg, True)
        fake_bot.reply.assert_called()
        out = output_of_reply(fake_bot.reply).lower()
        assert "failed" in out or "fetch" in out or "error" in out


@pytest.mark.asyncio
async def test_weather_keyerror_mucnick(fake_bot, fake_msg, patch_plugins,
                                        patch_aiohttp):
    # Simulate a msg lacking 'mucnick'
    msg = dict(fake_msg)
    msg.pop("mucnick", None)
    # Plugin should handle this gracefully, see plugin note below
    # (ideally plugin is patched to return a message about missing mucnick)
    with patch.object(weather.vcard, "get_user_vcard",
                      AsyncMock(return_value={"LOCALITY": "Berlin"})):
        await weather.weather_command(fake_bot, "jid", "Alice", [],
                                      msg, True)
        fake_bot.reply.assert_called()
        out = output_of_reply(fake_bot.reply).lower()
        # Should detect missing mucnick
        assert "berlin" in out


@pytest.mark.asyncio
async def test_weather_unicode_location(fake_bot, fake_msg, patch_plugins,
                                        patch_aiohttp):
    with patch.object(weather.vcard, "get_user_vcard",
                      AsyncMock(return_value={"LOCALITY":
                                              "München Hauptbahnhof"})), \
            patch.object(weather.vcard, "vcard_field",
                         AsyncMock(return_value="München Hauptbahnhof")), \
            patch.object(weather, "get_display_name",
                         AsyncMock(return_value="Alice")), \
            patch.object(weather, "aiohttp") as fake_aiohttp:
        # Provide a unicode-aware weather service
        class DummyResp:
            status = 200

            async def text(self):
                return "München Hauptbahnhof: Snow ❄️ -3°C"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class DummySession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            def get(self, *a, **k):
                return DummyResp()

        fake_aiohttp.ClientSession.return_value = DummySession()
        await weather.weather_command(fake_bot, "jid", "Alice", [],
                                      fake_msg, True)
        fake_bot.reply.assert_called()
        output = output_of_reply(fake_bot.reply)
        assert "münchen" in output.lower(
        ) or "hauptbahnhof" in output.lower() or "snow" in output.lower()


@pytest.mark.asyncio
async def test_weather_command_direct_message_success(
    fake_bot,
    patch_aiohttp,
    monkeypatch,
):
    monkeypatch.setattr(
        weather.vcard,
        "get_user_vcard",
        AsyncMock(
            return_value={"LOCALITY": "Berlin", "REGION": None, "CTRY": None}
        ),
    )
    msg = {
        "from": Mock(bare="alice@example.org", resource="laptop"),
        "body": ",weather",
        "type": "chat",
    }

    await weather.weather_command(
        fake_bot,
        "alice@example.org",
        "Alice",
        [],
        msg,
        False,
    )

    fake_bot.reply.assert_called()
    out = output_of_reply(fake_bot.reply)
    assert "Weather for you" in out
    assert "Berlin" in out


@pytest.mark.asyncio
async def test_weather_command_direct_message_accepts_direct_location(
    fake_bot,
    patch_aiohttp,
):
    msg = {
        "from": Mock(bare="alice@example.org", resource="laptop"),
        "body": ",w Dresden Neustadt",
        "type": "chat",
    }

    await weather.weather_command(
        fake_bot,
        "alice@example.org",
        "Alice",
        ["Dresden", "Neustadt"],
        msg,
        False,
    )

    fake_bot.reply.assert_called()
    out = output_of_reply(fake_bot.reply)
    assert "Weather for Dresden Neustadt" in out
    assert "Forecast: https://wttr.in/Dresden%20Neustadt" in out


@pytest.mark.asyncio
async def test_weather_command_direct_message_vcard_failure(
    fake_bot,
    monkeypatch,
):
    monkeypatch.setattr(
        weather.vcard,
        "get_user_vcard",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    msg = {
        "from": Mock(bare="alice@example.org", resource="laptop"),
        "body": ",weather",
        "type": "chat",
    }

    await weather.weather_command(
        fake_bot,
        "alice@example.org",
        "Alice",
        [],
        msg,
        False,
    )

    fake_bot.reply.assert_called_once()
    assert "Failed to retrieve your vCard" in output_of_reply(fake_bot.reply)


@pytest.mark.asyncio
async def test_weather_command_muc_pm_success(
    fake_bot,
    patch_aiohttp,
    monkeypatch,
):
    monkeypatch.setattr(weather._core, "_is_muc_pm", lambda msg: True)
    monkeypatch.setattr(
        weather.vcard,
        "get_user_vcard",
        AsyncMock(
            return_value={"LOCALITY": None, "REGION": "Saxony", "CTRY": "DE"}
        ),
    )
    msg = {
        "from": Mock(bare="testroom@conference.example.com", resource="Alice"),
        "body": ",weather",
        "type": "chat",
    }

    await weather.weather_command(
        fake_bot,
        "alice@example.org",
        "Alice",
        [],
        msg,
        False,
    )

    fake_bot.reply.assert_called()
    out = output_of_reply(fake_bot.reply)
    assert "Weather for Alice" in out
    assert "Saxony" in out


@pytest.mark.asyncio
async def test_weather_command_muc_pm_disabled_or_direct_location(
    fake_bot,
    monkeypatch,
    patch_aiohttp,
):
    monkeypatch.setattr(weather._core, "_is_muc_pm", lambda msg: True)
    msg = {
        "from": Mock(bare="testroom@conference.example.com", resource="Alice"),
        "body": ",weather",
        "type": "chat",
    }

    monkeypatch.setattr(
        weather._core,
        "_get_enabled_rooms",
        AsyncMock(return_value={}),
    )
    await weather.weather_command(
        fake_bot,
        "alice@example.org",
        "Alice",
        [],
        msg,
        False,
    )
    fake_bot.reply.assert_not_called()

    monkeypatch.setattr(
        weather._core,
        "_get_enabled_rooms",
        AsyncMock(return_value={"testroom@conference.example.com": True}),
    )
    await weather.weather_command(
        fake_bot,
        "alice@example.org",
        "Alice",
        ["Missing"],
        msg,
        False,
    )
    fake_bot.reply.assert_called_once()
    out = output_of_reply(fake_bot.reply)
    assert "Weather for Missing" in out
    assert "Forecast: https://wttr.in/Missing" in out


@pytest.mark.asyncio
async def test_weather_command_muc_pm_missing_resource(fake_bot, monkeypatch):
    monkeypatch.setattr(weather._core, "_is_muc_pm", lambda msg: True)
    msg = {
        "from": Mock(bare="testroom@conference.example.com", resource=""),
        "body": ",weather",
        "type": "chat",
    }

    await weather.weather_command(
        fake_bot,
        "alice@example.org",
        "Alice",
        [],
        msg,
        False,
    )

    fake_bot.reply.assert_called_once()
    assert "determine your nickname" in output_of_reply(fake_bot.reply)


def test_weather_target_and_location_helpers():
    bare, nick = weather.get_pm_target(Mock(bare="alice@example.org"), "Alice")
    assert (bare, nick) == ("alice@example.org", "Alice")
    assert weather.get_pm_target("bob@example.org/device", "Bob") == (
        "bob@example.org",
        "Bob",
    )
    assert weather._extract_location_fields(
        {"LOCALITY": "City", "REGION": "State", "CTRY": "DE"}
    ) == (
        "City",
        "State",
        "DE",
    )
    assert weather._select_location(None, None, "DE") == "DE"
    assert weather._select_location(None, "Berlin", "DE") == "Berlin"
    assert weather._select_location("Kreuzberg", "Berlin", "DE") == "Kreuzberg"
    assert weather._select_location(None, None, None) == ""
    assert weather._location_from_args(["Dresden", "Neustadt"]) == (
        "Dresden Neustadt"
    )
    assert weather._resolve_direct_location(["Dresden"], {"Alice": {}}) == (
        "Dresden"
    )
    assert weather._resolve_direct_location(["Alice"], {"Alice": {}}) is None
    assert weather._build_wttr_urls("München Hauptbahnhof") == (
        "https://wttr.in/M%C3%BCnchen%20Hauptbahnhof",
        "https://wttr.in/M%C3%BCnchen%20Hauptbahnhof?format=4&m",
    )
    assert weather._parse_wttr_weather("Berlin: Sunny 21°C") == (
        "Berlin",
        "Sunny 21°C",
    )
    assert weather._parse_wttr_weather("Sunny 21°C") == (
        "",
        "Sunny 21°C",
    )
    assert weather._format_weather_reply(
        "Berlin",
        "Berlin",
        "Berlin: Sunny 21°C",
    ) == "🌤️ Weather for Berlin: Sunny 21°C"
    assert weather._format_weather_reply(
        "alice@example.org",
        "Saxony",
        "Saxony: Sunny 21°C",
    ) == "🌤️ Weather for alice@example.org (Saxony): Sunny 21°C"
    assert weather._format_weather_reply(
        "Dresden Neustadt",
        "Dresden Neustadt",
        "Dresden: Sunny 21°C",
    ) == "🌤️ Weather for Dresden Neustadt: Dresden: Sunny 21°C"


@pytest.mark.asyncio
async def test_get_display_name_uses_first_roomnick_and_fallbacks(caplog):
    class Store:
        def __init__(self, value=None, exc=None):
            self.value = value
            self.exc = exc

        async def get(self, jid, key):
            assert jid == "alice@example.org"
            assert key == "roomnicks"
            if self.exc:
                raise self.exc
            return self.value

    class Users:
        def __init__(self, store):
            self.store = store

        def plugin(self, name):
            assert name == "users"
            return self.store

    bot = Mock()
    bot.db.users = Users(Store({"room1": [], "room2": ["Alice", "Ali"]}))
    assert await weather.get_display_name(bot, "alice@example.org") == "Alice"

    bot.db.users = Users(Store({"room1": []}))
    assert await weather.get_display_name(
        bot,
        "alice@example.org",
    ) == "unknown"

    bot.db.users = Users(Store(exc=RuntimeError("db down")))
    assert await weather.get_display_name(
        bot,
        "alice@example.org",
    ) == "unknown"


@pytest.mark.asyncio
async def test_weather_store_getter_uses_plugin_store():
    marker = object()
    bot = SimpleNamespace(
        db=SimpleNamespace(
            users=SimpleNamespace(plugin=MagicMock(return_value=marker))
        )
    )
    assert await ORIGINAL_GET_WEATHER_STORE(bot) is marker
    bot.db.users.plugin.assert_called_once_with("weather")


@pytest.mark.asyncio
async def test_fetch_wttr_weather_falls_back_to_plain_http(monkeypatch):
    calls = []

    async def fake_fetch_text(url, **kwargs):
        calls.append(url)
        if url.startswith("https://"):
            raise OSError("tls failed")
        return SimpleNamespace(status=200, text="Berlin: Sunny 21°C")

    monkeypatch.setattr(weather, "fetch_text", fake_fetch_text)

    result = await weather._fetch_wttr_weather_text(
        "https://wttr.in/Berlin?format=4&m"
    )

    assert result == "Berlin: Sunny 21°C"
    assert calls == [
        "https://wttr.in/Berlin?format=4&m",
        "http://wttr.in/Berlin?format=4&m",
    ]


@pytest.mark.asyncio
async def test_fetch_wttr_weather_reports_all_failed_candidates(monkeypatch):
    async def fake_fetch_text(url, **kwargs):
        return SimpleNamespace(status=503, text="temporarily unavailable")

    monkeypatch.setattr(weather, "fetch_text", fake_fetch_text)

    with pytest.raises(weather.WeatherFetchError) as exc_info:
        await weather._fetch_wttr_weather_text(
            "https://wttr.in/Berlin?format=4&m"
        )

    message = str(exc_info.value)
    assert "https://wttr.in/Berlin?format=4&m: HTTP 503" in message
    assert "http://wttr.in/Berlin?format=4&m: HTTP 503" in message


@pytest.mark.asyncio
async def test_fetch_wttr_weather_uses_curl_like_plain_text_headers(monkeypatch):
    captured = []

    async def fake_fetch_text(url, **kwargs):
        captured.append((url, kwargs))
        return SimpleNamespace(status=200, text="Berlin: Sunny 21°C")

    monkeypatch.setattr(weather, "fetch_text", fake_fetch_text)

    assert await weather._fetch_wttr_weather_text(
        "https://wttr.in/Berlin?format=4&m"
    ) == "Berlin: Sunny 21°C"

    _url, kwargs = captured[0]
    assert kwargs["headers"]["User-Agent"].startswith("curl/")
    assert "text/plain" in kwargs["headers"]["Accept"]
    assert kwargs["max_bytes"] == weather.WEATHER_MAX_BYTES


@pytest.mark.asyncio
async def test_fetch_wttr_weather_rejects_html_response(monkeypatch):
    async def fake_fetch_text(url, **kwargs):
        return SimpleNamespace(
            status=200,
            text="<!doctype html><html>no compact weather</html>",
        )

    monkeypatch.setattr(weather, "fetch_text", fake_fetch_text)

    with pytest.raises(weather.WeatherFetchError) as exc_info:
        await weather._fetch_wttr_weather_text(
            "https://wttr.in/Berlin?format=4&m"
        )

    assert "HTML response" in str(exc_info.value)
